"""从上传文档里认出格式——供「按上传文档的格式来」那一路用。

闸门 fail-closed：漏判只是退回公文格式，误判会把别人骨架套到报告上。
describe_format 抽出来的只是提示，不是事实，措辞里写着「以文档原文为准」。
"""
import re

# 标记串的唯一定义处。下面所有启发式都是逐行看的，标记行自带逗号会被当正文甩掉。
DOC_MARK_FMT = '[用户上传了文件「{name}」{size}，内容如下]\n'
DOC_MARK_RE = re.compile(r'\[用户上传了文件「(?P<name>[^」]*)」[^\]]*\]\s*\n')
DOC_SEP = '\n\n---\n\n'

# 上游把单份文档截到 50000 字符，只留头部。长文档上结尾的体例答不了，只能如实说没识别到。
TRUNC_MARK = '文档内容过长'


def wrap_upload(name, body, size_kb=None):
    """一份上传文档 → 带标记的上下文串。**标记串只在这里生成。**"""
    size = f'（{size_kb:.1f} KB）' if size_kb is not None else ''
    return DOC_MARK_FMT.format(name=name, size=size) + body + DOC_SEP


def join_uploads(items):
    """[(名字, 正文[, KB]), …] → 一个上下文串。和前端当年的拼法逐字节一致。"""
    parts = []
    for it in items:
        name, body = it[0], it[1]
        parts.append(wrap_upload(name, body, it[2] if len(it) > 2 else None))
    return ''.join(parts)


def parse_uploads(text):
    """上下文串 → [(名字, 正文), …]。给「这几份文档分别是哪几份」用（测试、日志）。"""
    out = []
    marks = list(DOC_MARK_RE.finditer(text or ''))
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        body = text[m.end():end]
        if body.endswith(DOC_SEP):
            body = body[:-len(DOC_SEP)]
        out.append((m.group('name'), body.strip('\n')))
    return out


# 闸门：补充说明里有没有「按这份文档的格式来」的意思
#
# 格式名词可以孤立成立：出现一个 + 附近提到文档 = 格式要求
_FORMAT_NOUN = (r'(?:格式|体例|排版|样式|风格|范文|框架|结构|写法|行文|标题层级|'
                r'层次|章节安排|谋篇)')
# 模仿动词要挨着文档指代才算。故意不收「参考」—— 那最容易接内容宾语
_IMITATE_VERB = r'(?:模仿|仿照|仿写|照着|按着|参照|按照|依着|比着)'
_DOC_REF = (r'(?:我?上传的?(?:文档|文件|材料|资料|附件)|附件|上传的?(?:文档|文件|材料|资料)|'
            r'这(?:篇|份|个)(?:文章|文档|文件|材料|资料|报告|范文)?|'
            r'那(?:篇|份|个)(?:文章|文档|文件|材料|资料|报告|范文)?|'
            r'本(?:篇|文|报告)|原文|范文|上面那|上述文档|我给的|我发的|提供的文档)')

# 每条意图只在本小句里找配对词，跨句不算
_WINDOW = 12

# 否定的写法。闸门误开的后果比漏开大，把文档降格的说法一律当否定看
_NEG = re.compile(r'(不|别|勿|无需|不用|不要|不是|仍|照旧|还是|依然|依旧|沿用|照原|'
                  r'只(?:是|作|当|供|算)|仅(?:是|作|当|供|算)|仅供|当做素材|当作素材)')
_NEG_BACK = 8         # 否定词往两边各看多少字


def _clauses(text):
    """按句读切开。每条意图只在同一个小句里认，避免跨句凑出假命中。"""
    return [c for c in re.split(r'[。；！？；\n]', text) if c.strip()]


def _hit(a, b, clause, window=_WINDOW):
    """a、b 两个正则在这个小句里有没有**挨着**出现（谁在前都行）。"""
    for m in re.finditer(a, clause):
        lo, hi = max(0, m.start() - window), min(len(clause), m.end() + window)
        seg = clause[lo:hi]
        mb = re.search(b, seg)
        if not mb:
            continue
        # 前后各让 8 个字说话（否定词可能挂在任一头）
        s = min(lo + mb.start(), m.start())
        e = max(lo + mb.end(), m.end())
        if _NEG.search(clause[max(0, s - _NEG_BACK):e + _NEG_BACK]):
            continue
        return True
    return False


def wants_doc_format(description, docs_text=''):
    """补充说明是不是在要求「报告格式以上传文档为准」。

    没有上传文档一律不算 —— 认了就会交出「没有骨架」的报告。
    """
    if not (description or '').strip():
        return False
    if not (docs_text or '').strip():
        return False
    for clause in _clauses(description):
        # 「格式名词」就近配一个文档指代，两边谁先谁后都算
        if _hit(_FORMAT_NOUN, _DOC_REF, clause) or _hit(_DOC_REF, _FORMAT_NOUN, clause):
            return True
        # 「模仿动词」紧挨文档指代（「模仿这篇文章写一篇」）
        if re.search(_IMITATE_VERB + r'[^，、]{0,4}?' + _DOC_REF, clause):
            m = re.search(_IMITATE_VERB, clause)
            if m and not _NEG.search(clause[max(0, m.start() - _NEG_BACK):m.start()]):
                return True
    return False


# 抽取：这份文档的骨架和体例长什么样
#
# 「1 引言」这种学刊写法：编号和标题间只有一个空格。只有 1~2 位数字才可能是章节号，
# 四位年份、三位金额跟着的量词/单位不是标题开头
_BARE_NUM = (r'\d{1,2}\s+'
             r'(?![\d家个元亿万百千份%年月日张条项位名台辆人倍次])')

# 有编号的标题行。PDF/Word 转出来是裸文本，编号是唯一还留着的层级信息
_ORDINAL = re.compile(
    r'^\s*(?:'
    r'第\s*[一二三四五六七八九十百千0-9]+\s*[章节篇部分讲]'   # 第一章 / 第 1 部分
    r'|[一二三四五六七八九十]+\s*[、．.]'                     # 一、
    r'|（\s*[一二三四五六七八九十0-9]+\s*）'                  # （一）（1）
    r'|\(\s*[一二三四五六七八九十0-9]+\s*\)'
    r'|\d+\s*[、．.]\s*\D'                                     # 1. 引言
    r'|\d+(?:\.\d+)+'                                          # 1.1 概述
    r'|' + _BARE_NUM +                                        # 1 引言（学刊体例）
    r'|\d+\s*[)）]\s*\D'                                       # 1) 引言
    r')')
# 独立成行的固定节名（学刊体例的开篇结尾），没有编号也要认
_KEYWORD_SEC = re.compile(
    r'^\s*(?:摘\s*要|内容提要|提\s*要|关键词|关键字|前\s*言|引\s*言|导\s*言|绪\s*论|'
    r'概\s*述|背\s*景|结\s*语|结\s*论|结束语|参考文献|参考书目|注\s*释|附\s*录|致\s*谢|'
    r'目\s*录|研究结论|政策建议)\s*[:：]?\s*$')
# 表格：Markdown 管道行、表题行
_PIPE = re.compile(r'^\s*\|')
_TABLE_CAP = re.compile(r'^\s*(?:表|Table)\s*\d')
# 项目符号行
_BULLET = re.compile(r'^\s*(?:[-*•·▪◦]|（\s*\d+\s*）|\(\s*\d+\s*\))\s')
# 编号风格的真身，用来告诉模型「范本一级用的是什么」
_STYLES = (
    ('一、', re.compile(r'^\s*[一二三四五六七八九十]+\s*[、．.]')),
    ('（一）', re.compile(r'^\s*（\s*[一二三四五六七八九十]+\s*）')),
    ('第一章', re.compile(r'^\s*第\s*[一二三四五六七八九十百千0-9]+\s*[章节篇]')),
    ('1.', re.compile(r'^\s*(?:\d+\s*[、．.]\s*\D|\d+\s*[)）]\s*\D|' + _BARE_NUM + r')')),
    ('（1）', re.compile(r'^\s*（\s*\d+\s*）')),
    ('1.1', re.compile(r'^\s*\d+(?:\.\d+)+')),
)

_HEAD_MAX = 30          # 标题行的字数上限
_OUTLINE_MAX = 30       # 骨架最多列几行


def _heading_kind(line):
    """这一行像不像**编号**标题？返回 'numbered' / 'named' / ''（不像）。

    只认有编号的标题和固定节名，不认短的独立行 —— 没有编号的短行是误判重灾区，
    而骨架判错的代价比骨架短更大。
    """
    s = line.strip()
    if not s or len(s) > _HEAD_MAX:
        return ''
    if _ORDINAL.match(s):
        # 去掉编号再挑标点：「一、研究背景与意义」里的「、」是编号自己的分隔符
        rest = _ORDINAL.sub('', s, count=1).strip()
        if not rest or any(c in rest for c in '。！？；，、'):
            return ''
        return 'numbered'
    if _KEYWORD_SEC.match(s):
        return 'named'
    return ''


def _table_facts(lines):
    """表格张数和表题位置。表题在表格上方还是下方，靠两者的行号比出来。"""
    pipe_idx = [i for i, ln in enumerate(lines) if _PIPE.match(ln)]
    cap_idx = [i for i, ln in enumerate(lines) if _TABLE_CAP.match(ln)]
    if not pipe_idx:
        return dict(count=0, cap=len(cap_idx), above=None)
    # 一张表 = 一段连续的管道行（中间允许空行，PDF 抽出来常见）
    blocks, prev = 0, None
    for i in pipe_idx:
        if prev is None or i - prev > 3:
            blocks += 1
        prev = i
    above = None
    if cap_idx:
        up = down = 0
        for c in cap_idx:
            near = min(pipe_idx, key=lambda p: abs(p - c))
            if near > c:
                up += 1
            else:
                down += 1
        above = up >= down
    return dict(count=blocks, cap=len(cap_idx), above=above)


def describe_format(docs_text, max_chars=1800):
    """上传文档 → 一小段「体例说明」。抽不出东西就返回空串，调用方据此退回默认格式。

    返回的是给**模型**看的文字，措辞是「范本长这样」。
    """
    text = docs_text or ''
    if not text.strip():
        return ''
    lines = text.splitlines()
    truncated = TRUNC_MARK in text

    outline, seen = [], set()
    for ln in lines:
        if not _heading_kind(ln):
            continue
        s = ' '.join(ln.split())
        if s in seen:
            continue
        seen.add(s)
        outline.append(s)
        if len(outline) >= _OUTLINE_MAX:
            break
    if not outline:
        # 一行编号标题都认不出来（表格导出、纯流水叙述）—— 没有格式可模仿
        return ''

    # 标题本身：第一行正文，跳掉拼上去的「用户上传了文件」标记和表格行
    title = ''
    for ln in lines:
        s = ' '.join(ln.split())
        if not s or s.startswith('[') or _PIPE.match(s):
            continue
        if len(s) <= 60 and s not in seen:
            title = s
        break

    styles = [name for name, rx in _STYLES if any(rx.match(ln) for ln in lines if ln.strip())]
    tbl = _table_facts(lines)
    bullets = sum(1 for ln in lines if _BULLET.match(ln))
    n = max(1, len(lines))
    # 开篇/结尾按行号比例分，不按固定行数：短文里前后 N 行是同一批行
    head_zone, tail_zone = lines[:max(1, n // 4)], lines[-max(1, n // 4):]
    head_secs = [s for s in (ln.strip() for ln in head_zone) if _KEYWORD_SEC.match(s)]
    tail_secs = [s for s in (ln.strip() for ln in tail_zone) if _KEYWORD_SEC.match(s)]
    tail_secs = [s for s in dict.fromkeys(tail_secs) if s not in head_secs]

    out = ['【从范本里识别到的体例】（下列提纲系自动识别，可能漏项，以文档原文为准）']
    out.append(f'- 篇长：约 {len(text)} 字')
    if title:
        out.append(f'- 标题那一行的写法：{title}')
    if truncated:
        out.append('- **注意：这份文档超过 5 万字符被截断，上面只有前半部分**，'
                   '结尾的体例（参考文献、附录、致谢之类）未能识别，以文档原文为准')
    out.append('- 章节骨架（按出现顺序）：')
    out += ['  ' + s for s in outline]
    if styles:
        out.append('- 层次编号用的是：' + ' / '.join(styles))
    if head_secs:
        out.append('- 开篇有：' + '、'.join(dict.fromkeys(head_secs)))
    if tail_secs:
        out.append('- 结尾有：' + '、'.join(dict.fromkeys(tail_secs)))
    if bullets:
        out.append(f'- 正文里有 {bullets} 行项目符号（不是纯段落式）')
    if tbl['count']:
        where = ('表题写在表格**上方**' if tbl['above'] else
                 '表题写在表格**下方**' if tbl['above'] is False else '没看到表题行')
        out.append(f"- 表格 {tbl['count']} 张，{where}")

    s = '\n'.join(out)
    if len(s) > max_chars:
        s = s[:max_chars].rstrip() + '\n  …（略）'
    return s


def filenames(docs_text):
    """上传过的文件名，按顺序。给提示词点名用（「以上传的《X》为准」）。"""
    return [m.group('name') for m in DOC_MARK_RE.finditer(docs_text or '')]
