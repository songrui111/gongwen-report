"""调模型的接缝：整个包只有这个文件发网络请求。

用标准库 urllib，不用 httpx。opener 不走系统代理。
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
DEFAULT_TIMEOUT = 1800.0      # 生成一次要几分钟，超时给得很宽


class UpstreamError(RuntimeError):
    """上游不给字了（非 200、连不上、超时）。抛出来之前不许落盘。"""


class Completer:
    """接缝：两个方法 available() 和 complete()。测试用假实现替换。"""

    name = 'completer'

    def available(self):
        raise NotImplementedError

    def complete(self, system, user, on_delta=None):
        """→ 整段文本。on_delta(piece, total) 每个增量调一次，用来报进度。

        契约：把每次 piece 拼起来必须等于返回值；每个 total 都是目前拼出来的全部。
        """
        raise NotImplementedError


class OpenAICompat(Completer):
    """OpenAI 兼容的 /chat/completions，流式。"""

    name = 'deepseek'

    def __init__(self, api_key, base_url=DEFAULT_BASE_URL, model=DEFAULT_MODEL,
                 timeout=DEFAULT_TIMEOUT, opener=None):
        self.api_key = (api_key or '').strip()
        self.base_url = base_url or DEFAULT_BASE_URL
        self.model = model or DEFAULT_MODEL
        self.timeout = timeout
        self._opener = opener  # 测试塞假的进来，把网络整段抽掉

    def available(self):
        """只看配没配 key，不发任何请求。"""
        return bool(self.api_key)

    def opener(self):
        if self._opener is not None:
            return self._opener
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
        """SSE 逐行读。只认 data: 行，[DONE] 就停。解析失败的行跳过。"""
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
    """按环境变量造 provider。不给任何默认 key —— 没配就是没配。"""
    return OpenAICompat(
        os.getenv(KEY_ENV, ''),
        os.getenv(BASE_ENV, DEFAULT_BASE_URL),
        os.getenv(MODEL_ENV, DEFAULT_MODEL))