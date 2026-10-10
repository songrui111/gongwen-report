"""从全绿样本派生出几个「只差一处」的故障样本。

**为什么要派生，不直接写死三份坏样本。** 坏样本一旦 check in，就多了一个要维护的
拷贝：改了全绿样本忘了同步，坏样本里就有别的毛病混进来，测试报红时你分不清是
「这一条没生效」还是「样本串味了」。所以坏样本一律**现派生**，每次只做一处写明白的
改动，派生的同时立刻验一遍「确实只报出那一条」。

跑法：

    py fixtures/derive.py          # 派生到 fixtures/_derived/，并逐份实跑核对
    py fixtures/derive.py --print  # 只打印改动说明

`build(name)` 给测试用：测试现派生、现断言，不依赖磁盘上有没有生成过。
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from gongwen import rules                                        # noqa: E402

GOLDEN = os.path.join(HERE, 'golden_gw.md')
OUT = os.path.join(HERE, '_derived')

# 在「三、发展现状」里原样出现过的一句话。派生的重复样本把它再抄到另外两章 ——
# 三次就是重复，两次不是（阈值就在这儿）。
SENT = ('2025 年某市低空经济全产业链产值 412.6 亿元，比 2024 年的 333.3 亿元'
        '增加 79.3 亿元')

# 表 1 那一整块（表题 + 三行），派生「只剩一张表」的样本时整块删掉
TABLE_1_HEAD = '表 1 某市低空经济产业分析框架'


def _read():
    with open(GOLDEN, encoding='utf-8') as f:
        return f.read()


def break_repeat(text):
    """同一句 24 字以上的话在三个章节各出现一次 —— 应该正好报出 1 处重复。"""
    return (text.replace('### （三）区域分布与位次',
                         f'{SENT}，按可比口径计算同比增长 23.8%。\n\n### （三）区域分布与位次')
                .replace('## 八、对策建议',
                         f'{SENT}，按可比口径计算同比增长 23.8%。\n\n## 八、对策建议'))


def break_table(text):
    """把「表 1」整块删掉，全文只剩一张表。"""
    lines, out, skipping = text.split('\n'), [], False
    for ln in lines:
        if ln.strip().startswith(TABLE_1_HEAD):
            skipping = True
            continue
        if skipping:
            # 表题后面的空行、表头、分隔行、数据行一起删；遇到第一个非表格行收手
            if ln.strip() == '' or ln.lstrip().startswith('|'):
                continue
            skipping = False
        out.append(ln)
    return '\n'.join(out)


def break_bold(text):
    """给一处判断句加粗 —— 正文加粗是发布稿体例里明确不要的。"""
    return text.replace('判断某市低空经济下一阶段的关键，不在继续扩大整机产能，而在补上保障能力和应用场景两端。',
                        '**判断某市低空经济下一阶段的关键**，不在继续扩大整机产能，'
                        '而在补上保障能力和应用场景两端。')


# 名字 → (派生函数, 这一处改的是什么, 期望报出的那一条规则名)
VARIANTS = {
    'broken_repeat.md': (break_repeat, '同一句话在三个章节各出现一次',
                         f'没有整句重复（≥24 字的片段不得出现 3 次）'),
    'broken_table.md': (break_table, '删掉表 1，全文只剩一张表',
                        f'至少有 {rules.TABLE_MIN} 张表格'),
    'broken_bold.md': (break_bold, '一处判断句加了粗', '正文没有加粗'),
}


def build(name):
    """→ 派生出故障样本的正文。没派生过的名字直接 KeyError。"""
    fn, _, _ = VARIANTS[name]
    return fn(_read())


def main(argv):
    if '--print' in argv:
        for name, (_, what, rule) in VARIANTS.items():
            print(f'{name}：{what} → 期望报出「{rule}」')
        return 0

    os.makedirs(OUT, exist_ok=True)
    bad = 0
    for name, (fn, what, rule) in VARIANTS.items():
        text = build(name)
        path = os.path.join(OUT, name)
        with open(path, 'w', encoding='utf-8') as f:
            f.write(text)
        n, out, _ = rules.check(text)
        failed = [ln[5:].split('  ')[0] for ln in out if ln.startswith('FAIL')]
        ok = failed == [rule]
        bad += 0 if ok else 1
        print(f'  {"✓" if ok else "✗"} {name}：{what}；报出 {n} 条 {failed}')
        if not ok:
            print(f'    期望恰好是 [{rule}]')
    print('派生样本逐份核对通过' if not bad else f'{bad} 份不符合预期')
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
