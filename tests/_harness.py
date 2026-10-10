"""测试共用工具：断言器、样本装载、子进程调用。不引 pytest。

每个 test_*.py 约定：模块里有个 main()，返回 (过不过, 「没验」清单)。
没验 ≠ 通过 —— 退出码 2 和 1 分开。
"""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURES = os.path.join(ROOT, 'fixtures')
PREVIEW = os.path.join(ROOT, 'preview')
REPORT_CHECK = os.path.join(ROOT, 'report_check.py')

if ROOT not in sys.path:
    sys.path.insert(0, ROOT)          # `import gongwen` 成立


class Tally:
    """数一数断言过了几条，顺手把「没验」记在另一本账上。

    两本账分开是这个仓库里反复出现的那件事：**没验 ≠ 通过**。少一个 fixtures 文件、
    机器上没有 Edge，都不该安静地变绿 —— 那种绿过一阵子就没人再信了。"""

    def __init__(self):
        self.ok = True
        self.n = 0
        self.notes = []

    def __call__(self, good, label):
        self.n += 1
        print(f'  {"✓" if good else "✗"} {label}')
        self.ok = self.ok and bool(good)
        return bool(good)

    def skip(self, label, why):
        self.notes.append(f'{label}（{why}）')
        print(f'  - {label} 没验：{why}')

    def say(self, text):
        print(f'    {text}')


def load(name, t=None, why='仓库里没有这份 fixtures'):
    """读 fixtures/ 下的一份样本；不在就记一笔「没验」并返回空串。"""
    path = os.path.join(FIXTURES, name)
    if not os.path.exists(path):
        if t is not None:
            t.skip(name, why)
        return ''
    with open(path, encoding='utf-8') as f:
        return f.read()


def run_cli(*args, env=None, timeout=300):
    """跑一次真命令。走子进程不 import —— 退出码和 stdout/stderr 分工是这一层要验的。

    PYTHONIOENCODING 默认 utf-8，env 里可以覆盖掉来验 GBK 场景。
    """
    e = dict(os.environ)
    # PYTHONIOENCODING：Windows 上控制台默认不是 UTF-8，报告里全是中文
    e['PYTHONIOENCODING'] = 'utf-8'
    if env:
        e.update(env)
    r = subprocess.run([sys.executable, REPORT_CHECK] + list(args),
                       capture_output=True, text=True, encoding='utf-8',
                       errors='replace', timeout=timeout, env=e, cwd=ROOT)
    return r.returncode, r.stdout or '', r.stderr or ''


def find_edge():
    """找 Edge。找不到返回 None —— **调用方要把它当成「没验」，不是「通过」**。"""
    sys.path.insert(0, PREVIEW)
    try:
        import build
        return build.find_edge()
    finally:
        sys.path.remove(PREVIEW)


def main_hook(mod_main, title):
    """`main()` 的收尾统一走这里：打印账本、定退出码。三个退出码语义见 README。

    **失败优先于「没验」**：两本账都非空时报 1。反过来的话（先看没验），一份有真毛病
    的代码会被报成「有东西没跑」—— 前者要改代码，后者只要装个依赖，把前者的信号盖住
    就等于放过它。两本账都打出来，一条也不藏。
    """
    sys.stdout.reconfigure(encoding='utf-8', line_buffering=True)
    print(f'### {title}')
    ok, notes = mod_main()
    print()
    if notes:
        print(f'没验 {len(notes)} 项（≠ 通过）：')
        for n in notes:
            print(f'  - {n}')
    if not ok:
        print('有失败项')
        return 1
    if notes:
        return 2
    print('全部通过')
    return 0
