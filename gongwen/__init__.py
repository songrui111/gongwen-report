"""公文报告生成：一份规范，两个壳。

    from gongwen import rules, prompt          # 库
    py report_check.py 报告.md                  # 命令行

分层（改动时请守着这条线）：

    textlib   量：段落、标题、正文串、重复片段。不认识规矩。
    rules     规矩：一张表，每条一行数据。判据不许随手改。
    prompt    提示词：三份模板 + 填槽 + 上传文档的体例识别（docformat）
    generate  唯一调模型的地方；provider 是它的接缝，测试里换成假的。
    selftest  证伪这一层工具本身：坏样本必须报红。
    cli       参数、退出码、落盘。

**这个包不联网、不读密钥、不碰数据库**：只有 `provider` 会发请求，而它只读环境变量、
没有默认 key。所以 `--selftest` 和全部纯逻辑测试不需要装任何第三方依赖就能跑。
"""

__version__ = '1.0.0'

__all__ = ['textlib', 'rules', 'prompt', 'docformat', 'generate', 'provider',
           'selftest', 'cli']
