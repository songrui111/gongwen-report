"""版式：headless Edge 量真页面 + 印 PDF 回读比值。判据一字不改。
五种改坏各自必须由指定那一条报红。
"""
import os
import re
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _harness import Tally, FIXTURES, PREVIEW, main_hook   # noqa: E402

sys.path.insert(0, PREVIEW)
import build                                              # noqa: E402  （preview/build.py）

SAMPLE = os.path.join(FIXTURES, 'print_sample.md')
OPTS = {'recipient': '某某市科学技术局', 'org': '某某市科学技术研究院',
        'date': '2026-10-10'}
HEAD = {'copy_no': '0001', 'secret': '秘密★3年', 'urgency': '特急',
        'banner': '某某市科学技术委员会文件', 'doc_no': '某科发〔2026〕1号',
        'signer': '张三', 'cc': '某某市发展和改革委员会',
        'printer': '某某市科学技术委员会办公室', 'print_date': '2026年10月10日'}
TO_TEXT = OPTS['recipient']      # 主送机关：标题下那一行，要顶格
ORG_TEXT = OPTS['org']           # 发文机关署名：落款第一行，要右空二字

# 3 号 = 16pt。PDF 内容流里的长度单位是 px（1pt = 4/3 px）：16 × 4/3 = 21.33。
# 这个数不是推出来的，是印出来量到的 —— 早先按 pt 读，一路读到 21.33 还以为是 16。
FS_3HAO = 21.33
MM_PER_PT = 25.4 / 72

# @page 给的四边（标准 7.3.5 的版心）。A4 210×297 减去四边就是版心 156×225。
M_LEFT, M_TOP, M_RIGHT, M_BOTTOM = 28.0, 37.0, 26.0, 35.0
BOX_W, BOX_H = 210.0 - M_LEFT - M_RIGHT, 297.0 - M_TOP - M_BOTTOM

TOL_PX = 0.5        # 左缘：半个像素以内算同起排
TOL_MM = 0.3        # 边距：0.3 毫米，比印刷公差严得多，但量出来就是这么准
TOL_FS = 0.1        # 字号
TOL_ZI = 0.05       # 右空：按「字」算，0.05 字 ≈ 一个像素

# 每种「改坏」**该**被哪一条抓住。写成表是因为只判「有红」不够 —— 见模块开头。
BREAKS = {
    'indent': '层次序数同起排',
    'sign': '落款右空（标准 7.3.5.2）',
    'font': '落款字号与正文一致',
    'table': '正文与表格统一 3 号',
    'paper': '版心边距（@page 四边）',
}

_CM = re.compile(r'^([\d.\-]+) ([\d.\-]+) ([\d.\-]+) ([\d.\-]+) ([\d.\-]+) ([\d.\-]+) cm$', re.M)
_RE = re.compile(r'^([\d.\-]+) ([\d.\-]+) ([\d.\-]+) ([\d.\-]+) re$', re.M)


# ---------------------------------------------------------------- 把纸读成数

def page_geom(page):
    """→ {'left','top','w','h'}，单位毫米；读不出来返回 None。

    **边距是从内容流开头的 cm 里读的，不是从文本坐标里算的。** Chrome 每页开头一定是

        .24 0 0 -.24 0 841.92 cm          ← 全局缩放（还翻了 y）
        q
        3.125 0 0 3.125 331.25 437.5 cm   ← 版心原点：331.25 × .24 = 79.5pt = 28.05mm

    第二行的平移量乘第一行的缩放**就是**左边距和上边距；裁切框 `re` 是版心尺寸。

    走文本矩阵（`tm`）行不通：表格里的文本在单元格自己的坐标系里，同一份报告里量到过
    16000 多的 y —— 那是个看着像数字、其实没有含义的值（`--break paper` 下它也会变，
    于是拿它当判据会「碰巧能过」，下一次就不知道飘到哪去了）。
    """
    d = page.get_contents().get_data().decode('latin-1')
    cms = [tuple(map(float, m)) for m in _CM.findall(d)]
    if len(cms) < 2:
        return None
    base, inner = cms[0], cms[1]
    if not inner[0]:                    # 防 0：版面还没排出来就取几何，宁可返回 None
        return None
    g = {'left': inner[4] * abs(base[0]) * MM_PER_PT,
         'top': inner[5] * abs(base[0]) * MM_PER_PT}
    # 裁切框在**里层**坐标系里，换算要乘两级缩放
    s_in = abs(base[0]) * abs(inner[0])
    box = _RE.findall(d)
    if box:
        g['w'] = float(box[0][2]) * s_in * MM_PER_PT
        g['h'] = float(box[0][3]) * s_in * MM_PER_PT
    return g


def page_runs(page):
    """→ [(字号, 左缘, 基线y, 文本)]。左缘和 y 都相对版心（顶格 = 0）。"""
    got = []

    def vis(text, cm, tm, fd, fs):
        if text.strip():
            got.append((round(fs, 2), round(tm[4], 2), round(tm[5], 1), text.strip()))

    page.extract_text(visitor_text=vis)
    return got


def pdf_facts(path):
    """→ 从 PDF 里读出来的事实；读不出来返回 None（缺 pypdf 或者没印出东西）。

    `lines` 是**按基线归过行**的，`fs` 逐 run 收集（字号是 run 自己的属性）。"""
    from pypdf import PdfReader
    rd = PdfReader(path)
    pages = [page_runs(p) for p in rd.pages]
    flat = [r for pg in pages for r in pg]
    if not flat:
        return None
    lines = [group_lines(pg) for pg in pages]
    return {'geom': page_geom(rd.pages[0]),
            'fs': sorted({r[0] for r in flat}),
            'min_fs': min(r[0] for r in flat),
            'lines': lines,
            'first': lines[0],
            'tail': lines[-1]}


def group_lines(runs):
    """把同一基线上连着的一段 run 并成一行，返回 [(字号, 左缘, y, 文本)]。

    **判据一律按行算，不按 run 算。** PDF 里一行文字会被切成好几段，切在哪没有规律：
    `--break font` 下成文日期就是 '10' 和 '⽇' 两段（后一个还掉成了 CJK 部首字形 ——
    那是 pypdf 的 ToUnicode 映射，不是报告的问题）。所以「末页最后两行」不能写成
    「最后两个 run」。"""
    lines = []
    for r in runs:
        if lines and abs(lines[-1][2] - r[2]) < 0.5:
            p = lines[-1]
            lines[-1] = (p[0], min(p[1], r[1]), p[2], p[3] + r[3])
        else:
            lines.append(r)
    return lines


def _at(lines, pred):
    """按文本内容挑一行；挑不到返回 None。挑不到**不算通过**，调用方要记一笔。"""
    for r in lines:
        if pred(r[3]):
            return r
    return None


# ---------------------------------------------------------------- 判据

def judge_dom(m):
    """→ [(判据名, 过不过, 说明)]。`m` 是探针量到的几何。"""
    out = []
    left = m.get('left') or {}

    lv = [(k, left.get(k)) for k in ('h2', 'h3', 'h4', 'p')]
    got = [(k, v) for k, v in lv if v is not None]
    if len(got) != 4:
        out.append(('层次序数同起排', False,
                    f'四个层次没量全（量到 {[k for k, _ in got]}）—— 量不到就不是通过'))
    else:
        vals = [v for _, v in got]
        span = max(vals) - min(vals)
        out.append(('层次序数同起排', span < TOL_PX,
                    '四层左缘 ' + ' / '.join(f'{k}={v:.1f}' for k, v in got)
                    + f'，跨度 {span:.1f}px'))

    for name, cls in (('主送机关顶格', 'doc-to'),
                      ('表号表题/单位行/注不缩进', 'no-indent')):
        v = left.get(cls)
        out.append((name, v is not None and abs(v) < TOL_PX,
                    '没量到' if v is None else f'左缘 {v:.1f}px'))

    sg = m.get('sign') or []
    if len(sg) != 2:
        out.append(('落款两行都在', False, f'量到 {len(sg)} 行'))
        return out
    out.append(('落款两行都在', True, f'{[s["text"] for s in sg]}'))

    fs = sg[0]['fontSize']
    out.append(('落款字号与正文一致', abs(fs - sg[0]['htmlFontSize']) < TOL_FS,
                f'落款 {fs}px，正文 {sg[0]["htmlFontSize"]}px'))
    # 字族名里带引号，用 `in` 而不是相等
    out.append(('落款是仿宋', '仿宋' in (sg[0]['fontFamily'] or ''),
                sg[0]['fontFamily'] or '（空）'))

    w = [s['width'] for s in sg]
    pad = [s['paddingRight'] for s in sg]
    sig_zi = pad[0] / fs                       # 署名右空：标准要求 2 字
    shift = (pad[0] + w[0] - pad[1] - w[1]) / fs   # 日期首字比署名首字右移几个字
    out.append(('落款右空（标准 7.3.5.2）',
                abs(sig_zi - 2) < TOL_ZI and abs(shift - 2) < TOL_ZI,
                f'署名右空 {sig_zi:.2f} 字，日期右移 {shift:.2f} 字（都要 2.00）'))

    out.append(('页面没有 JS 错', not (m.get('errs') or []),
                '；'.join(m.get('errs') or []) or '无'))
    return out


def judge_pdf(p):
    """→ [(判据名, 过不过, 说明)]。`p` 是 pdf_facts() 那个字典。"""
    out = []
    g = p.get('geom')
    if not g:
        out.append(('版心边距（@page 四边）', False, '内容流的 cm 读不出来'))
    else:
        want = {'left': M_LEFT, 'top': M_TOP, 'w': BOX_W, 'h': BOX_H}
        got = {k: g.get(k) for k in want}
        ok = all(v is not None and abs(v - want[k]) < TOL_MM for k, v in got.items())
        out.append(('版心边距（@page 四边）', ok,
                    '读出来 ' + ' '.join(f'{k}={got[k]:.2f}' for k in ('left', 'top', 'w', 'h')
                                        if got[k] is not None)
                    + f'mm；要 left={M_LEFT} top={M_TOP} {BOX_W}×{BOX_H}'))

    # 全文最小字号：正文、表格、表注**一律** 3 号（标准 7.3.3 的那条），所以最小号就是
    # 正文号。表格掉回四号时这条会立刻见红 —— 这是 `--break table` 唯一的出路。
    out.append(('正文与表格统一 3 号', abs(p['min_fs'] - FS_3HAO) < TOL_FS,
                f'全文出现过的字号 {p["fs"]}，最小 {p["min_fs"]}'))

    r0 = p['first']
    for name, pred, label in (
            ('主送机关顶格（纸面上）', lambda s: TO_TEXT in s, '主送机关'),
            ('表号表题顶格（纸面上）', lambda s: re.match(r'^表\s*\d', s) is not None, '表号表题')):
        r = _at(r0, pred)
        out.append((name, r is not None and abs(r[1]) < TOL_PX,
                    f'没找到「{label}」这一行' if r is None else f'左缘 {r[1]}px'))

    # 落款在最后一页的最后两行。**按位置挑而不是按文字**：成文日期里的「日」在 PDF 里
    # 会掉成 CJK 部首字形（⽇），按文字找会找不到 —— 这是 pypdf 的 ToUnicode 映射，不是
    # 报告的问题。
    tail = p['tail']
    two = tail[-2:] if len(tail) >= 2 else []
    if len(two) != 2:
        out.append(('落款两行都在（纸面上）', False, f'末页只有 {len(tail)} 段文本'))
        return out
    org, dat = two[0], two[1]
    org_fs, org_x = org[0], org[1]
    dat_fs, dat_x = dat[0], dat[1]
    out.append(('落款两行都在（纸面上）', ORG_TEXT[:5] in two[0][3],
                f'{two[0][3]!r} / {two[1][3]!r}'))
    out.append(('落款统一 3 号（纸面上）',
                abs(org_fs - FS_3HAO) < TOL_FS and abs(dat_fs - FS_3HAO) < TOL_FS,
                f'署名 {org_fs}px、日期 {dat_fs}px'))
    # 日期比署名右移二字。署名比日期宽（这份样本里是 10 字对 5.6 字），所以标准 7.3.5.2
    # 给的就是「右移二字」。
    out.append(('落款右空（标准 7.3.5.2）', abs((dat_x - org_x) / FS_3HAO - 2) < TOL_ZI,
                f'日期比署名右移 {(dat_x - org_x) / FS_3HAO:.2f} 字（要 2.00）'))
    return out


# ---------------------------------------------------------------- 跑一趟

def measure(brk):
    """→ (DOM 几何, PDF 事实)。同一个 `breaks` 各出一份页面 ——

    探针页面和印的那份**故意不同一份**：探针会把量到的 JSON 写进 `#xprobe` 这个 div，
    它挂在 body 底下、不在 `.report-content` 里，打印时应当被白名单藏掉。用一个页面
    两边共用的话，万一那条白名单坏了，这份 JSON 会印进 PDF 里、把「最小字号」这条
    判据带红 —— 那就成了一条「因为测试自己在页面上多插了一行」而红的判据。
    """
    md = open(SAMPLE, encoding='utf-8').read()
    dom = build.measure(build.build_page(md, OPTS, brk, probe=True))
    out = os.path.join(tempfile.gettempdir(), 'gongwen_print_probe.pdf')
    if os.path.exists(out):
        os.remove(out)
    build.run_edge(build.build_page(md, OPTS, brk), 'pdf', out, budget=40000)
    pdf = pdf_facts(out) if os.path.exists(out) else None
    return dom, pdf


def collect(brk):
    dom, pdf = measure(brk)
    got = []
    if dom:
        got += judge_dom(dom)
    if pdf:
        got += judge_pdf(pdf)
    return got


def main():
    t = Tally()
    if not os.path.exists(SAMPLE):
        t.skip('版式这一层', '没有 fixtures/print_sample.md')
        return True, t.notes

    edge = build.find_edge()
    if not edge:
        # 找不到浏览器 = 这一层**没验**，退出码 2。安静地跳过，这一层迟早变成永远绿的一层。
        t.skip('版式这一层', '没找到 Edge（设 GWREPORT_EDGE 指到 msedge.exe）')
        return True, t.notes
    try:
        import pypdf           # noqa: F401
    except ImportError:
        t.skip('版式这一层', '没装 pypdf（pip install -r requirements.txt）')
        return True, t.notes
    print(f'  用 {edge}')

    print('--- 干净的一份：每条判据都必须绿')
    clean = collect({})
    for name, ok, detail in clean:
        t(ok, f'{name}：{detail}')
    if not clean:
        t.skip('干净的一份', '一条判据都没跑起来')
        return True, t.notes

    for brk, must in BREAKS.items():
        print(f'--- --break {brk}：必须由「{must}」报红')
        got = collect({brk: True})
        red = [n for n, ok, _ in got if not ok]
        hit = must in red
        for name, ok, detail in got:
            if not ok:
                print(f'      ✗ {name}：{detail}')
        t(hit, f'{brk} → 「{must}」报红' + ('' if hit else f'；实际报红的是 {red or "一条都没有"}'))

    print('--- 版头/版记：给了字段就画，没给就不画（fail-closed）')
    md = open(SAMPLE, encoding='utf-8').read()

    def head_dom(with_head):
        opts = dict(OPTS)
        if with_head:
            opts['head'] = HEAD
        return build.measure(build.build_page(md, opts, {}, probe=True))

    dom = head_dom(True)
    hd = (dom or {}).get('head') or {}
    im = (dom or {}).get('imprint') or {}
    t(hd.get('banner') == HEAD['banner'], f'红头文字 = 给的字段（{hd.get("banner")!r}）')
    t('255, 0, 0' in (hd.get('bannerColor') or ''), f'红头是红的（{hd.get("bannerColor")!r}）')
    t(bool(hd.get('rule')), '红色分隔线画了')
    t(bool(im.get('present')) and '抄送：' in (im.get('cc') or ''), '版记抄送行画了')
    dom0 = head_dom(False)
    t(not ((dom0 or {}).get('head') or {}).get('banner'), '没给版头字段：不画红头')
    t(not ((dom0 or {}).get('imprint') or {}).get('present'), '没给版记字段：不画版记')

    return t.ok, t.notes


if __name__ == '__main__':
    sys.exit(main_hook(main, 'test_print：版式（真页面 + 真 PDF）'))
