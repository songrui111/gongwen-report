"""调模型的那一处接缝 —— 整个包**只有这个文件发网络请求**。

**为什么单独一层。** 生成这条路要验的东西有两类：一类是提示词装得对不对（纯函数，
不需要模型），一类是「流式取回来的字，一个字不丢地拼起来」这个契约。后者如果只能
靠真调模型来验，就变成「要花钱、要联网、还不稳定」的测试 —— 于是没人跑，契约坏了也
没人知道。把「调模型」收成一个两个方法的接口之后，测试里塞一个假的就能把契约钉死，
`generate` 那条路一行都不用改。

**用标准库的 urllib，不用 httpx。** 老实现用的是 httpx，并且写死了
`trust_env=False` —— 因为这台机器上系统代理会把请求带偏，表现是「一直连不上」。
urllib 这边等价的做法是 `ProxyHandler({})`（空字典 = 不走任何代理），下面那个
opener 就是干这个的。少一个第三方依赖，`pip install -r requirements.txt` 就只剩
pypdf（而且只有打印那一层用它）。
"""
import json
import os
import urllib.error
import urllib.request

DEFAULT_BASE_URL = 'https://api.deepseek.com/chat/completions'
DEFAULT_MODEL = 'deepseek-flash'
KEY_ENV = 'DEEPSEEK_API_KEY'
BASE_ENV = 'DEEPSEEK_BASE_URL'
MODEL_ENV = 'DEEPSEEK_MODEL'

# 一次生成要几分钟，所以超时给得很宽。注意 urllib 的 timeout 是**每次 socket 操作**
# 的上限（不是整个请求的墙钟），语义上正好：连接卡住、或者中途不再吐字，都会在这个
# 时间后报错，而不是无限等下去。
DEFAULT_TIMEOUT = 1800.0


class UpstreamError(RuntimeError):
    """上游不给字了（非 200、连不上、超时）。**抛出来之前不许落盘** —— 半截报告
    比没有报告更误导人。"""


class Completer:
    """接缝。假实现只要这两个方法：available() 和 complete()。"""

    name = 'completer'

    def available(self):
        raise NotImplementedError

    def complete(self, system, user, on_delta=None):
        """→ 整段文本。`on_delta(piece, total)` 每个增量调一次，用来报进度。

        契约（test_generate.py 逐条钉着）：把每次 piece 拼起来必须**等于**返回值；
        每个 total 都是「到目前为止拼出来的全部」。
        """
        raise NotImplementedError


class OpenAICompat(Completer):
    """OpenAI 兼容的 /chat/completions，流式。DeepSeek 走的就是这个形状。"""

    name = 'deepseek'

    def __init__(self, api_key, base_url=DEFAULT_BASE_URL, model=DEFAULT_MODEL,
                 timeout=DEFAULT_TIMEOUT, opener=None):
        self.api_key = (api_key or '').strip()
        self.base_url = base_url or DEFAULT_BASE_URL
        self.model = model or DEFAULT_MODEL
        self.timeout = timeout
        # 测试塞假的 opener 进来，就能把网络整段抽掉（不碰 socket、不联网）。
        self._opener = opener

    def available(self):
        """**只看配没配 key，不发任何请求。** 没配就明确说不，而不是发出去等 401。"""
        return bool(self.api_key)

    def opener(self):
        if self._opener is not None:
            return self._opener
        # 空字典 = 不用任何代理。等价于老实现里 httpx 的 trust_env=False：这台机器上
        # 系统代理会让请求直接连不上，而报出来的错和「key 不对」长得一模一样。
        return urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def payload(self, system, user):
        return {
            'model': self.model,
            'stream': True,
            'temperature': 0.7,
            'messages': [{'role': 'system', 'content': system},
                         {'role': 'user', 'content': user}],
        }

    def request(self, system, user):
        return urllib.request.Request(
            self.base_url,
            data=json.dumps(self.payload(system, user)).encode('utf-8'),
            headers={'Content-Type': 'application/json',
                     'Accept': 'text/event-stream',
                     'Authorization': f'Bearer {self.api_key}'},
            method='POST')

    def complete(self, system, user, on_delta=None):
        if not self.available():
            raise UpstreamError(
                f'没有配置 {KEY_ENV}。要么设好环境变量走直连生成，'
                f'要么用 --print-system 把规范交给宿主模型写、写完回来检查。')
        try:
            resp = self.opener().open(self.request(system, user), timeout=self.timeout)
        except urllib.error.HTTPError as e:
            body = e.read().decode('utf-8', 'ignore')
            raise UpstreamError(f'{self.name} 返回 {e.code}：{body[:300]}') from None
        except OSError as e:
            raise UpstreamError(f'连不上 {self.name}（{self.base_url}）：{e}') from None
        return self.read_stream(resp, on_delta)

    @staticmethod
    def read_stream(resp, on_delta=None):
        """SSE 逐行读。**只认 `data:` 行**，`[DONE]` 就停。

        解析失败的行直接跳过：上游偶尔会插注释行或空行，为它们中断整份报告不值得；
        真正致命的错（非 200）已经在上面抛掉了。
        """
        parts = []
        with resp:
            for raw in resp:
                line = raw.decode('utf-8', 'ignore').strip()
                if not line.startswith('data:'):
                    continue
                data = line[5:].strip()
                if data == '[DONE]':
                    break
                try:
                    piece = json.loads(data)['choices'][0]['delta'].get('content') or ''
                except Exception:
                    continue
                if not piece:
                    continue
                parts.append(piece)
                if on_delta is not None:
                    on_delta(piece, ''.join(parts))
        return ''.join(parts)


def from_env():
    """按环境变量造一个 provider。**不给任何默认 key** —— 老仓库那份代码里
    `os.getenv("DEEPSEEK_API_KEY", "sk-…")` 的第二个参数是一把真钥匙，跟着历史一起
    进了 20 个提交。这里第二个参数一律是空串：没配就是没配。"""
    return OpenAICompat(
        os.getenv(KEY_ENV, ''),
        os.getenv(BASE_ENV, DEFAULT_BASE_URL),
        os.getenv(MODEL_ENV, DEFAULT_MODEL))
