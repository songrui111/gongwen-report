"""命令行这一层：参数、打印、退出码。**判断逻辑一条都不在这里。**

退出码：`0` 全过 / `1` 有失败项 / `2` 用法错或环境缺东西（含 `--gen` 没配 key）。
`2` 和 `1` 分开是有意的：脚本里靠退出码判断「报告合格吗」的时候，把「我没跑起来」
混进「报告不合格」里，比不检查更糟。
"""
import argparse
import os
import sys

from . import generate as G
from . import prompt, rules, selftest as selftest_mod, textlib as T
from .provider import UpstreamError, from_env

OK, FAIL, USAGE = 0, 1, 2

DESC = '公文/行业分析报告生成与检查（GB/T 9704—2012 体例）'


def _utf8():
    """把 stdout / stderr 掰成 UTF-8。

    **重定向时会崩**，这是实跑撞到的：`py report_check.py --selftest > 结果.txt`
    在中文 Windows 上抛 `UnicodeEncodeError: 'gbk' codec can't encode '\\u2713'` ——
    报告和账本里全是中文和 ✓，一句都打不出来。控制台里反而不崩（Python 在那里走的是
    控制台 API，编码本来就是 UTF-8），所以**只在管道里发作**：pipeline 里最容易被
    当成「工具坏了」，其实只坏在打印这一步。

    `errors='replace'` 是兜底：万一还有掰不动的东西（老版本 Python），宁可打出一个
    `?` 也不能崩在半句话上。
    """
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding='utf-8', errors='replace')
        except (AttributeError, ValueError, OSError):
            pass


def read_text(path):
    """读文件；没有（或没给路径）就返回空串。**「没给」和「空了」在调用方是一回事**：
    没给参考资料和给了一份空的，都是核不了来源。"""
    if not path or not os.path.exists(path):
        return ''
    with open(path, encoding='utf-8') as f:
        return f.read()


def build_parser():
    p = argparse.ArgumentParser(
        prog='report_check.py', description=DESC,
        epilog='零密钥那条路：--print-system 把规范打到 stdout，交给宿主模型照它写，'
               '写完再用本工具检查。')
    p.add_argument('report', nargs='?', help='要检查的 Markdown 报告')
    p.add_argument('--selftest', action='store_true', help='证伪这个工具本身')
    p.add_argument('--list-rules', action='store_true', help='打印规矩清单（从规则表渲染）')
    p.add_argument('--print-template', nargs='?', const='all', metavar='NAME',
                   help='打印模板原文：report_template / structure_gw / '
                        'structure_exemplar，不给名字就打全部')
    p.add_argument('--print-system', action='store_true',
                   help='把装好的 system 打到 stdout（不用 key、不联网）')
    p.add_argument('--topic', default='', help='报告主题；--print-system / --gen 用')
    p.add_argument('--desc', default='', help='补充说明（写「模仿这篇文章写一篇」就走向范本那条路）')
    p.add_argument('--to', default='', help='主送机关（标准 7.3.2），照抄不简写')
    p.add_argument('--docs', default='', help='要模仿/当素材的文档路径')
    p.add_argument('--refs', default='', help='参考资料文件；不给就自动找旁边的 <同名>_refs.md')
    p.add_argument('--today', default='', help='把「今天」定死（快照用），留空取本机当天')
    p.add_argument('--exemplar', action='store_true',
                   help='按范本体裁打分：公文骨架专属的那几条按 skip 打')
    p.add_argument('--gen', action='store_true', help='真调模型生成一份（要配 key，要花钱）')
    p.add_argument('--tag', default='report_after', help='--gen 的产物名，默认 report_after')
    p.add_argument('--out', default='out', help='--gen 的产物目录，默认 out')
    return p


def main(argv=None):
    _utf8()
    args = build_parser().parse_args(argv)

    # ---- 不用 key 的四件事 ----
    if args.selftest:
        ok, notes = selftest_mod.selftest()
        if notes:
            print('（「没验」不等于「通过」）')
            return USAGE
        return OK if ok else FAIL

    if args.list_rules:
        for line in rules.list_rules():
            print(line)
        return OK

    if args.print_template:
        names = prompt.TEMPLATES if args.print_template == 'all' else (args.print_template,)
        for n in names:
            try:
                text = prompt.load(n)
            except KeyError as e:
                print(e.args[0], file=sys.stderr)
                return USAGE
            print(f'===== {n} =====')
            print(text)
        return OK

    if args.print_system or args.gen:
        return _generate(args)

    if args.report:
        return _check(args, args.report)

    build_parser().print_help()
    return USAGE


# ---------------- 生成（唯一要 key 的一条路）----------------


def _generate(args):
    if not args.topic:
        print('--print-system / --gen 都要给 --topic', file=sys.stderr)
        return USAGE
    refs = read_text(args.refs)
    docs = G.read_docs(args.docs)
    try:
        req = G.build(args.topic, args.desc, refs, args.to, docs, args.today)
    except (ValueError, prompt.TemplateError) as e:
        print(f'参数不对：{e}', file=sys.stderr)
        return USAGE

    print(f'  主送机关 {args.to or "（未给）"}；补充说明 {args.desc or "（空的）"}；'
          f'骨架 {req.fmt}；参考资料 {len(refs)} 字；上传文档 {len(docs)} 字',
          file=sys.stderr)

    if args.print_system:
        # 骨架标签走 stderr，正文走 stdout —— 这样 `--print-system > system.md` 拿到的
        # 是干净的一份可直接喂给宿主模型的规范
        print(f'fmt: {req.fmt}', file=sys.stderr)
        print(req.system)
        return OK

    provider = from_env()
    if not provider.available():
        # 零密钥那条排前面：它永远可用，而「配一把 key」需要用户先决定去花钱
        print(f'{provider.name} 没配 key。两条路：\n'
              f'  1) 零密钥：py report_check.py --print-system --topic "…" > system.md\n'
              f'     把 system.md 交给宿主模型照着写，写完再 py report_check.py 报告.md\n'
              f'  2) 直连生成：设好环境变量再跑（.env.example 里那三个），'
              f'这一步会真的调模型、真的花钱', file=sys.stderr)
        return USAGE

    print(f'=== 生成：{args.topic} → {os.path.join(args.out, args.tag)}.md ===')
    try:
        text = G.generate(args.topic, provider, args.desc, refs, args.to, docs,
                          args.today, echo=lambda s: print('  ' + s, flush=True))
    except UpstreamError as e:
        # 上游不给字就**不落盘**：一份半截报告比没有报告更误导人
        print(f'生成失败，没有落盘：{e}', file=sys.stderr)
        return USAGE
    except KeyboardInterrupt:
        print('\n中断，没有落盘', file=sys.stderr)
        return USAGE

    os.makedirs(args.out or '.', exist_ok=True)
    rp = os.path.join(args.out, args.tag + '.md')
    with open(rp, 'w', encoding='utf-8') as f:
        f.write(text)
    # 参考资料也落一份：检查的时候会自动读旁边的 <同名>_refs.md，来源才核得动。
    # **写的是模型看到的那一份**（上传文档也算参考资料，见 prompt.refs_block）——
    # 落一份少的，书名号那一层就会把范本里引过的文件误判成编的。
    given = prompt.refs_block(refs, docs)
    with open(os.path.join(args.out, args.tag + '_refs.md'), 'w', encoding='utf-8') as f:
        f.write(given or '（本次没有参考资料，来源无法核对）')
    print(f'  报告 {len(text)} 字 → {rp}')

    print()
    bad = _report(text, given, req.gw)
    if docs:
        _overlap_section(text, docs)
    return _summary(bad)


# ---------------- 检查 ----------------

def _check(args, path):
    if not os.path.exists(path):
        print(f'读不到 {path}：没有这个文件', file=sys.stderr)
        return USAGE
    text = read_text(path)

    refs = read_text(args.refs)
    if not refs:
        # 老约定：报告旁边放一份 <同名>_refs.md —— 生成的时候自动写，检查的时候自动读。
        # 没有它，「书名号里的名字是不是编的」这一层根本判不了，所以要说出来而不是
        # 默默跳过：报告照样打分，但少了一层，用户得知道。
        side = os.path.splitext(path)[0] + '_refs.md'
        refs = read_text(side)
        if not refs:
            print(f'  （{side} 不在，书名号那一层无法核对）')

    print(f'=== 检查 {path}（{len(text)} 字）'
          f'{"，按范本体例打分（--exemplar）" if args.exemplar else ""} ===')
    bad = _report(text, refs, gw=not args.exemplar)
    if args.docs:
        _overlap_section(text, G.read_docs(args.docs))
    return _summary(bad)


def _report(text, refs, gw):
    bad, out, info = rules.check(text, refs, gw)
    for line in out:
        print(f'  {line}')
    print('  --- 机器判不了的，列出来给人看 ---')
    for line in info:
        print(f'  {line}')
    return bad


def _overlap_section(text, docs):
    """报告和范本逐字重合的那几段。只在给了 --docs 的时候打。"""
    runs = T.overlap(text, docs)
    print()
    print(f'  --- 报告和范本逐字重合 ≥{T.OVERLAP_MIN} 字的片段：{len(runs)} 处 ---')
    if not runs:
        print('  一处都没有')
    for s in runs:
        print(f'    {len(s)} 字：{s[:64]}…' if len(s) > 64 else f'    {len(s)} 字：{s}')
    print('  （对策句的着力点重合不算抄 —— 同一个题材的范本，判断本来就该像；'
          '整句照搬才是把范本当内容模板用了）')


def _summary(bad):
    print()
    print('全部通过' if bad == 0 else f'失败 {bad} 项')
    return OK if bad == 0 else FAIL
