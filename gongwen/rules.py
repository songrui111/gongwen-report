"""规矩表：每条一行数据，不是一个 if。名字是唯一来源，--list-rules 从表渲染。

判据一条都不许动。阈值（≥25 段、8000-16000 字、≥24 字重复 3 次、表格 ≥2 张）
都是实跑样本量出来的，搬迁不是重新设计。
"""
import re

from . import textlib as T


BODY_LO, BODY_HI = 8000, 16000
PARA_MIN = 25
BULLET_MAX = 3
TABLE_MIN = 2

# ---- 规则名（唯一真源）----
NAME_SUMMARY = '开篇有「摘要」章'
NAME_SOURCE = '有「数据来源」章且非空'
NAME_H2 = '一级标题用「一、二、三、」'
NAME_H3 = '二级标题用「（一）（二）」且不止一个'
NAME_PARAS = f'正文是段落（≥{PARA_MIN} 段）'
NAME_BULLET = f'不用「-」项目符号（≤{BULLET_MAX} 行）'
NAME_BOLD = '正文没有加粗'
NAME_EMOJI = '没有 emoji'
NAME_TABLE = f'至少有 {TABLE_MIN} 张表格'
NAME_FIG = '不引用「图 N」（本报告没有配图）'
NAME_ENUM = '建议用「一是……二是……三是……」'
NAME_CLASSIFY = '有归类归纳（「划分为三类：……分别为……」）'
NAME_CLICHE = '没有「综上所述」这类作文腔'
NAME_DISCLAIMER = '没有自我免责段（面板底部已有提醒）'
NAME_LEN = f'正文 {BODY_LO}-{BODY_HI} 字'
NAME_REPEAT = f'没有整句重复（≥{T.REP_MIN} 字的片段不得出现 {T.REP_TIMES} 次）'


class Rule:
    """一条规矩。judge(ctx) → (过不过, 附注)。附注在过的时候也打出来。"""

    __slots__ = ('name', 'gw_only', 'judge')

    def __init__(self, name, judge, gw_only=False):
        self.name = name
        self.judge = judge
        self.gw_only = gw_only


def _summary(ctx):
    return bool(ctx['summary']), ('' if ctx['summary'] else f'二级标题是：{ctx["h2"][:4]}')


def _source(ctx):
    ok = ctx['src_ok'] and len(ctx['src_body']) >= 20
    return ok, (f'{len(ctx["src_body"])} 字' if ctx['src_ok'] else '没有这一章')


def _h2(ctx):
    off = ctx['off']
    return not off, (f'不受编号的：{off[:3]}' if off else f'{len(ctx["h2"])} 条')


def _h3(ctx):
    h3, off3 = ctx['h3'], ctx['off3']
    detail = (f'不是这个格式的：{off3[:3]}' if off3 else
              ('一个二级标题都没有' if not h3 else f'{len(h3)} 条'))
    return bool(h3 and not off3), detail


def _paragraphs(ctx):
    return ctx['body_n'] >= PARA_MIN, f'{ctx["body_n"]} 段'


def _bullets(ctx):
    return ctx['bullets'] <= BULLET_MAX, f'{ctx["bullets"]} 行'


def _bold(ctx):
    return ctx['bold'] == 0, f'{ctx["bold"]} 处 **'


def _emoji(ctx):
    return not ctx['emoji'], ''.join(ctx['emoji'][:8])


def _tables(ctx):
    return ctx['tbl'] >= TABLE_MIN, f'{ctx["tbl"]} 张表，表号 {ctx["cap"]} 处'


def _figs(ctx):
    return not ctx['figs'], ''.join(sorted(set(ctx['figs']))[:5])


def _enum(ctx):
    missing = ctx['missing']
    return not missing, (f'缺：{missing}' if missing else '')


def _classify(ctx):
    cls = ctx['cls']
    return bool(cls), (f'{len(cls)} 处：{cls[:3]}' if cls else '一处都没有')


def _cliche(ctx):
    return not ctx['cliche'], f'出现：{ctx["cliche"]}'


def _disclaimer(ctx):
    return not ctx['disclaim'], f'出现：{ctx["disclaim"]}'


def _length(ctx):
    return BODY_LO <= ctx['n'] <= BODY_HI, f'{ctx["n"]} 字'


def _repeat(ctx):
    reps = ctx['reps']
    return not reps, (f'{len(reps)} 处，最多的一段重复 {reps[0][1]} 次：{reps[0][0][:30]}…'
                      if reps else '')


# 顺序就是输出的顺序（结构 → 排版 → 行文 → 篇幅），别随手重排。
RULES = (
    Rule(NAME_SUMMARY, _summary, gw_only=True),
    Rule(NAME_SOURCE, _source, gw_only=True),
    Rule(NAME_H2, _h2, gw_only=True),
    Rule(NAME_H3, _h3, gw_only=True),
    Rule(NAME_PARAS, _paragraphs),
    Rule(NAME_BULLET, _bullets),
    Rule(NAME_BOLD, _bold),
    Rule(NAME_EMOJI, _emoji),
    Rule(NAME_TABLE, _tables, gw_only=True),
    Rule(NAME_FIG, _figs),
    Rule(NAME_ENUM, _enum, gw_only=True),
    Rule(NAME_CLASSIFY, _classify, gw_only=True),
    Rule(NAME_CLICHE, _cliche),
    Rule(NAME_DISCLAIMER, _disclaimer),
    Rule(NAME_LEN, _length, gw_only=True),
    Rule(NAME_REPEAT, _repeat),
)

RULE_NAMES = tuple(r.name for r in RULES)
GW_ONLY_RULES = frozenset(r.name for r in RULES if r.gw_only)

assert len(set(RULE_NAMES)) == len(RULE_NAMES), '规则名有重复'
assert GW_ONLY_RULES <= set(RULE_NAMES), 'GW_ONLY_RULES 里有不在表里的名字'


def context(text):
    """把一份报告算成一组量，供上面的判据取用。算一次，判据们共用。"""
    h2 = T.headings(text, 2)
    h3 = T.headings(text, 3)
    src_ok = any('数据来源' in h for h in h2 + h3)
    return {
        'h2': h2,
        'h3': h3,
        'summary': [h for h in h2 if re.search(r'[一二三四五六七八九十]、\s*摘\s*要', h)],
        'src_ok': src_ok,
        'src_body': T.section_body(text, r'数据来源') if src_ok else '',
        'off': [h for h in h2 if not T.H2_NUM.match(h) and '数据来源' not in h],
        'off3': [h for h in h3 if not T.H3_NUM.match(h)],
        'body_n': T.paragraphs(text),
        'bullets': sum(1 for ln in T.lines(text) if T.BULLET_RE.match(ln)),
        'bold': text.count('**'),
        'emoji': T.emoji_hits(text),
        'tbl': T.tables(text),
        'cap': len(re.findall(r'表\s*\d+', text)),
        'figs': re.findall(r'图\s*\d+', text),
        'missing': [w for w in ('一是', '二是', '三是') if w not in text],
        'cls': T.CLASSIFY.findall(text),
        'cliche': [w for w in T.CLICHE if w in text],
        'disclaim': [w for w in T.DISCLAIMER if w in text],
        'n': len(T.prose(text)),
        'reps': T.repeat_hits(text),
    }


def check(text, refs='', gw=True):
    """跑一遍清单，返回 (失败条数, 每行的输出, 清单式的信息行)。

    gw=False 时 gw_only 的规矩打印成 skip，不计失败。其他的照旧卡。
    """
    ctx = context(text)
    out, bad = [], 0
    for r in RULES:
        if not gw and r.gw_only:
            ok, detail = r.judge(ctx)
            out.append(f'skip  {r.name}{"  " + detail if detail else ""}'
                       '  （本次格式以范本为准，这一条不适用）')
            continue
        ok, detail = r.judge(ctx)
        if not ok:
            bad += 1
        out.append(f'{"ok  " if ok else "FAIL"} {r.name}{"  " + detail if detail else ""}')

    # ---- 只列清单，不判过不过 ----
    info = []
    cls, reps = ctx['cls'], ctx['reps']
    ranks = re.findall(r'第\s*\d+\s*位', text)
    info.append(f'位次表述「第 X 位」：{len(ranks)} 处')
    info.append(f'归类归纳：{len(cls)} 处')
    if reps:
        info.append(f'重复的长片段 {len(reps)} 处（这一段越短越好，每一处都该改写成结论式复述）：')
        for s, c in reps:
            info.append(f'    ×{c}  {s[:48]}…')

    titles = T.quoted_titles(text)
    if not refs:
        info.append(f'参考资料：没有提供，{len(titles)} 处书名号无法核对')
        for t in titles:
            info.append(f'    《{t}》')
    else:
        flat = T.flat(refs)
        miss = [t for t in titles if T.flat(t) not in flat]
        info.append(f'书名号 {len(titles)} 处，其中 {len(miss)} 处在参考资料里找不到：')
        for t in miss:
            info.append(f'    《{t}》')
    return bad, out, info


def list_rules():
    """--list-rules 的输出。只看这张表，不另写一份清单。"""
    out = []
    for r in RULES:
        tag = '公文专属' if r.gw_only else '通用    '
        note = '（照范本格式时跳过）' if r.gw_only else ''
        out.append(f'{tag}  {r.name}{note}')
    return out