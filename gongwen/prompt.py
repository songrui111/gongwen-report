"""提示词层：三份模板、填槽、体例识别、参数闸门。全是纯函数。

槽位用 `{{x}}` + `str.replace`，不用 `str.format`。replace 永不抛异常，槽位从模板自动枚举。
"""
import os
import re
import time

from . import docformat

HERE = os.path.dirname(os.path.abspath(__file__))
TPL_DIR = os.path.join(HERE, 'templates')

TEMPLATE = 'report_template'
STRUCTURE_GW = 'structure_gw'
STRUCTURE_EXEMPLAR = 'structure_exemplar'
TEMPLATES = (TEMPLATE, STRUCTURE_GW, STRUCTURE_EXEMPLAR)

TOPIC_MAX = 200
DESC_MAX = 500
RECIPIENT_MAX = 100
DOCS_MAX = 40000

_SLOT = re.compile(r'\{\{(\w+)\}\}')
_DATE_RE = re.compile(r'^(\d{4})-(\d{1,2})-(\d{1,2})$')


def today_text(today=''):
    """today → 中文写法。留空取本机当天。月、日不补虚位。"""
    if not today:
        t = time.localtime()
        return f'{t.tm_year}年{t.tm_mon}月{t.tm_mday}日'
    m = _DATE_RE.match((today or '').strip())
    if not m:
        return (today or '').strip()
    return f'{int(m.group(1))}年{int(m.group(2))}月{int(m.group(3))}日'


class TemplateError(ValueError):
    """模板槽没填全 —— 代码错，不是用户输入错。"""


def load(name):
    """按名字读模板。不缓存：测试会在同一进程里改模板再跑。"""
    if name not in TEMPLATES:
        raise KeyError(f'没有这份模板：{name}（只有 {TEMPLATES}）')
    with open(os.path.join(TPL_DIR, name + '.md'), encoding='utf-8') as f:
        return f.read()


def slots(text):
    """模板里有哪些槽 —— 从模板正文枚举。"""
    return set(_SLOT.findall(text))


def render(text, values):
    """把 {{x}} 换成值。缺的槽原样留着，由 unfilled 报出来。"""
    out = text
    for k, v in values.items():
        out = out.replace('{{' + k + '}}', v)
    return out


def unfilled(text):
    """还没被换掉的槽名。"""
    return sorted(slots(text))


def render_checked(name, values):
    """填一份模板，槽必须填全 —— 少一个立刻报出名。"""
    tpl = load(name)
    left = slots(tpl) - set(values)
    if left:
        raise TemplateError(f'{name} 里这几个槽没给值：{sorted(left)}')
    return render(tpl, values)


# ---- 上传文档 ----

def trim_docs(text):
    """超长文档留头留尾，中间省略。头和尾都是体例，只留头会砍掉参考文献。"""
    if len(text) <= DOCS_MAX:
        return text
    head = DOCS_MAX * 2 // 3
    cut = len(text) - DOCS_MAX
    return (text[:head]
            + f'\n\n（中间省略约 {cut} 字，以下直接接文档结尾）\n\n'
            + text[-(DOCS_MAX - head):])


def validate(topic, description='', recipient=''):
    """返回错误说明；没问题返回空串。"""
    if not (topic or '').strip():
        return '请填写报告主题（行业/领域）'
    if len(topic) > TOPIC_MAX:
        return f'主题不能超过{TOPIC_MAX}字'
    if len(description or '') > DESC_MAX:
        return f'补充说明不能超过{DESC_MAX}字'
    if len(recipient or '') > RECIPIENT_MAX:
        return f'主送机关不能超过{RECIPIENT_MAX}字'
    return ''


DOCS_HEAD = '## 用户上传的参考文档'


def refs_block(refs_text, docs_text=''):
    """→ 拼进 system 的参考资料段。两份都没有就是空串。
    上传文档和 --refs 的资料一样是素材，挂在 ## 参考资料 底下。
    """
    parts = []
    if refs_text:
        parts.append(refs_text)
    if docs_text:
        parts.append(DOCS_HEAD + '\n' + trim_docs(docs_text))
    return '\n\n'.join(parts)


# ---- 装 system ----

def report_structure(topic, description='', docs_text=''):
    """→ (装进 structure 槽的骨架, 标签 'gw'/'exemplar')。

    命中「按上传文档的格式来」且抽出了骨架，就装范本骨架；否则装公文骨架。
    抽不出骨架时退回公文 —— 交出没有骨架的报告比默认行为更糟。
    """
    if docformat.wants_doc_format(description, docs_text):
        outline = docformat.describe_format(docs_text)
        if outline:
            names = docformat.filenames(docs_text)
            return render_checked(STRUCTURE_EXEMPLAR, {
                'names': '、'.join(f'《{n}》' for n in names) if names else '用户上传的文档',
                'outline': outline}), 'exemplar'
    return render_checked(STRUCTURE_GW, {'topic': topic}), 'gw'


def report_system(topic, description='', refs_text='', recipient='', docs_text='',
                  today='', structure_override=None):
    """主题 + 说明 + 主送机关 + 今天 → 最终的 system 串。

    today 留空取本机当天；显式给了就用给的。
    主送机关走参数不走模型 —— 模型最容易把它简写，而公文里这一行最不能改。
    没传就不写，不能让模型自己编机关名。

    `structure_override` 给定时用它替掉 `{{structure}}` 槽（分阶段流程里是用户
    确认过的目录）；不给时行为和原来完全一致。
    """
    today = today_text(today)
    desc_block = f'\n补充说明：{description}' if description else ''
    if recipient:
        recipient_block = (
            f'本次的主送机关是「{recipient}」。**逐字照抄，不得简写、不得改写、'
            f'不得加书名号**（例如「某某市科学技术局」不能写成「市科技局」或'
            f'「某某市科技局」），末尾加全角冒号。')
    else:
        recipient_block = (
            '本次**没有给出主送机关**，这一行**整行不写**，'
            '不要自己编一个机关名。')
    if structure_override is None:
        structure, _ = report_structure(topic, description, docs_text)
    else:
        structure = structure_override
    system = render_checked(TEMPLATE, {
        'topic': topic, 'description': desc_block,
        'recipient': recipient_block, 'structure': structure, 'today': today,
    })
    block = refs_block(refs_text, docs_text)
    if block:
        system = system + '\n\n## 参考资料\n' + block
    return system