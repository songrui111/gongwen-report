"""把 Markdown 报告拆成可判定的量——段落、标题、正文串、重复片段。

这一层不认识规矩，只负责「量」。规矩在 rules.py。
"""
import re

# 中文公文正文里不会出现的 emoji 区段
_EMOJI = re.compile(
    '[\U0001F000-\U0001FAFF\U0001F1E6-\U0001F1FF'
    '\U00002600-\U000027BF\U0000FE0F\U000020E3]')

_HEADING = re.compile(r'^#{1,6}\s')
_TABLE_SEP = re.compile(r'^\s*\|[\s:\-|]+\|\s*$')
_TABLE_ROW = re.compile(r'^\s*\|.*\|\s*$')
BULLET_RE = re.compile(r'^\s*[-*+]\s+')
_QUOTED = re.compile(r'《([^》]{1,40})》')

# 归类归纳：「划分为/分为/归为 + 数字 + 类/档/梯队」和「共N个，分别为」两种写法
CLASSIFY = re.compile(
    r'划分为|划分成'
    r'|(?:可)?分为[一二三四五六七八九十两\d]+(?:个)?[类档层级]'
    r'|归为[一二三四五六七八九十两\d]+(?:个)?[类档]'
    r'|[一二三四五六七八九十两\d]+个(?:梯队|层级|档次)'
    r'|共[一二三四五六七八九十两\d]+(?:个|项|家|类)[，,、]?分别为'
)

# 整句重复：≥24 字的片段出现 3 次就算重复
REP_MIN = 24
REP_TIMES = 3

# 跨文档重合阈值，和 REP_MIN 取同一个长度
_OVERLAP_MIN = 24
OVERLAP_MIN = _OVERLAP_MIN

# 比书名号之前抹平引号写法、全半角标点和空白
_PUNCT = str.maketrans({
    '「': '', '」': '', '“': '', '”': '', '‘': '', '’': '',
    '"': '', "'": '', '　': '', ' ': '',
    # 省略号：长标题常被截断成「《…》前半段……」，资料里是全称
    '…': '', '⋯': '',
    '｜': '|', '，': ',', '（': '(', '）': ')', '：': ':', '；': ';',
    '！': '!', '？': '?', '．': '.',
    '－': '-', '–': '-', '—': '-', '～': '~',
})


def flat(s):
    """抹平引号写法、全半角标点和空白，用来比专名。"""
    return re.sub(r'\s+', '', s).translate(_PUNCT)


# 一级编号「一、」，二级「（一）」
H2_NUM = re.compile(r'^##\s*([一二三四五六七八九十]+)、')
H3_NUM = re.compile(r'^###\s*（([一二三四五六七八九十]+)）')

CLICHE = ('综上所述', '本报告将', '本章将', '如上所述', '总而言之')
DISCLAIMER = ('免责声明', '不构成任何投资建议')


def lines(text):
    return text.split('\n')


def prose(text):
    """正文（含表格内容，不含标题行、表格分隔行、空白）。"""
    keep = []
    for ln in lines(text):
        if _HEADING.match(ln) or _TABLE_SEP.match(ln):
            continue
        keep.append(ln)
    return re.sub(r'\s+', '', ''.join(keep))


def flow(text, drop_summary=True):
    """正文连成一串，用来找重复长片段。

    行间插哨兵防止跨段误拼。书名号缩成「《书》」排除正常引证。
    摘要整章排除——摘要是全篇浓缩，和后面共用的句子不算抄。
    drop_summary=False 给 overlap 用，跨文档比时不排除摘要。
    """
    keep, in_summary = [], False
    for ln in lines(text):
        if _HEADING.match(ln):
            if drop_summary and ln.startswith('## ') and not ln.startswith('###'):
                in_summary = '摘要' in ln
            continue
        if in_summary or _TABLE_SEP.match(ln):
            continue
        s = re.sub(r'《[^》]{1,60}》', '《书》', ln)
        s = re.sub(r'\s+', '', s)
        if s:
            keep.append(s)
    return '\x00'.join(keep)


def repeat_hits(text, minlen=REP_MIN, times=REP_TIMES, limit=12):
    """找出在几个章节里各抄了一遍的长片段。返回 [(片段, 出现次数), ...]。

    一段话重复 3 次，它的每个子串也都重复 3 次，所以必须从最长的那一份开始收，
    把每个出现位置整段标成已覆盖 —— 只从长度上剥是剥不干净的。
    """
    t = flow(text)
    cands = []
    for L in range(minlen, minlen + 40, 2):
        pos = {}
        for i in range(len(t) - L + 1):
            pos.setdefault(t[i:i + L], []).append(i)
        for s, p in pos.items():
            if len(p) >= times:
                cands.append((len(p), L, s, p))
    # 先出现次数多的，再长的。反过来会把同一处重复报成两条
    cands.sort(key=lambda c: (-c[0], -c[1]))

    out, covered = [], set()
    for cnt, L, s, p in cands:
        # 起点或终点有一头落在已收下的区间里就算盖住。只看起点不够
        if all(i in covered or (i + L - 1) in covered for i in p):
            continue
        out.append((s, cnt))
        for i in p:
            covered.update(range(i, i + L))
    out.sort(key=lambda kv: (-kv[1], -len(kv[0])))
    return out[:limit]


def paragraphs(text):
    """段落数：连续的非空、非标题、非表格、非列表行算一段。"""
    n = 0
    inside = False
    for ln in lines(text):
        s = ln.strip()
        is_body = bool(s) and not (
            _HEADING.match(ln) or _TABLE_ROW.match(ln) or BULLET_RE.match(ln)
            or s.startswith('>') or re.match(r'^\d+[.、]\s', s))
        if is_body and not inside:
            n += 1
        inside = is_body
    return n


def headings(text, level):
    p = '#' * level + ' '
    return [ln.strip() for ln in lines(text) if ln.startswith(p) and not ln.startswith(p + '#')]


def section_body(text, title_pat):
    """取某个标题到下一个同级或更高级标题之间的正文。"""
    out, on = [], False
    for ln in lines(text):
        if _HEADING.match(ln):
            if on:
                break
            on = bool(re.search(title_pat, ln))
            continue
        if on:
            out.append(ln)
    return '\n'.join(out).strip()


def emoji_hits(text):
    return sorted({m.group(0) for m in _EMOJI.finditer(text)})


def tables(text):
    return sum(1 for ln in lines(text) if _TABLE_SEP.match(ln))


def quoted_titles(text):
    """正文里的书名号——这一项要人看一眼，机器判不了《X》是真是假。"""
    return sorted({m.group(1).strip() for m in _QUOTED.finditer(text)})


def overlap(report, source, minlen=_OVERLAP_MIN, limit=8):
    """报告和范本逐字重合的长片段。返回 [片段, …]，长的在前。

    rules 里的整句重复只看报告自己，看不见跨文档的照抄，所以这里单独比一次。
    只当信息列给别人看，不当失败项：着力点重合是正常的，整段重合才可疑。
    """
    a, b = (flow(report, drop_summary=False), flow(source, drop_summary=False))
    if len(a) < minlen or len(b) < minlen:
        return []
    win = {b[i:i + minlen] for i in range(len(b) - minlen + 1)}
    out, i = [], 0
    while i <= len(a) - minlen:
        if a[i:i + minlen] not in win:
            i += 1
            continue
        j = i + 1                       # 往后把这一段尽量接长
        while j <= len(a) - minlen and a[j:j + minlen] in win:
            j += 1
        out.append(a[i:j + minlen - 1])
        i = j + minlen - 1
    # 长的先报；被更长的一段整体盖住的短片段就不必再报了
    out.sort(key=len, reverse=True)
    keep = []
    for s in out:
        if not any(s in k for k in keep):
            keep.append(s)
        if len(keep) >= limit:
            break
    return keep
