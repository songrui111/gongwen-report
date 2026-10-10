"""provider 契约：SSE 逐字节喂也一字不差、增量回调自洽。一次网络都不发。
"""
import inspect
import io
import json
import os
import re
import sys
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _harness import Tally, main_hook                        # noqa: E402

from gongwen import generate as G                            # noqa: E402
from gongwen.provider import (Completer, OpenAICompat, UpstreamError,  # noqa: E402
                              from_env)

PIECES = ('# 关于某市低空经济产业的报告\n\n',
          '某市低空经济产业近三年保持两位数增长，',
          '2025 年全产业链产值 412.6 亿元。\n\n',
          '## 一、摘要\n\n本文以……')


def data_line(piece):
    """→ 一条 `data: {...}` 行的字节（中文要 encode，不能写成 bytes 字面量）。"""
    body = json.dumps({'choices': [{'delta': {'content': piece}}]}, ensure_ascii=False)
    return ('data: ' + body + '\n\n').encode('utf-8')


def sse(*pieces, tail=b'', done=True):
    """→ 一份 SSE 响应的字节流。`tail` 是塞在 `[DONE]` 之后的垃圾。"""
    out = bytearray()
    for p in pieces:
        out += data_line(p)
    if done:
        out += b'data: [DONE]\n\n' + tail
    return bytes(out)


class FakeResp:
    """假的响应对象。

    **按行迭代，不是按块** —— 真的 `http.client.HTTPResponse` 就是这么做的：内部用
    readline，跨 TCP 包的半个行它自己会接着取下一块拼起来。这里连「半个行」也照做，
    于是可以放心地按 1 字节一块喂：**我们这个读法不关心包边界落在哪**，那是传输层的
    责任。（第一版我把它写成「按块迭代」，于是 1 字节一块时一行都被拆成了一条条
    「行」，读出来是空的 —— 假对象没照着真对象的行为写，测出来的就是假对象的行为。）
    """

    def __init__(self, chunks):
        self.chunks = list(chunks)
        self.buf = b''

    def readline(self):
        while b'\n' not in self.buf:
            if not self.chunks:
                out, self.buf = self.buf, b''
                return out
            self.buf += self.chunks.pop(0)
        i = self.buf.index(b'\n') + 1
        out, self.buf = self.buf[:i], self.buf[i:]
        return out

    def __iter__(self):
        return self

    def __next__(self):
        ln = self.readline()
        if not ln:
            raise StopIteration
        return ln

    def read(self):
        return b''.join(self.chunks)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class FakeOpener:
    """假的 opener：要么给一份响应，要么按剧本抛错。**不碰 socket。**"""

    def __init__(self, resp=None, error=None):
        self.resp = resp
        self.error = error
        self.calls = []

    def open(self, req, timeout=None):
        self.calls.append((req, timeout))
        if self.error is not None:
            raise self.error
        return self.resp


class FakeProvider(Completer):
    name = 'fake'

    def __init__(self, pieces=PIECES, ok=True):
        self.pieces = pieces
        self.ok = ok

    def available(self):
        return self.ok

    def complete(self, system, user, on_delta=None):
        parts = []
        for p in self.pieces:
            parts.append(p)
            if on_delta is not None:
                on_delta(p, ''.join(parts))
        return ''.join(parts)


def req(topic='某市低空经济产业'):
    return G.build(topic)


def main():
    t = Tally()

    print('--- 一、拼起来必须一字不差（换着包边界喂）')
    want = ''.join(PIECES)
    resp = sse(*PIECES)
    for label, chunks in (
            ('整块', [resp]),
            ('按 1 字节', [resp[i:i + 1] for i in range(len(resp))]),
            ('按 3 字节', [resp[i:i + 3] for i in range(0, len(resp), 3)]),
            ('一行一块', resp.splitlines(keepends=True))):
        got = OpenAICompat.read_stream(FakeResp(chunks))
        t(got == want, f'{label}：拼回来和原样相同（{len(got)} 字）')

    print('--- 二、SSE 的边界情况')
    t(OpenAICompat.read_stream(FakeResp([sse(*PIECES, tail=data_line('不该出现'))])) == want,
      '[DONE] 之后就停（后面的字节一律不看）')
    junk = (': 注释行\n\n'
            'data: {坏掉的 json\n\n'
            'data: {"choices":[]}\n\n'
            'data: {"choices":[{"delta":{}}]}\n\n'
            'data: {"choices":[{"delta":{"content":""}}]}\n\n'
            'not-data at all\n\n'
            'data: [DONE]\n\n').encode('utf-8')
    got = OpenAICompat.read_stream(FakeResp([junk]))
    t(got == '', f'坏行、空增量、没有 data: 前缀的行都跳过（拿到 {got!r}）')
    t(OpenAICompat.read_stream(FakeResp([b'data: [DONE]\n\n'])) == '', '一上来就 [DONE]：空报告')
    t(OpenAICompat.read_stream(FakeResp([b''])) == '', '空响应：空报告')

    print('--- 三、增量回调自洽（进度条不能骗人）')
    seen = []
    text = OpenAICompat.read_stream(FakeResp([sse(*PIECES)]),
                                    on_delta=lambda p, tot: seen.append((p, tot)))
    t(''.join(p for p, _ in seen) == text, '把每次 piece 拼起来 == 返回值')
    t([tot for _, tot in seen] == [''.join(p for p, _ in seen[:i + 1])
                                   for i in range(len(seen))],
      '每次给的 total 都是「到目前为止拼出来的全部」')
    t(len(seen) == len(PIECES), f'每个非空增量调一次（{len(seen)} 次）')

    print('--- 四、generate.run：攒字、报进度、不落盘')
    echo = []
    got = G.run(req(), FakeProvider(), progress_every=10, echo=echo.append)
    t(got == want, 'run() 拿回整份报告')
    t(echo and echo[-1].endswith(f'已收到 {len(want)} 字'), f'收尾时报了总字数（{echo[-1]}）')
    t(all('已收到' in s for s in echo), '进度行都是「已收到 N 字」')
    t(len(echo) <= len(want) // 10 + 2, f'不是每个字都报一次（{len(echo)} 行 / {len(want)} 字）')
    t(G.run(req(), FakeProvider(), echo=None) == want, '不给 echo 也能跑（无需回调）')

    n = [0]
    G.run(req(), FakeProvider(pieces=['一'] * 50), progress_every=10,
          echo=lambda s: n.__setitem__(0, n[0] + 1))
    t(n[0] >= 5, f'每满 10 字报一次（报了 {n[0]} 次）')

    print('--- 五、没配 key：不发请求')
    empty = FakeProvider(ok=False)
    try:
        G.run(req(), empty)
        t(False, '没配 key 必须抛 UpstreamError —— 没抛')
    except UpstreamError as e:
        t('没配 key' in str(e) and '--print-system' in str(e),
          '抛 UpstreamError，并指向零密钥那条路')
    p = OpenAICompat('')
    op = FakeOpener(resp=FakeResp([sse(*PIECES)]))
    p._opener = op
    try:
        p.complete('s', 'u')
        t(False, 'provider.complete 没配 key 也要抛')
    except UpstreamError:
        t(True, 'provider.complete 没配 key 也抛 UpstreamError')
    t(not op.calls, '而且**一个请求都没发出去**（不是发出去等 401）')

    print('--- 六、上游出错：抛 UpstreamError，带上够查的信息')
    body = b'{"error":{"message":"invalid api key"}}'
    for label, err, want_in in (
            ('非 200', urllib.error.HTTPError('u', 401, 'Unauthorized', {}, io.BytesIO(body)),
             '401'),
            ('连不上', urllib.error.URLError('getaddrinfo failed'), '连不上')):
        p = OpenAICompat('k')
        p._opener = FakeOpener(error=err)
        try:
            p.complete('s', 'u')
            t(False, f'{label} 必须抛 UpstreamError —— 没抛')
        except UpstreamError as e:
            t(want_in in str(e), f'{label}：抛 UpstreamError 且带上线索（{str(e)[:60]}…）')
    p = OpenAICompat('k')
    p._opener = FakeOpener(error=urllib.error.HTTPError('u', 401, 'x', {},
                                                        io.BytesIO(body)))
    try:
        p.complete('s', 'u')
    except UpstreamError as e:
        t('invalid api key' in str(e), '非 200 时把上游那段话也带出来（不然没法查）')

    print('--- 七、发出去的请求长什么样')
    op = FakeOpener(resp=FakeResp([sse(*PIECES)]))
    p = OpenAICompat('sk-假钥匙', base_url='https://example.invalid/v1/chat',
                     model='某模型', opener=op, timeout=7)
    p.complete('系统提示', '用户那句话')
    r, timeout = op.calls[0]
    t(timeout == 7, '超时按构造参数传下去')
    t(r.full_url == 'https://example.invalid/v1/chat', '地址是构造时给的')
    t(r.get_header('Authorization') == 'Bearer sk-假钥匙', 'Authorization 带上钥匙')
    payload = json.loads(r.data.decode('utf-8'))
    t(payload['model'] == '某模型' and payload['stream'] is True, 'payload：模型名 + stream')
    t([m['role'] for m in payload['messages']] == ['system', 'user'], '两条消息，system 在前')
    t(payload['messages'][0]['content'] == '系统提示'
      and payload['messages'][1]['content'] == '用户那句话', '内容原样带过去')

    print('--- 八、默认 opener 不走系统代理')
    # 对照组：先自己设一个代理，默认 opener 必须捡起它 —— 捡不起来，下面那条断言就是
    # 空的（「我们的 opener 没有代理」在一台本来就没有代理的机器上也成立，什么都没证明）。
    saved_px = {k: os.environ.get(k) for k in ('http_proxy', 'https_proxy')}
    try:
        os.environ['http_proxy'] = 'http://127.0.0.1:9/'
        os.environ['https_proxy'] = 'http://127.0.0.1:9/'

        def proxies(op):
            d = {}
            for h in op.handlers:
                if isinstance(h, urllib.request.ProxyHandler):
                    d.update(h.proxies)
            return d

        t(bool(proxies(urllib.request.build_opener())),
          f'对照组：默认 build_opener() 会捡起环境里的代理（{proxies(urllib.request.build_opener())}）')
        t(proxies(OpenAICompat('k').opener()) == {},
          '我们的 opener 一个代理都不认 —— 等价于老实现 httpx 的 trust_env=False'
          '（这台机器注册表里就配着系统代理，捡了它，报出来会和「key 不对」长得一样）')
    finally:
        for k, v in saved_px.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    print('--- 九、from_env：绝不带默认钥匙')
    saved = {k: os.environ.pop(k, None) for k in ('DEEPSEEK_API_KEY', 'DEEPSEEK_BASE_URL',
                                                  'DEEPSEEK_MODEL')}
    try:
        p = from_env()
        t(p.api_key == '', '环境变量没设时 api_key 是空串（老仓库那里是一把真钥匙）')
        t(not p.available(), 'available() 是假 —— 不发起任何请求')
        t(p.base_url and p.model, '地址和模型名有兜底（这两个不是密钥）')
        os.environ['DEEPSEEK_API_KEY'] = 'sk-测试'
        t(from_env().available(), '设了 key 就 available')
    finally:
        for k, v in saved.items():
            if v is not None:
                os.environ[k] = v
            else:
                os.environ.pop(k, None)

    print('--- 十、参数与落盘')
    r = req('某市低空经济产业')
    t(r.user == '请为「某市低空经济产业」生成一份行业分析报告。', f'用户那句话：{r.user}')
    t(r.gw is True and r.fmt == 'gw', '默认公文体例：gw=True')
    ex = G.build('主题', '模仿这篇文章写一篇', docs_text='[用户上传了文件「a.md」，内容如下]\n一、引言\n正文\n')
    t(ex.fmt == 'exemplar' and ex.gw is False, '范本体例：fmt=exemplar、gw=False')
    try:
        G.build('')
        t(False, '空主题必须抛 ValueError —— 没抛')
    except ValueError as e:
        t('主题' in str(e), f'空主题抛 ValueError：{e}')
    src = inspect.getsource(G)
    t(not any(pat in src for pat in (", 'w'", ', "w"', 'writelines', "'wb'")),
      'generate.py 里没有写文件的调用 —— 落盘只在 cli，上游出错自然就落不下盘')
    # 按 import 判，不按「出现过 urllib 这个词」判：文档字符串里正说着老实现用过 httpx
    net = re.findall(r'^\s*(?:import|from)\s+(httpx|urllib|requests|socket|http)\b',
                     src, re.M)
    t(not net, f'generate.py 里也没有网络调用（import 里没有 {net or "网络库"}）')
    return t.ok, t.notes


if __name__ == '__main__':
    sys.exit(main_hook(main, 'test_generate：provider 契约（不联网）'))
