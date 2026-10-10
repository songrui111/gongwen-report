"""规矩表那一层：表自己的不变量、坏样本必须报红、全绿样本必须全绿、派生变体只差一处。

`--selftest` 那几十项就是这一层的核心，**这里不抄第二遍** —— 抄一遍就等于有了两份判据，
改一处漏一处，正是这个仓库到处在防的那种事。这里做的是 selftest 做不到的三件事：

1. 把它的结果收成一条能进 `run_all.py` 的断言（`--selftest` 是给人看的，测试要的是
   「过了、而且没有『没验』清单」）；
2. 现派生三个「只差一处」的故障样本，逐份核对**恰好那一条**报红；
3. 证伪规则表本身：把一条规矩的 `gw_only` 翻掉，skip 行为必须跟着变 ——
   证明 `check()` 读的是这张表，而不是又一份平行的手写清单（那是搬过来之前的事故）。
"""
import contextlib
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _harness import Tally, FIXTURES, ROOT, load, main_hook    # noqa: E402

sys.path.insert(0, FIXTURES)          # fixtures/derive.py
import derive                          # noqa: E402

from gongwen import rules, selftest as ST   # noqa: E402


# 三种前缀宽度不同（`ok  ` / `FAIL ` / `skip  `），**别按字数切**：这里写清楚切多少。
def _names(out, tag):
    return {ln[len(tag):].strip().split('  ')[0] for ln in out if ln.startswith(tag)}


def _skip_names(out):
    return _names(out, 'skip  ')


def _fail_names(out):
    return _names(out, 'FAIL ')


def main():
    t = Tally()

    print('--- 一、--selftest 那几十项（收成一条）')
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        ok, notes = ST.selftest()
    detail = buf.getvalue().strip().splitlines()[-1] if buf.getvalue().strip() else '(没有输出)'
    if not (ok and not notes):
        print(buf.getvalue())         # 红了就把那几十行原样倒出来，别让失败只剩一句话
    t(ok, f'证伪那一层全过：{detail}')
    t(not notes, '而且没有「没验」的项目' + (f'：{notes}' if notes else ''))

    print('--- 二、全绿样本必须 0 条报红')
    golden = load('golden_gw.md', t)
    if golden:
        bad, out, info = rules.check(golden)
        for ln in out:
            if ln.startswith('FAIL'):
                print(f'      {ln}')
        t(bad == 0, f'{len(golden)} 字的抽象样本 0 条报红（实际 {bad} 条）')
        t(len(info) > 0, f'清单式的信息行也在（{len(info)} 行）')

    print('--- 三、派生变体：每份**恰好**报出那一条')
    for name, (fn, what, want) in derive.VARIANTS.items():
        text = derive.build(name)
        n, out, _ = rules.check(text)
        failed = sorted(_fail_names(out))
        ok = failed == [want]
        t(ok, f'{name}（{what}）报出 {n} 条' + (f'{failed}' if ok else f'{failed}，期望恰好 [{want}]'))
        t(fn(golden) == text if golden else True, f'{name} 派生是纯函数（同输入同输出）')

    print('--- 四、证伪规则表本身：翻掉一条 gw_only，skip 必须跟着变')
    sample = ST.BAD_SAMPLE
    _, out_gw, _ = rules.check(sample, gw=False)
    before = _skip_names(out_gw)
    target = next(r for r in rules.RULES if r.name == rules.NAME_SUMMARY)
    t(target.gw_only, f'「{rules.NAME_SUMMARY}」本来带 gw_only')
    t(rules.NAME_SUMMARY in before, 'gw=False 时它按 skip 打')
    try:
        target.gw_only = False
        _, out2, _ = rules.check(sample, gw=False)
        after_skip = _skip_names(out2)
        after_fail = _fail_names(out2)
        t(rules.NAME_SUMMARY not in after_skip,
          '翻掉之后不再 skip —— skip 判定读的是表里的字段')
        t(rules.NAME_SUMMARY in after_fail,
          f'而且真的开始卡了（{rules.NAME_SUMMARY}）')
        listed = '\n'.join(rules.list_rules())
        t(f'{rules.NAME_SUMMARY}（照范本格式时跳过）' not in listed,
          '--list-rules 也跟着变了（同一个字段）')
    finally:
        # 这条规矩是这一层的量具，翻完必须放回去；不放回去，后面所有断言都在骗人
        target.gw_only = True
    t(rules.NAME_SUMMARY in _skip_names(rules.check(sample, gw=False)[1]),
      '放回去之后 skip 恢复原样')

    print('--- 五、规矩表自己的形状')
    t(len(rules.RULES) == 16, f'16 条规矩（实际 {len(rules.RULES)}）')
    t(len(set(rules.RULE_NAMES)) == len(rules.RULE_NAMES), '规则名没有重复')
    t(rules.GW_ONLY_RULES <= set(rules.RULE_NAMES), 'gw_only 的名字都在表里')
    t(len(rules.list_rules()) == len(rules.RULES), '--list-rules 一条不少地渲染')
    return t.ok, t.notes


if __name__ == '__main__':
    sys.exit(main_hook(main, 'test_rules：规矩清单'))
