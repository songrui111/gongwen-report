"""文本处理：把一份 Markdown 报告拆成可判定的量 —— 段落、标题、正文串、重复片段。

这一层**不认识任何规矩**，只负责「量」。规矩在 rules.py，两边分开是为了让每条规矩
的判据读起来就是一句话（「≥25 段」），而不是埋在正则里。

几个判据的来历写在各自旁边 —— 它们都是从实跑样本上量出来的，不是估的。
"""
import re

# 正文里不该出现的东西。取的是中文公文正文里绝不会用的区段，避开汉字、全角标点
# 和常用的数学/单位符号。
_EMOJI = re.compile(
    '[\U0001F000-\U0001FAFF\U0001F1E6-\U0001F1FF'
    '\U00002600-\U000027BF\U0000FE0F\U000020E3]')

_HEADING = re.compile(r'^#{1,6}\s')
_TABLE_SEP = re.compile(r'^\s*\|[\s:\-|]+\|\s*$')
_TABLE_ROW = re.compile(r'^\s*\|.*\|\s*$')
BULLET_RE = re.compile(r'^\s*[-*+]\s+')
_QUOTED = re.compile(r'《([^》]{1,40})》')

# 归类归纳：发布稿最像专业报告的一处手法，是「划分为三类：……共 4 个，分别为……」。
# 这一条早先写窄了（只认「划分为」「分为三类」「分为三个梯队」），而实跑报告写的是
# 「大致可分为三档：增速在 30% 以上的共 6 项，分别为……」，机器报了 0，是判据没认
# 出来，不是报告没写。现在把「分为/划分为/归为 + 数字 + 类/档/梯队/层级」和
# 「共 N 个，分别为」两种写法都算上。
CLASSIFY = re.compile(
    r'划分为|划分成'
    r'|(?:可)?分为[一二三四五六七八九十两\d]+(?:个)?[类档层级]'
    r'|归为[一二三四五六七八九十两\d]+(?:个)?[类档]'
    r'|[一二三四五六七八九十两\d]+个(?:梯队|层级|档次)'
    r'|共[一二三四五六七八九十两\d]+(?:个|项|家|类)[，,、]?分别为'
)

# 整句重复的判据：≥24 字的片段出现 3 次就算重复。
#
# 阈值是拿实跑样本量的：改完体例后生成的那份 16000 字报告里有十几处（同一组产量数据
# 在摘要、现状、问题三章各完整陈述一次；「稳妥推进 L4 级自动驾驶……全场景渗透」4 次），
# 而旧提示词那份 5552 字的报告里一处都没有 —— 就是说，这是换体例**新引入**的毛病，
# 不是原来就有的。发布稿的规矩是同一个数据只在首次出现时说完整，后面要用只引结论。
REP_MIN = 24
REP_TIMES = 3

# 「格式跟着上传文档走」那一趟，报告和范本之间逐字重合多少算抄（见 overlap）。
# 和 REP_MIN 取同一个长度：同一个长度标准下，「报告自己内部抄三遍」和「整句搬范本」
# 是同一类事，用户看到 24 这个数也只需要理解一次。
_OVERLAP_MIN = 24
# 对外就说这一个名字：命令行要把这个数打在图表头上（「重合 ≥24 字的片段」），
# 与其让 cli 伸手取私有名，不如在这儿认一次。
OVERLAP_MIN = _OVERLAP_MIN

# 同一个专名，正文和参考资料里可能一处写 “三峡” 一处写 「三峡」，全半角标点也会不一致。
# 比书名号之前先把这些差异抹平 —— 判据自己错，比模型错更难发现。这一条吃过亏：早先拿
# 《…》 和参考资料逐字比，10 条全报「资料里找不到」，逐条看过去才发现 10 条的引号写法
# 都和参考资料不同，而那个不同正是当时的提示词自己要求的。
_PUNCT = str.maketrans({
    '「': '', '」': '', '“': '', '”': '', '‘': '', '’': '',
    '"': '', "'": '', '　': '', ' ': '',
    # 省略号：报告在来源里引一份长标题时常常截断成「《…》前半段……」，资料里是全称。
    # 不抹掉的话，这种正常的截断会被报成「资料里找不到」—— 又是一次判据自己错。
    '…': '', '⋯': '',
    '｜': '|', '，': ',', '（': '(', '）': ')', '：': ':', '；': ';',
    '！': '!', '？': '?', '．': '.',
    '－': '-', '–': '-', '—': '-', '～': '~',
})


def flat(s):
    """抹平引号写法、全半角标点和空白，用来比专名。"""
    return re.sub(r'\s+', '', s).translate(_PUNCT)


# 一级编号「一、」；二级「（一）」。
H2_NUM = re.compile(r'^##\s*([一二三四五六七八九十]+)、')
H3_NUM = re.compile(r'^###\s*（([一二三四五六七八九十]+)）')

# 作文腔。发布稿不用这些。
CLICHE = ('综上所述', '本报告将', '本章将', '如上所述', '总而言之')
# 模型爱在开头加一段自我免责，面板底部本来就有提醒了
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
    """正文连成一串，用来找重复长片段。三处处理，都是为了让报出来的都是真重复：

    行与行之间插一个哨兵字符，不然上一段结尾和下一段开头会被拼成一段本来不存在
    的文字，凑巧够 24 字就会误报。

    书名号里的文件名缩成「《书》」，因为一份政策文件在「发展沿革」「政策环境」
    「数据来源」三处各引一次是正常的引证，不是为凑篇幅的重复 —— 旧样本里的两处
    命中全是这个，一条真重复都没有。

    **「摘要」那一章整章排除。** 摘要是全篇的浓缩，它和后面某一章共用一句话是
    摘要这个体裁本身要求的，不是抄。要求两者零重合，等于逼模型把结论换个说法再写
    一遍，那更糟。真正该报的是**正文各章之间**互相抄 —— 实跑样本里那 12 处重复，
    报的也全是正文之间的。

    `drop_summary=False` 是给 overlap 用的：跨文档比的时候，摘要里照抄范本一句
    同样是抄，那一条排除规则只对「报告自己内部」成立。
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
    """找出在几个章节里各抄了一遍的长片段。返回 [(最长的那份片段, 出现次数), ...]。

    按长度分档统计所有子串的出现位置，再从长到短收：一段话重复 3 次，它的每个子串
    也都重复 3 次，所以必须从最长的那一份开始收，把它的每个出现位置整段标成「已
    覆盖」，只从长度上剥是剥不干净的 —— 错开一个字的两个 42 字片段互不包含，会各报
    一条，同一处重复被拆成三条（第一版就是这么错的）。
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
    # 先出现次数多的，再长的。反过来（先长后短）会把同一处重复报成两条：一句话的
    # 某一截出现 5 次，而带上后半句的更长一截只出现 3 次，长的那条先进来占住位置，
    # 剩下一截的其余两处就露在外面又报一条。
    cands.sort(key=lambda c: (-c[0], -c[1]))

    out, covered = [], set()
    for cnt, L, s, p in cands:
        # 每一处出现都被已经收下的重复盖住了，就不必再报 —— 起点和终点有一头落在
        # 已收下的区间里就算盖住。只看起点不够：同一句话从头引用和从中间引用，起点
        # 能差十几个字，两个窗口互不包含。
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
    """正文里的书名号 ← 只有这一处要人看一眼，机器判不了《X》是真是假。"""
    return sorted({m.group(1).strip() for m in _QUOTED.finditer(text)})


def overlap(report, source, minlen=_OVERLAP_MIN, limit=8):
    """报告和范本**逐字重合**的长片段。返回 [片段, …]，长的在前。

    「模仿格式」这条路上最容易过界的一处：范本同时也是参考资料（它的数据可以用），
    模型顺手就会把范本里成句的判断也搬过来。rules 里的整句重复只看报告**自己**，
    看不见跨文档的照抄，所以这里单独比一次。

    只当**信息**列出来给人看，不当失败项：一句对策的着力点重合是正常的（用户拿同一
    个题材的文章来当范本），整段重合才是抄 —— 这个界线机器画不准，把长度打出来让人判。
    flow 会把行与行之间插哨兵，所以只有同一段之内的连续文字才算重合。
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
