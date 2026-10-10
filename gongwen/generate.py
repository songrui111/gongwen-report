"""生成这一路：装好提示词 → 交给 provider → 拿回整份报告。

**这个文件不碰网络、不碰磁盘。** 它只做三件事：把 system 装出来（prompt 那层）、
把用户那句话拼出来、把 provider 吐回来的字攒起来报进度。落盘的是 cli，所以「上游
非 200」时不会留下一份半截报告 —— 上游报错和写文件之间隔着一个 return。

老版本的 generate() 是 `import httpx` + `import main` + `asyncio.run` 三件事揉在
一起，还要靠 main 里的检索函数先取参考资料的。搬过来之后参考资料由 `--refs` 传文件，
**这一路不再自主联网** —— 代价写在 README 里，换来的是这个函数可以被一个假 provider
完整测穿。
"""
import os

from . import docformat
from . import prompt
from .provider import UpstreamError

# 用户那一句话。**也用 replace 不用 format** —— 主题里带花括号是很常见的事（「关于
# {2025} 年度…」），跟模板那边同一个理由：宁可只是没换掉，也不要抛异常。
USER_FMT = '请为「{topic}」生成一份行业分析报告。'


def user_message(topic):
    return USER_FMT.replace('{topic}', topic)


class Request:
    """一次生成要送出去的东西。拆出来是为了让 `--print-system` 能只装不发。"""

    __slots__ = ('system', 'user', 'fmt')

    def __init__(self, system, user, fmt):
        self.system = system
        self.user = user
        self.fmt = fmt

    @property
    def gw(self):
        """这份报告该按公文体例打分吗 —— 骨架是范本的时候不该（见 rules 的说明）。"""
        return self.fmt != 'exemplar'


def read_docs(path):
    """读一份要模仿的文档，拼成前端那个形状。

    标记行的写法**是契约的一部分**：提示词里点名「以上传的《X》为准」用的就是这行里
    的文件名，`docformat.parse_uploads` 也确实能从这份文本里把它解回来。所以这里不
    自己拼字符串，交给 docformat 那唯一一处定义。
    """
    if not path:
        return ''
    with open(path, encoding='utf-8') as f:
        body = f.read()
    return docformat.wrap_upload(os.path.basename(path), body)


def build(topic, description='', refs_text='', recipient='', docs_text='', today=''):
    """→ Request。一个字节都不发出去，纯函数。"""
    issue = prompt.validate(topic, description, recipient)
    if issue:
        raise ValueError(issue)
    system = prompt.report_system(topic, description, refs_text, recipient, docs_text,
                                  today=today)
    _, fmt = prompt.report_structure(topic, description, docs_text)
    return Request(system, user_message(topic), fmt)


def generate(topic, provider, description='', refs_text='', recipient='', docs_text='',
             today='', progress_every=2000, echo=None):
    """装好、发给 provider、把字攒起来。

    `echo` 是报进度用的回调（收到一句话）。一次生成要好几分钟，中途一个字不打出来
    会被当成卡死 —— 这个教训在老的 CLI 里已经付过一次学费（那儿是每 2000 字打一行），
    这里保留同一件事，只是把「怎么打」交给调用方。
    """
    return run(build(topic, description, refs_text, recipient, docs_text, today),
               provider, progress_every=progress_every, echo=echo)


def run(req, provider, progress_every=2000, echo=None):
    """→ 整份报告文本。上游不给字就抛 UpstreamError，**不落盘**。"""
    if not provider.available():
        raise UpstreamError(
            f'{provider.name} 没配 key。零密钥那条路是把规范打出来交给宿主模型写：'
            f'`--print-system --topic …`，写完再回来检查。')
    seen = [0]

    def on_delta(piece, total):
        if echo is None:
            return
        if len(total) - seen[0] >= progress_every:
            seen[0] = len(total)
            echo(f'…已收到 {len(total)} 字')

    text = provider.complete(req.system, req.user, on_delta=on_delta)
    if echo is not None and text:
        echo(f'…已收到 {len(text)} 字')
    return text
