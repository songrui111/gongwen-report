"""测试共用的小工具：一个会计数的断言器、一份样本装载、一次子进程调用。

**不引 pytest。** 这一层要能在只装了标准库的机器上跑起来（纯逻辑那几套），
需要第三方库的只有版式那一套 —— 依赖是按文件分的，不是按整套分的。这样一来
「剪出来之后不需要装整个应用栈就能验」这件事本身，是被 `run_all.py` 每天跑出来的，
而不是写在文档里的一句话。

每个 test_*.py 的约定一样：模块里有个 `main()`，跑完返回 `(过不过, 「没验」清单)`，
自己也能单独跑（`py tests/test_print.py`）。**清单非空 = 这一层没验，不是通过** ——
退出码 2，和「验了没过」（1）分开。
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
    """跑一次真命令：`py report_check.py …`，把 stdout / stderr 分开拿回来。

    走真命令行而不是直接 import `gongwen.cli`：退出码、stdout 和 stderr 的分工
    （`--print-system` 的内容走 stdout、`fmt:` 那行走 stderr）是这一层要验的东西，
    直接调函数就绕过去了。

    `env` 里给 `PYTHONIOENCODING` 可以改掉那个默认的 utf-8 —— 绝大多数调用不该改它
    （Windows 控制台默认不是 UTF-8，报告里全是中文），但**正因为它是个默认值，有些
    只在别的编码下才发作的毛病会被它盖住**，要验的时候得能把它掀开（见
    test_assemble 最后那一节）。"""
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
