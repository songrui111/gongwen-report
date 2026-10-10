"""提示词层：三份模板、填槽、上传文档的体例、参数闸门。**全是纯函数。**

**槽位用 `{{x}}` 加 `str.replace`，不用 `str.format`。** 老版本用 format，代价是模板
正文里出现任何一个字面花括号（比如模型要写的公式、或者一句引用）就会让**每一个**请求
500；为此写了一段「扫残留括号」的兜底断言，而那段断言本身还有漏洞（占位符清单是手写
的，漏了一个 `{description}`，且只在范本那条分支上逃得掉 —— 范本分支的兜底被跳过）。
`replace` 永不抛异常，而且槽位可以**从模板自动枚举**（slots），手写清单就此消失：
「模板里有个槽忘了填」这件事现在结构上不可能发生。

代价是模板里要写双花括号。这三份模板正文里没有任何字面花括号，所以这次转换是纯粹的
机械替换（`{x}` → `{{x}}`），`--print-template` 打出来的就是最终送给模型的那一份。
"""
import os
import re
import time

from . import docformat

HERE = os.path.dirname(os.path.abspath(__file__))
TPL_DIR = os.path.join(HERE, 'templates')

# 三份模板。template 是整份 system 的壳，另外两份装在它的 structure 槽里（一个槽、
# 两个值 —— 任何一次请求里只有一套骨架，见 report_structure 的说明）。
TEMPLATE = 'report_template'
STRUCTURE_GW = 'structure_gw'
STRUCTURE_EXEMPLAR = 'structure_exemplar'
TEMPLATES = (TEMPLATE, STRUCTURE_GW, STRUCTURE_EXEMPLAR)

# 参数闸门。原来是散在 Web 层（FastAPI 端点）里的四个 if，搬进来之后命令行和 Skill
# 走的是同一份判据 —— 两处各写一份，迟早对不上。
TOPIC_MAX = 200
DESC_MAX = 500
RECIPIENT_MAX = 100
# 上传文档的总长上限。**这原来是没上限的**：前端允许传 5 份、每份截到 50000 字符，
# 25 万字符会原样拼进 system，加上参考资料和提示词本身，一定超出上游的上下文窗口。
DOCS_MAX = 40000

_SLOT = re.compile(r'\{\{(\w+)\}\}')
_DATE_RE = re.compile(r'^(\d{4})-(\d{1,2})-(\d{1,2})$')


def today_text(today=''):
    """`today` → 提示词里用的中文写法。留空取本机当天。

    传 `2026-10-10`（命令行上最顺手的写法）就转成「2026年10月10日」；已经是中文写法、
    或者是别的什么，原样用 —— 这一层不做校验，`--today` 是给快照定死用的。

    月、日**不补虚位**：1 月 3 日写「1月3日」，不写「01月03日」。和成文日期的写法
    （标准 7.3.5.4）同一套，省得模型照着提示词抄出一个「010月」。
    """
    if not today:
        t = time.localtime()
        return f'{t.tm_year}年{t.tm_mon}月{t.tm_mday}日'
    m = _DATE_RE.match((today or '').strip())
    if not m:
        return (today or '').strip()
    return f'{int(m.group(1))}年{int(m.group(2))}月{int(m.group(3))}日'


class TemplateError(ValueError):
    """模板里的槽没填全 —— 这是代码错，不是用户输入错，所以直接抛。"""


def load(name):
    """按名字读一份模板。**不缓存**：证伪测试会在同一个进程里改模板再跑，
    缓存了就看到改前的旧文本，那种失败最难查。"""
    if name not in TEMPLATES:
        raise KeyError(f'没有这份模板：{name}（只有 {TEMPLATES}）')
    with open(os.path.join(TPL_DIR, name + '.md'), encoding='utf-8') as f:
        return f.read()


def slots(text):
    """模板里有哪些槽 —— **从模板正文枚举**，不另写一份清单。"""
    return set(_SLOT.findall(text))


def render(text, values):
    """把 {{x}} 换成值。缺的槽原样留着（不抛异常），由 unfilled 报出来。

    不做「值里的内容会不会破坏模板」的防护，因为 replace 根本没有转义这回事 ——
    上传文件名里带 `{2025}`、正文里带花括号，都只是普通字符。
    """
    out = text
    for k, v in values.items():
        out = out.replace('{{' + k + '}}', v)
    return out


def unfilled(text):
    """还没被换掉的槽名。填完槽之后还非空，就是漏填了。"""
    return sorted(slots(text))


def render_checked(name, values):
    """填一份模板，槽必须填全 —— 少一个立刻报出是哪份模板的哪个槽。"""
    tpl = load(name)
    left = slots(tpl) - set(values)
    if left:
        raise TemplateError(f'{name} 里这几个槽没给值：{sorted(left)}')
    return render(tpl, values)


# ---------------- 上传文档 ----------------


def trim_docs(text):
    """上传文档超长时留头留尾，中间那段省略并写明省了多少。

    砍的时候**头和尾都留**：头是体例（标题、章节怎么起），尾也是体例（参考文献、附录
    怎么收尾）；只留头部会正好把「有没有参考文献」这个判断砍掉。
    """
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


# 上传文档拼进 system 时的标题。沿用老实现那一句原话。
DOCS_HEAD = '## 用户上传的参考文档'


def refs_block(refs_text, docs_text=''):
    """→ 拼进 system 的那一段参考资料；两份都没有就是空串。

    **上传文档和 `--refs` 给的资料一样，是给模型看的素材**，一起挂在 `## 参考资料`
    底下（上传文档在后，和 `_report_refs` 里的顺序一致）。

    这一句是搬过来时漏掉的：老实现是
    `refs.append("## 用户上传的参考文档\\n" + _trim_docs(docs_text))`，少了它，
    `--docs` 就只影响骨架 —— 范本骨架装得好好的，模型眼前却根本没有那份文档，
    正文当然不是照着它写的，而且没有任何东西会报错（`trim_docs` 当时也一起成了
    没人调用的死函数，是同一件事留下的线索）。"""
    parts = []
    if refs_text:
        parts.append(refs_text)
    if docs_text:
        parts.append(DOCS_HEAD + '\n' + trim_docs(docs_text))
    return '\n\n'.join(parts)


# ---------------- 装 system ----------------


def report_structure(topic, description='', docs_text=''):
    """→ (装进 structure 槽的骨架, 标签 'gw'/'exemplar')。

    两条路都**只有一套骨架**：命中「按上传文档的格式来」而且真从文档里抽出了骨架，
    就装范本骨架；否则装默认公文骨架。抽不出骨架时退回公文 —— 闸门和抽取是两回事，
    「命中了但抽不出东西」（传的是 xlsx 导出的表格、通篇没有编号标题）不能交出一份
    没有骨架的报告，那是这个功能唯一比默认行为更糟的结果。
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
                  today=''):
    """主题 + 说明 + 主送机关 + 今天 → 最终的 system 串。

    今天是几号，程序知道、模型不知道：不给它，它就只能在正文里编一个时间基准。今天
    只用来定**数据截止时间** —— 报告上那一行成文日期是标准 7.3.5.4 的要素，位置在
    正文之后，由调用方按本机当天排，不要求模型在标题下写年月。

    主送机关（标准 7.3.2）走参数而不是走模型：它是机关的全称或规范化简称，模型最
    容易做的事就是把它简写（「某某市科学技术局」→「市科技局」），而公文里这一行是
    最不能改的。没传就不写 —— **不能让它自己编一个机关名**。

    `docs_text` 是用户上传的文档。它进来有**两个用处**：判「格式以上传文档为准」走哪套
    骨架，以及作为素材拼进参考资料（见 refs_block）。第二个参数不能从 refs 里反推 ——
    refs 是拼好的文本，有没有附件看不出来。

    `today` 留空取本机当天；**显式给了就用给的**（快照测试据此可复现）。
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
    structure, _ = report_structure(topic, description, docs_text)
    system = render_checked(TEMPLATE, {
        'topic': topic, 'description': desc_block,
        'recipient': recipient_block, 'structure': structure, 'today': today,
    })
    block = refs_block(refs_text, docs_text)
    if block:
        system = system + '\n\n## 参考资料\n' + block
    return system
