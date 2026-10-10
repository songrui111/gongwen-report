"""命令行：退出码、stdout/stderr 分工、没配 key 不落盘。走真子进程。
"""
import os
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _harness import Tally, FIXTURES, ROOT, run_cli, main_hook   # noqa: E402

from gongwen import prompt                                        # noqa: E402

GOLDEN = os.path.join(FIXTURES, 'golden_gw.md')
GOLDEN_EX = os.path.join(FIXTURES, 'golden_exemplar.md')

# 一份病灶明确的短报告：项目符号当层级、加粗当小标题、一张表都没有 —— 报红要报得出来。
BAD = """# 某行业分析报告

## 一、概况

- 规模持续扩大
- 竞争格局分散
- 政策支持力度加大

**总体来看**，行业景气度较高 📈

### （一）结构

情况如上。
"""


def main():
    t = Tally()
    tmp = tempfile.mkdtemp(prefix='gongwen_cli_')
    try:
        return _run(t, tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _run(t, tmp):
    print('--- 一、不给参数：打帮助，退出码 2（不是 0）')
    code, out, err = run_cli()
    t(code == 2, f'退出码 {code}（要 2）')
    t('usage' in out.lower() or '用法' in out, '打了帮助')

    print('--- 二、--selftest / --list-rules / --print-template')
    code, out, err = run_cli('--selftest')
    t(code == 0, f'--selftest 退出码 {code}')
    t('自检' in out and '全部通过' in out, '自检跑到全过')

    code, out, err = run_cli('--list-rules')
    lines = [ln for ln in out.strip().splitlines() if ln.strip()]
    t(code == 0 and len(lines) == 16, f'--list-rules 输出 {len(lines)} 行、退出码 {code}')
    t('公文专属' in out and '通用' in out, '每行标了是不是公文专属')

    code, out, err = run_cli('--print-template')
    t(code == 0 and out.count('=====') == 6, f'--print-template 不给名字：打全部（{out.count("=====")//2} 份）')
    for name in prompt.TEMPLATES:
        t(f'===== {name} =====' in out, f'里面有 {name}')
    code, out, err = run_cli('--print-template', 'structure_gw')
    t(code == 0 and '===== structure_gw =====' in out and 'structure_exemplar' not in out,
      '给名字就只打那一份')
    code, out, err = run_cli('--print-template', '没有这份')
    t(code == 2 and err.strip(), f'名字不对：退出码 {code}，说明写在 stderr')

    print('--- 三、--print-system：正文走 stdout，标签走 stderr（能直接重定向）')
    code, out, err = run_cli('--print-system', '--topic', '某市低空经济产业',
                             '--to', '某某市科学技术局', '--today', '2026-10-10')
    t(code == 0, f'退出码 {code}')
    t('fmt: gw' in err, f'骨架标签在 stderr（{err.strip().splitlines()[0] if err.strip() else "空"}）')
    t('fmt:' not in out, 'stdout 里没有 fmt: 这一行 —— 重定向出来就是干净的规范')
    t('某市低空经济产业' in out and '某某市科学技术局' in out, 'stdout 是装好的 system')
    t('2026年10月10日' in out, '--today 定死了「今天」（快照可复现）')

    print('--- 四、上传文档必须真的进 system（端到端）')
    doc = os.path.join(tmp, '范本.md')
    with open(doc, 'w', encoding='utf-8') as f:
        f.write('某市低空经济产业的空间集聚特征\n\n摘  要\n\n本文以……\n\n一、引言\n\n正文。\n')
    code, out, err = run_cli('--print-system', '--topic', '某市低空经济产业',
                             '--desc', '模仿这篇文章写一篇', '--docs', doc)
    t(code == 0 and 'fmt: exemplar' in err, f'用了范本骨架（{err.strip().splitlines()[0]}）')
    t('本文以……' in out, '范本正文出现在 system 里（模型看得见范本）')
    t(prompt.DOCS_HEAD in out, '带上了「用户上传的参考文档」这一节')
    t(f'《{os.path.basename(doc)}》' in out, '标记行里是真实文件名')

    print('--- 五、参数闸门：错了就说清楚，退出码 2')
    code, out, err = run_cli('--print-system')
    t(code == 2 and '--topic' in err, f'没给主题：退出码 {code}，stderr 指明缺什么')
    code, out, err = run_cli('--print-system', '--topic', '主' * 201)
    t(code == 2 and '200' in err, f'主题超长：退出码 {code}，说清上限')

    print('--- 六、--gen 没配 key：不落盘、不联网、零密钥那条排前面')
    outdir = os.path.join(tmp, 'out')
    code, out, err = run_cli('--gen', '--topic', '某市低空经济产业', '--out', outdir,
                             env={'DEEPSEEK_API_KEY': ''})
    t(code == 2, f'退出码 {code}（要 2：环境缺东西，不是报告不合格）')
    t(not os.path.exists(outdir) or not os.listdir(outdir),
      f'一个字都没落盘（{os.listdir(outdir) if os.path.exists(outdir) else "目录都没建"}）')
    t('零密钥' in err and '直连生成' in err and err.index('零密钥') < err.index('直连生成'),
      '两条路都给了，零密钥那条排在前面')
    t('--print-system' in err, '并且写明了那条命令')
    t('花钱' in err, '也提醒了直连那条会花钱')

    print('--- 七、检查一份报告：全绿 / 有毛病 / 读不到')
    code, out, err = run_cli(GOLDEN)
    t(code == 0, f'全绿样本退出码 {code}')
    t('全部通过' in out, '结尾说「全部通过」')
    t('没验' not in out and 'FAIL' not in out, '没有 FAIL 行')

    badp = os.path.join(tmp, 'bad.md')
    with open(badp, 'w', encoding='utf-8') as f:
        f.write(BAD)
    code, out, err = run_cli(badp)
    t(code == 1, f'有毛病：退出码 {code}（要 1，和「没跑起来」的 2 分开）')
    t('FAIL' in out and '失败' in out, '报出 FAIL 行并给了失败条数')

    code, out, err = run_cli(os.path.join(tmp, '没有这个文件.md'))
    t(code == 2 and '读不到' in err, f'文件不在：退出码 {code}，stderr 说明白')

    print('--- 八、--exemplar：照范本体例打分')
    code, out, err = run_cli(GOLDEN_EX, '--exemplar')
    t(code == 0, f'范本样本按范本体例打分：退出码 {code}')
    t('skip' in out and (out.count('skip') >= 8), f'公文专属那几条按 skip 打（{out.count("skip")} 处）')
    code2, out2, _ = run_cli(GOLDEN_EX)
    t(code2 == 1 and '按范本体例打分' not in out2,
      f'同一份不 --exemplar 就报红（退出码 {code2}）—— 说明 --exemplar 真的在起作用')

    print('--- 九、旁边的 <同名>_refs.md：自动读，没有就说出来')
    rep = os.path.join(tmp, '报告.md')
    with open(rep, 'w', encoding='utf-8') as f:
        f.write(open(GOLDEN, encoding='utf-8').read())
    code, out, err = run_cli(rep)
    t('无法核对' in out, '没有 _refs.md 时明说书名号那一层核不了（不是默默跳过）')
    with open(os.path.join(tmp, '报告_refs.md'), 'w', encoding='utf-8') as f:
        f.write('某市低空经济产业发展规划（2025—2027 年）。')
    code, out, err = run_cli(rep)
    t('无法核对' not in out and '找不到' in out,
      '放了 _refs.md 就自动读了，并逐条给出找不到的《》')
    t(code == 0, f'退出码 {code}（书名号对不上只列清单，不算失败）')

    print('--- 十、--refs 指到哪读哪')
    refs = os.path.join(tmp, '资料.md')
    with open(refs, 'w', encoding='utf-8') as f:
        f.write('某市低空经济产业发展规划（2025—2027 年）。')
    code, out, err = run_cli(GOLDEN, '--refs', refs)
    t(code == 0 and '无法核对' not in out, '给了 --refs 就不再提示「核不了」')

    print('--- 十一、控制台不是 UTF-8 时也得能跑（**这一节是实跑撞出来的**）')
    # `py report_check.py --selftest > 结果.txt` 在中文 Windows 上崩过一次：
    # `UnicodeEncodeError: 'gbk' codec can't encode '✓'` —— 重定向时 Python 不再走
    # 控制台 API，改用本地编码（GBK），账本里的 ✓ 一句都打不出来就崩在打印上。
    # 上面每一个调用都默认塞了 PYTHONIOENCODING=utf-8，**正好把它盖住**：默认值是给
    # 正常用法准备的，验这个毛病的时候必须把它掀开。显式给 gbk —— 不依赖本机语言，
    # 任何平台上都能复现（不然这条断言在 Linux 上永远是绿的，等于没有）。
    for arg, want in (('--selftest', '自检'), ('--list-rules', '通用')):
        code, out, err = run_cli(arg, env={'PYTHONIOENCODING': 'gbk'})
        t(code == 0 and 'Traceback' not in err,
          f'PYTHONIOENCODING=gbk 时 {arg} 退出码 {code}'
          + ('' if code == 0 else f'；{err.strip().splitlines()[-1][:90]}'))
        t(want in out, f'{arg} 的输出没被编码吃掉（找得到「{want}」）')

    print('--- 十二、stdout 被重定向（不是管道而是文件）也一样')
    red = os.path.join(tmp, '结果.txt')
    with open(red, 'w', encoding='utf-8') as fh:
        p = subprocess.run([sys.executable, os.path.join(ROOT, 'report_check.py'), '--selftest'],
                           stdout=fh, stderr=subprocess.PIPE, text=True,
                           encoding='utf-8', errors='replace', cwd=ROOT,
                           env=dict(os.environ, PYTHONIOENCODING='gbk'))
    body = open(red, encoding='utf-8').read()
    t(p.returncode == 0 and '全部通过' in body,
      f'输出重定向到文件：退出码 {p.returncode}、文件里是 UTF-8 的「全部通过」（{len(body)} 字）')
    return t.ok, t.notes


if __name__ == '__main__':
    sys.exit(main_hook(main, 'test_assemble：命令行（真子进程）'))
