"""命令行：参数、打印、退出码。判断逻辑不在这里。

退出码：0 全过 / 1 有失败项 / 2 用法错或环境缺东西（含 --gen 没配 key）。
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
    """stdout/stderr 掰成 UTF-8。中文 Windows 重定向时默认选 GBK，✓ 会炸。"""
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding='utf-8', errors='replace')
        except (AttributeError, ValueError, OSError):
            pass


def read_text(path):
    """读文件，没给或不存在就返回空串。"""
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
    p.add_argument('--list-rules', action='store_true', help='打印规矩清单')
    p.add_argument('--print-template', nargs='?', const='all', metavar='NAME',
                   help='打印模板原文；不给名字就打全部')
    p.add_argument('--print-system', action='store_true',
                   help='把装好的 system 打到 stdout（不用 key、不联网）')
    p.add_argument('--topic', default='', help='报告主题')
    p.add_argument('--desc', default='', help='补充说明，写「模仿这篇文章写一篇」就走向范本那条路')
    p.add_argument('--to', default='', help='主送机关（标准 7.3.2），照抄不简写')
    p.add_argument('--docs', default='', help='要模仿/当素材的文档路径')
    p.add_argument('--refs', default='', help='参考资料文件；不给就自动找旁边的 <同名>_refs.md')
    p.add_argument('--today', default='', help='把「今天」定死（快照用），留空取本机当天')
    p.add_argument('--exemplar', action='store_true',
                   help='按范本体裁打分：公文专属那几条按 skip 打')
    p.add_argument('--gen', action='store_true', help='真调模型生成（要配 key，花钱）')
    p.add_argument('--tag', default='report_after', help='--gen 的产物名')
    p.add_argument('--out', default='out', help='--gen 的产物目录')
    return p


def main(argv=None):
    _utf8()
    args = build_parser().parse_args(argv)

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


# ---- 生成 ----

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
        print(f'fmt: {req.fmt}', file=sys.stderr)
        print(req.system)
        return OK

    provider = from_env()
    if not provider.available():
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
        print(f'生成失败，没有落盘：{e}', file=sys.stderr)
        return USAGE
    except KeyboardInterrupt:
        print('\n中断，没有落盘', file=sys.stderr)
        return USAGE

    os.makedirs(args.out or '.', exist_ok=True)
    rp = os.path.join(args.out, args.tag + '.md')
    with open(rp, 'w', encoding='utf-8') as f:
        f.write(text)
    given = prompt.refs_block(refs, docs)
    with open(os.path.join(args.out, args.tag + '_refs.md'), 'w', encoding='utf-8') as f:
        f.write(given or '（本次没有参考资料，来源无法核对）')
    print(f'  报告 {len(text)} 字 → {rp}')

    print()
    bad = _report(text, given, req.gw)
    if docs:
        _overlap_section(text, docs)
    return _summary(bad)


# ---- 检查 ----

def _check(args, path):
    if not os.path.exists(path):
        print(f'读不到 {path}：没有这个文件', file=sys.stderr)
        return USAGE
    text = read_text(path)

    refs = read_text(args.refs)
    if not refs:
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
    """报告和范本逐字重合的片段。只在给了 --docs 时打。"""
    runs = T.overlap(text, docs)
    print()
    print(f'  --- 报告和范本逐字重合 ≥{T.OVERLAP_MIN} 字的片段：{len(runs)} 处 ---')
    if not runs:
        print('  一处都没有')
    for s in runs:
        print(f'    {len(s)} 字：{s[:64]}…' if len(s) > 64 else f'    {len(s)} 字：{s}')
    print('  （对策句的着力点重合不算抄，整句照搬才算。）')


def _summary(bad):
    print()
    print('全部通过' if bad == 0 else f'失败 {bad} 项')
    return OK if bad == 0 else FAIL