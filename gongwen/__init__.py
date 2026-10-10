"""一份规范，两个壳：库（`from gongwen import rules`）和命令行（`py report_check.py`）。

分层：
    textlib   量 — 段落、标题、正文串、重复片段
    rules     规矩表 — 每条一行数据，判据不许随手改
    prompt    提示词 — 三份模板 + 填槽 + 体例识别
    generate  唯一调模型的地方；provider 是接缝，测试里换假的
    selftest  证伪这一层：坏样本必须报红
    cli       参数、退出码、落盘

这个包不联网、不读密钥、不碰数据库。只有 provider 发请求，且只读环境变量、没有默认 key。
"""
__version__ = '1.0.0'
__all__ = ['textlib', 'rules', 'prompt', 'docformat', 'generate', 'provider',
           'selftest', 'cli']