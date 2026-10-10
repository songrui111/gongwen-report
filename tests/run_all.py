"""一次跑完全部。**跑的是子进程**，不是 import。

两个理由：

1. 有几个模块会动全局状态（`rules.Rule.gw_only` 临时翻转、`os.environ` 里塞假钥匙、
   `sys.path` 上加东西）。同一个进程里连跑，顺序就成了隐藏的耦合。
2. 一个一个单跑是**人**的用法（`py tests/test_rules.py`），这里是**流水线**的用法。
   两者走同一个入口，就不会出现「单跑绿、连跑红」。

输出**逐行透传**（不是跑完才打）：`test_print` 要开 Edge 印 PDF、跑一两分钟，
憋着不吭声的话，看的人会以为卡住了。

退出码汇总：**有一个报红就是 1**（那是真问题，比「没验」要紧），全都没红但有「没验」
才给 2，全绿 0。汇总表里顺带给每个模块数一下账：✓ / ✗ / 没验 各几条。
"""
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

# 顺序有意：先快后慢。test_print 要开 Edge 印 PDF，最慢，放最后 —— 前面红了的话，
# 看一眼就知道不用等它了。
MODULES = ('test_no_secrets', 'test_rules', 'test_prompt', 'test_docformat',
           'test_generate', 'test_assemble', 'test_print')

VERDICT = {0: '全绿', 1: '有失败项', 2: '没验 / 用法错'}


def run_one(name, python=sys.executable):
    """跑一个模块。→ (退出码, 秒数, ✓ 条数, 没验条数)，输出边跑边打。

    **不数 `✗`。** 有的模块会**故意**打印红行 —— `test_print` 拿 `--break` 把版面改坏，
    改坏的那几条本来就该红，它把红行打出来正是给人看「红的是不是那一条」。把那些数进
    「失败」里，汇总表就会写着「20 通过 / 10 失败 / 全绿」这种自相矛盾的话。红不红看
    退出码和各模块自己的收尾行（`全部通过` / `有失败项`），那是唯一不会读错的地方。
    """
    path = os.path.join(HERE, name + '.py')
    print(f'\n{"=" * 72}\n{name}\n{"=" * 72}', flush=True)
    env = dict(os.environ, PYTHONIOENCODING='utf-8')
    t0 = time.time()
    n_ok = n_skip = 0
    p = subprocess.Popen([python, path], cwd=ROOT, env=env, text=True,
                         encoding='utf-8', errors='replace',
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    for line in p.stdout:                      # 逐行，边跑边打
        line = line.rstrip('\n')
        # 账本行长这样（见 _harness.Tally）：`  ✓ 判据` / `  ✗ 判据` / `  - 判据 没验：…`
        s = line.strip()
        if s.startswith('✓'):
            n_ok += 1
        elif s.startswith('- ') and '没验' in s:
            n_skip += 1
        print(line, flush=True)
    p.stdout.close()
    return p.wait(), time.time() - t0, n_ok, n_skip


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    want = [a for a in argv if not a.startswith('-')]
    names = [n for n in MODULES
             if not want or n in want or n.replace('test_', '') in want]
    unknown = [a for a in want
               if a not in MODULES and a.replace('test_', '') not in MODULES]
    if unknown:
        print(f'没有这几个模块：{unknown}\n可选：{list(MODULES)}', file=sys.stderr)
        return 2
    if not names:
        print(f'用法：py tests/run_all.py [模块名…]\n模块：{list(MODULES)}'
              f'（也可以省掉 test_ 前缀，只给后面的名字）', file=sys.stderr)
        return 2

    rows = []
    for n in names:
        code, secs, ok, skip = run_one(n)
        rows.append((n, code, secs, ok, skip))

    print(f'\n{"=" * 72}\n汇总\n{"=" * 72}')
    for n, code, secs, ok, skip in rows:
        tally = f'{ok} 条通过' + (f' / {skip} 没验' if skip else '')
        print(f'  {code}  {n:<18} {secs:6.1f}s  {tally:<24}'
              f'{VERDICT.get(code, f"异常退出码 {code}")}')

    if any(c == 1 for c in (r[1] for r in rows)):
        bad = [r[0] for r in rows if r[1] == 1]
        print(f'\n结论：有失败项（退出码 1）—— {bad}')
        return 1
    if any(r[1] == 2 for r in rows):
        miss = [r[0] for r in rows if r[1] == 2]
        print(f'\n结论：没有失败项，但这几层没跑起来（退出码 2）：{miss}')
        print('      **没跑 ≠ 通过** —— 装好依赖或设好 GWREPORT_EDGE 再来一遍。')
        return 2
    total = sum(r[3] for r in rows)
    print(f'\n结论：{len(rows)} 个模块、{total} 条判据全部通过。')
    return 0


if __name__ == '__main__':
    sys.exit(main())
