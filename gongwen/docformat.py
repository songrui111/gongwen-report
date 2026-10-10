"""从用户上传的文档里认出「格式」—— 供报告「按我上传文档的格式来」那一路用。

    from gongwen import docformat
    docformat.wants_doc_format('模仿这篇文章写一篇', docs_text)
    docformat.describe_format(docs_text)

报告有两层格式，这里只管**提示词那一层**：章节骨架、层次编号、开篇结尾的体例、篇幅
量级、表格数量与表题写法。打印那层（A4、版心、3 号仿宋、标题按 Markdown 深度上字体）
是 preview/paper.css 按标题**深度**写死的，任意上传文件里读不出「纸」的参数（PDF 抽
出来的纯文本里连字体都没有），所以那一层不跟着文档走。

**为什么要单独一个模块。** 这两件事都只跟「一段文本」有关，和框架、和模型都无关，
所以能离线测。识别错的代价不对称：漏判只是退回默认公文格式（用户看得见、再写一句
就行），误判会把范本之外的骨架套到报告上 —— 所以闸门一律 fail-closed，判不准就不认。

`describe_format` 抽出来的东西**只是提示**，不是事实：启发式认标题行在 PDF 转换出来的
裸文本上必然漏项，所以提示词里那一段的措辞是「下列提纲系自动识别，仅供参考，以文档
原文为准」。把它说成权威的，模型就会照着错的骨架写。
"""
import re

# 前端（或任何调用方）拼在每份文档前面的标记。见 wrap_upload —— 这一对函数是标记串
# 的唯一定义处，别在别处再手写一遍。
# 认不出标记也没关系 —— 下面所有启发式都是逐行看的，标记行自带「，」会被当正文甩掉。
DOC_MARK_FMT = '[用户上传了文件「{name}」{size}，内容如下]\n'
DOC_MARK_RE = re.compile(r'\[用户上传了文件「(?P<name>[^」]*)」[^\]]*\]\s*\n')
DOC_SEP = '\n\n---\n\n'

# 上游把单份文档截到 50000 字符，调用方还会把这句话拼在正文尾巴上。截断是**只留头部**
# 的，所以「有没有参考文献」这类落在结尾的问题，在长文档上根本答不了 —— 那时候只能
# 如实说没识别到。
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


# ---------------- 闸门：补充说明里有没有「按这份文档的格式来」的意思 ----------------

# 「格式名词」。这一组是可以孤立成立的：出现一个，再加上附近提到文档，就是格式要求。
_FORMAT_NOUN = (r'(?:格式|体例|排版|样式|风格|范文|框架|结构|写法|行文|标题层级|'
                r'层次|章节安排|谋篇)')
# 「模仿动词」。这一组要**挨着**文档指代才算（「模仿这篇文章」），因为它容易带别的宾语。
# 故意**不收「参考」**：「参考我上传文档里的数据和结论」是内容要求，不是格式要求，
# 而参考是这几个动词里最常接内容的那个。宁可漏判，也不要误判去换掉骨架。
_IMITATE_VERB = r'(?:模仿|仿照|仿写|照着|按着|参照|按照|依着|比着)'
_DOC_REF = (r'(?:我?上传的?(?:文档|文件|材料|资料|附件)|附件|上传的?(?:文档|文件|材料|资料)|'
            r'这(?:篇|份|个)(?:文章|文档|文件|材料|资料|报告|范文)?|'
            r'那(?:篇|份|个)(?:文章|文档|文件|材料|资料|报告|范文)?|'
            r'本(?:篇|文|报告)|原文|范文|上面那|上述文档|我给的|我发的|提供的文档)')

# 每条意图只在自己这一小句里找配对的词，跨句不算（「按公文格式写。我上传了文档」
# 不该被判成格式要求）。窗口给 12 个字，够「的体例」「里的框架」这种修饰走完。
_WINDOW = 12

# 否定的写法。「不要按我上传文档的格式」要挡掉；「按公文格式写，我上传的文档只是素材」
# 也要挡掉 —— 后半句把附件定性成了素材，那正是**内容**而不是**格式**。闸门一开骨架就换
# 了，误开的后果比漏开大，所以「只是／仅作／仅供」这种把文档降格的说法一律当否定看。
_NEG = re.compile(r'(不|别|勿|无需|不用|不要|不是|仍|照旧|还是|依然|依旧|沿用|照原|'
                  r'只(?:是|作|当|供|算)|仅(?:是|作|当|供|算)|仅供|当做素材|当作素材)')
# 否定词往两边各看多少字。「不要按上传文档的格式」里否定词在**前**，「文档只是素材」里
# 否定词在**后**，所以两头都要看。
_NEG_BACK = 8


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
        # 配成对的这一整段，前后各让 8 个字说话（否定词可能挂在任一头）
        s = min(lo + mb.start(), m.start())
        e = max(lo + mb.end(), m.end())
        if _NEG.search(clause[max(0, s - _NEG_BACK):e + _NEG_BACK]):
            continue
        return True
    return False


def wants_doc_format(description, docs_text=''):
    """补充说明是不是在要求「报告格式以上传文档为准」。

    **没有上传文档一律不算**（返回 False）。这条是闸门最要紧的一半：这个函数决定
    提示词里装哪一套骨架，用户写了「模仿这篇文章写一篇」却忘了带附件、或者附件里一个字
    都没解析出来时，认了就会交出「没有骨架」的报告 —— 而默认公文骨架是无害的。
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


# ---------------- 抽取：这份文档的骨架和体例长什么样 ----------------

# 「1 引言」这种学刊写法：编号和标题之间只有一个空格，不带点。它单独一条规则，是因为
# 它最容易撞上正文 —— 「2025 年」「320 亿元」也都是数字加空格开头。两道闸门挡着：只有
# 1～2 位的数字才可能是章节号（四位数的年份、三位数的金额在这里就出局了），而且紧跟着
# 的量词/单位（「3 家企业」「5 亿元」）不是标题的开头。
_BARE_NUM = (r'\d{1,2}\s+'
             r'(?![\d家个元亿万百千份%年月日张条项位名台辆人倍次])')

# 有编号的标题行。PDF/Word 转出来是裸文本，编号是唯一还留着的层级信息。
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
# 独立成行的固定节名（学刊体例的开篇结尾）。这一组没有编号也要认。
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

    **只认有编号的标题和固定节名，不认「短的独立行」**（实测把「近年来国家和地方密集
    出台…」这种正文短句收进了骨架）。没有编号的短行是误判的重灾区，而骨架判错的代价
    比骨架短更大：提示词里写了「照范本写」，模型就会照着一个错骨架写。范本的**标题
    写法**另外单独取一次（见 describe_format）。
    """
    s = line.strip()
    if not s or len(s) > _HEAD_MAX:
        return ''
    if _ORDINAL.match(s):
        # 去掉编号再挑标点：「一、研究背景与意义」里的「、」是编号自己的分隔符，
        # 不能当句子标点把它否掉（第一版就是这么漏掉一整级的）
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
    # 一张表 = 一段连续的管道行（允许中间有空行，PDF 抽出来常见）
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
    """上传文档 → 一小段「体例说明」。抽不出东西就返回空串（调用方据此退回默认格式）。

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

    # 标题本身：第一行**正文**（跳掉拼上去的「用户上传了文件」标记和表格行）。范本的
    # 标题写法（带不带发文机关、带不带副标题）是要跟的一处体例。
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
    # 开篇/结尾按**行号比例**分，不按固定行数：短文里前 200 行和后 200 行是同一批行，
    # 会得出「开篇有：摘要、参考文献」这种自相矛盾的结论（第一版就是这样）。
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
