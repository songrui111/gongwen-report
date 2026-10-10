"""证伪这一层工具本身：坏样本必须报红，不报红的检查项等于没在判。

`py report_check.py --selftest`，零第三方依赖、零网络。
"""
import os

from . import prompt, rules, textlib as T

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
FIXTURES = os.path.join(ROOT, 'fixtures')

GOLDEN_GW = 'golden_gw.md'
GOLDEN_EX = 'golden_exemplar.md'

MUST_FAIL = ('开篇有「摘要」章', '二级标题用「（一）（二）」且不止一个',
             f'不用「-」项目符号（≤{rules.BULLET_MAX} 行）', '正文没有加粗', '没有 emoji',
             f'至少有 {rules.TABLE_MIN} 张表格', '建议用「一是……二是……三是……」',
             '有归类归纳（「划分为三类：……分别为……」）',
             f'正文 {rules.BODY_LO}-{rules.BODY_HI} 字')

# 现造的坏样本：通篇项目符号、加粗当层级、emoji 当小标题、一张表都没有、建议不分条
BAD_SAMPLE = """# 行业分析报告

## 一、行业概况

- 市场规模持续扩大
- 竞争格局较为分散
- 上游集中度高于下游
- 政策支持力度不断加大
- 技术迭代速度明显加快
- 出口占比稳步提升

**总体来看**，行业景气度较高 📈

## 二、重点企业

| 企业 | 份额 |
| --- | --- |
| 甲公司 | 20% |
| 乙公司 | 15% |

## 三、建议

应加大研发投入，完善产业链协同。
"""

_DUP_SENT = '某市新能源汽车产量 72.2 万辆，同比增长 4.2%，增速较上一年明显回落。'


class _Tally:
    def __init__(self):
        self.ok = True
        self.notes = []
        self.n = 0

    def __call__(self, good, label):
        self.n += 1
        print(f'  {"✓" if good else "✗"} {label}')
        self.ok = self.ok and bool(good)
        return bool(good)

    def skip(self, label, why):
        self.notes.append(f'{label}（{why}）')
        print(f'  - {label} 没验：{why}')


def _fixture(name, tally, why='仓库里的 fixtures 不在'):
    path = os.path.join(FIXTURES, name)
    if not os.path.exists(path):
        tally.skip(name, why)
        return ''
    with open(path, encoding='utf-8') as f:
        return f.read()


# ---- 一、规矩表自己的不变量 ----

def _table_parts(t):
    print('=== 规矩表：名字和 gw_only 只能是表里那一份 ===')
    t(len(rules.RULES) == 16, f'16 条规矩（实际 {len(rules.RULES)} 条）')
    t(len(set(rules.RULE_NAMES)) == len(rules.RULE_NAMES), '规则名没有重复')
    t(rules.GW_ONLY_RULES <= set(rules.RULE_NAMES),
      f'公文专属的 {len(rules.GW_ONLY_RULES)} 条都在表里')
    t(GW_EXPECTED <= rules.GW_ONLY_RULES,
      f'该跳过的那几条确实带 gw_only（缺：{sorted(GW_EXPECTED - rules.GW_ONLY_RULES)}）')
    t(f'{rules.BODY_LO}-{rules.BODY_HI}' in rules.RULE_NAMES[-2]
      or any(f'{rules.BODY_LO}-{rules.BODY_HI}' in n for n in rules.RULE_NAMES),
      '篇幅那条的名字是从 BODY_LO/BODY_HI 拼出来的')
    t(all(n in '\n'.join(rules.list_rules()) for n in rules.RULE_NAMES),
      '--list-rules 把 16 条都渲染出来了')


GW_EXPECTED = frozenset((
    '开篇有「摘要」章', '有「数据来源」章且非空', '一级标题用「一、二、三、」',
    '二级标题用「（一）（二）」且不止一个', f'至少有 {rules.TABLE_MIN} 张表格',
    '建议用「一是……二是……三是……」', '有归类归纳（「划分为三类：……分别为……」）',
    f'正文 {rules.BODY_LO}-{rules.BODY_HI} 字',
))


# ---- 二、现造的坏样本必须报红 ----

def _bad_sample_parts(t):
    print('=== 现造的坏样本：这几条必须报红 ===')
    bad, out, _ = rules.check(BAD_SAMPLE)
    failed = {ln[5:].split('  ')[0] for ln in out if ln.startswith('FAIL')}
    for name in MUST_FAIL:
        hit = name in failed
        t(hit, f'{name}' + ('' if hit else ' —— 改坏了它还是绿的，这条没被验到'))
    t(bad >= 7, f'报红条数 {bad} 条（少于 7 就是清单太松）')


# ---- 三、整句重复 ----

def _repeat_parts(t):
    print('=== 整句重复：抄三遍要报，抄两遍不许报 ===')
    s = _DUP_SENT
    head = '# 测试\n\n'

    def doc(*secs):
        return head + ''.join(f'## {n}\n\n{s}\n\n' for n in secs)

    for name, text, want in (
            ('正文两章各抄一遍：不该报', doc('三、发展现状', '七、存在的主要问题'), 0),
            ('正文三章各抄一遍：必须报',
             doc('三、发展现状', '七、存在的主要问题', '八、对策建议'), 1),
            # 摘要整章排除：摘要+正文各一份够 3 次，但正文里只有 2 次，不该报
            ('摘要一句＋正文两章各一句：不该报',
             doc('一、摘要', '三、发展现状', '七、存在的主要问题'), 0),
            ('同一份政策文件引三次：不该报',
             head + '## 一、摘要\n\n见《某市推动低空经济高质量发展行动方案（2024～2027 年）》。'
                    '\n\n## 五、政策\n\n见《某市推动低空经济高质量发展行动方案（2024～2027 年）》。'
                    '\n\n## 数据来源\n\n《某市推动低空经济高质量发展行动方案（2024～2027 年）》。\n', 0)):
        got = len(T.repeat_hits(text))
        t(got == want, f'{name}（报出 {got} 处，期望 {want}）')


# ---- 四、跨文档重合 ----

def _overlap_parts(t):
    print('=== 跨文档：报告和范本逐字重合这一条 ===')
    src = '一是把飞行服务站和起降点作为公共品先行布局，明确建设主体和资金渠道。'
    for name, body, want in (
            ('整句照搬范本：要报', src + '后半段是本文自己写的判断。', 1),
            ('只重合十来个字：不报', '把飞行服务站先行布局即可，其余判断均为本文新增。', 0),
            ('和范本毫无关系：不报', '本文讨论的是产业链上游的整机制造环节。', 0)):
        got = len(T.overlap('## 五、对策建议\n\n' + body + '\n', src + '\n'))
        t(got == want, f'{name}（报出 {got} 处，期望 {want}）')


# ---- 五、模板：槽必须填得满 ----

def _template_parts(t):
    print('=== 模板：槽从模板枚举，漏一个必须吵出来 ===')
    t(prompt.slots(prompt.load(prompt.TEMPLATE))
      == {'topic', 'description', 'recipient', 'structure', 'today'},
      '整份模板的槽就是这 5 个')
    try:
        prompt.render_checked(prompt.STRUCTURE_EXEMPLAR, {'names': '《范本》'})
        t(False, '漏了 outline 必须抛 TemplateError —— 没抛')
    except prompt.TemplateError as e:
        t('outline' in str(e), f'漏了 outline 抛出来并指名道姓：{e}')

    # 假文档标题是裸文本（PDF/Word 抽出来的样子），写成 Markdown 的 ## 反而一行都认不出
    docs = ('[用户上传了文件「关于{2025}年低空经济的方案.md」（4.1 KB），内容如下]\n'
            '某市低空经济发展研究报告\n\n摘  要\n\n本文……\n\n一、引言\n\n正文。\n\n'
            '二、研究设计与数据来源\n\n正文。\n\n参考文献\n\n[1] 某某。\n')
    for label, kw in (('默认公文体例', {}),
                      ('范本体例（文件名里带花括号）',
                       {'description': '模仿这篇文章写一篇', 'docs_text': docs})):
        text = prompt.report_system('测试主题', refs_text='## 参考资料\n资料正文', **kw)
        t(not prompt.slots(text), f'{label}：装完之后一个槽都不剩')
        t('{{' not in text, f'{label}：没有残留的双花括号')
        if kw:
            t('{2025}' in text, f'{label}：文件名里的花括号原样进了 system（没被当模板）')

    t(prompt.report_system('测试主题').count('## 参考资料') == 0,
      '没给参考资料时不加那一节')
    t('## 参考资料' in prompt.report_system('测试主题', refs_text='资料'),
      '给了参考资料时加上那一节')


# ---- 六、范本体裁那一趟要放行 ----

def _exemplar_parts(t, sample):
    print('=== 范本体裁那一趟：公文骨架专属的规矩要按 skip 打 ===')
    _, out_gw, _ = rules.check(sample, gw=True)
    _, out_ex, _ = rules.check(sample, gw=False)

    def names(out, tag):
        return {ln[len(tag):].strip().split('  ')[0] for ln in out if ln.startswith(tag)}

    fails_gw, fails_ex = names(out_gw, 'FAIL'), names(out_ex, 'FAIL')
    skips = names(out_ex, 'skip')
    missed = GW_EXPECTED - skips
    t(not missed, f'{len(GW_EXPECTED) - len(missed)}/{len(GW_EXPECTED)} 条按 skip 打了'
                  + (f'，漏掉：{sorted(missed)}' if missed else ''))
    still = rules.GW_ONLY_RULES & fails_ex
    t(not still, 'gw=False 之后没有再报这几条' + (f'，仍在报：{sorted(still)}' if still else ''))
    t(bool(rules.GW_ONLY_RULES & fails_gw),
      f'同一份文本按公文骨架判会报红（{len(rules.GW_ONLY_RULES & fails_gw)} 条）')


# ---- 七、全绿样本必须全绿 ----

def _golden_parts(t, text):
    print('=== 全绿样本：16 条一条都不许报红 ===')
    bad, out, _ = rules.check(text)
    if bad:
        for ln in out:
            if ln.startswith('FAIL'):
                print(f'    {ln}')
    t(bad == 0, f'{len(text)} 字的抽象样本 0 条报红（实际 {bad} 条）')
    return bad == 0


def selftest():
    """→ (过不过,「没验」清单)。清单非空时调用方给退出码 2 —— 没验 ≠ 通过。"""
    t = _Tally()
    _table_parts(t)
    _bad_sample_parts(t)
    _repeat_parts(t)
    _overlap_parts(t)
    _template_parts(t)

    golden = _fixture(GOLDEN_GW, t, '没有 fixtures/golden_gw.md')
    if golden:
        _golden_parts(t, golden)
    ex = _fixture(GOLDEN_EX, t, '没有 fixtures/golden_exemplar.md')
    if ex:
        _exemplar_parts(t, ex)

    print()
    if t.notes:
        print(f'没验 {len(t.notes)} 项（≠ 通过）：')
        for n in t.notes:
            print(f'  - {n}')
    print(f'自检 {t.n} 项：' + ('全部通过' if t.ok else '有失败项'))
    return t.ok, t.notes