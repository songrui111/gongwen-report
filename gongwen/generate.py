"""装好提示词 → 交给 provider → 拿回整份报告。不碰网络、不碰磁盘。

落盘的是 cli，所以上游报错和写文件之间隔着一个 return —— 不会留下半截报告。
这一路不再自主联网，参考资料由 --refs 传文件。
"""
import os

from . import docformat
from . import outline
from . import prompt
from .provider import UpstreamError

USER_FMT = '请为「{topic}」生成一份行业分析报告。'


def user_message(topic):
    return USER_FMT.replace('{topic}', topic)


class Request:
    """一次生成要送出去的东西。拆出来是为了让 --print-system 能只装不发。"""

    __slots__ = ('system', 'user', 'fmt')

    def __init__(self, system, user, fmt):
        self.system = system
        self.user = user
        self.fmt = fmt

    @property
    def gw(self):
        return self.fmt != 'exemplar'


def read_docs(path):
    """读一份要模仿的文档，拼成前端那个带标记的形状。"""
    if not path:
        return ''
    with open(path, encoding='utf-8') as f:
        body = f.read()
    return docformat.wrap_upload(os.path.basename(path), body)


def build(topic, description='', refs_text='', recipient='', docs_text='', today='',
          structure_override=None):
    """→ Request。纯函数，不发请求。"""
    issue = prompt.validate(topic, description, recipient)
    if issue:
        raise ValueError(issue)
    system = prompt.report_system(topic, description, refs_text, recipient, docs_text,
                                  today=today, structure_override=structure_override)
    _, fmt = prompt.report_structure(topic, description, docs_text)
    return Request(system, user_message(topic), fmt)


def generate(topic, provider, description='', refs_text='', recipient='', docs_text='',
             today='', progress_every=2000, echo=None, structure_override=None):
    """装好、发给 provider、把字攒起来。

    echo 是报进度用的回调。一次生成好几分钟，中途一个字都不打会被当成卡死。
    """
    return run(build(topic, description, refs_text, recipient, docs_text, today,
                     structure_override=structure_override),
               provider, progress_every=progress_every, echo=echo)


def run(req, provider, progress_every=2000, echo=None):
    """→ 整份报告文本。上游不给字就抛 UpstreamError，不落盘。"""
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


# ---- 分阶段：目录 / 按节改 / 全文改 ----

def generate_outline(topic, provider, description='', refs_text='', recipient='',
                     docs_text='', today='', echo=None):
    """出目录。→ (outline, warnings, 原始回复, fmt)。"""
    system, user, fmt = outline.outline_messages(
        topic, description, refs_text, docs_text, recipient, today)
    text = run(Request(system, user, fmt), provider, echo=echo)
    raw = outline.parse_json(text)
    ol, warns = outline.normalize_outline(raw, fmt, topic)
    return ol, warns, text, fmt


def revise_section(topic, provider, outline_data, section, current, instruction,
                   refs_text='', docs_text='', echo=None):
    """只改一节。→ (新全文, ok, 警告, 原始回复)。"""
    system, user = outline.section_messages(
        topic, outline_data, section, current, instruction, refs_text, docs_text)
    text = run(Request(system, user, 'gw'), provider, echo=echo)
    md, ok, warn = outline.replace_section(current, section, text)
    return md, ok, warn, text


def revise_all(topic, provider, outline_data, current, instruction,
               refs_text='', docs_text='', echo=None):
    """改全文。→ 新全文。"""
    system, user = outline.revise_all_messages(
        topic, outline_data, current, instruction, refs_text, docs_text)
    return run(Request(system, user, 'gw'), provider, echo=echo)