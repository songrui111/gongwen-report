"""公文/行业分析报告生成与检查 —— 命令行入口。

真正的东西在 gongwen/ 包里，这个文件只做一件事：把命令行接上。
放在仓库根上是为了让「clone 下来就能跑」成立：`py report_check.py --selftest`，
不需要装任何第三方依赖、不需要联网、不需要密钥。
"""
import sys

from gongwen.cli import main

if __name__ == '__main__':
    sys.exit(main())
