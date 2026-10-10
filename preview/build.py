"""把一份 Markdown 报告放进预览页，出 PNG / PDF；也是打印版式测试的入口。

    py preview/build.py 报告.md --png out.png        # 截一张图，看版式
    py preview/build.py 报告.md --pdf out.pdf        # 出一份 PDF
    py preview/build.py 报告.md --png out.png --break indent   # 故意改坏，应当一眼看出不对
    py preview/build.py --print-frontier              # 看看这台机器上找不找得到 Edge

**为什么是「生成一个页面」而不是「打开页面再灌内容」。** 早先的预览工具是从
ai-chat.html 里抠 <style> 拼一个新页面，测试则是往 ai-chat.html 的末尾注入探针脚本 ——
注入点靠 `rfind('})();')` 找，主脚本改一次收尾就失配。现在页面上只有一个公开入口
`window.__reportPreview.load(md, opts, breaks)`，谁都可以调，测试和人都走它。
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PAGE = os.path.join(HERE, 'page.html')

# 生成的页面**必须和 page.html 同目录**：页面上那些 <link>/<script src> 是相对路径，
# 换一个目录就得改写它们，而改写又是一处「字节对不上就静默失效」的地方 —— 干脆不做。
BUILT = os.path.join(HERE, '_page.html')

EDGE_CANDIDATES = (
    r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe',
    r'C:\Program Files\Microsoft\Edge\Application\msedge.exe',
    '/usr/bin/microsoft-edge',
    '/usr/bin/microsoft-edge-stable',
    '/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge',
)


def find_edge():
    """找 Edge：环境变量 GWREPORT_EDGE → 常见安装路径 → PATH。找不到返回 None。

    **找不到不是错误，是「这一层没验」。** 版式测试量的是真页面，没有浏览器就没得量；
    这时候应当明确地说没验、给一个和「验了没过」不同的退出码，而不是安静地跳过 ——
    安静地跳过久了，这一层就变成了永远绿的一层。"""
    env = os.environ.get('GWREPORT_EDGE')
    if env and os.path.exists(env):
        return env
    for p in EDGE_CANDIDATES:
        if os.path.exists(p):
            return p
    for name in ('msedge', 'microsoft-edge', 'microsoft-edge-stable'):
        p = shutil.which(name)
        if p:
            return p
    return None


def build_page(md, opts=None, breaks=None, probe=False, out=None):
    """→ 生成好的页面路径。

    `probe=True` 时额外挂上探针（preview/probe.js），页面加载完会把量到的几何写进
    `#xprobe`。人看的页面不带探针。
    """
    with open(PAGE, encoding='utf-8') as f:
        html = f.read()

    payload = {'md': md, 'opts': opts or {}, 'breaks': breaks or {}}
    # 报告正文里的 `</script>` 会把注入的脚本提前截断 —— 转义掉尖括号就没事了
    data = json.dumps(payload, ensure_ascii=False).replace('<', '\\u003c')

    driver = ['<script>window.__preview = ' + data + ';</script>']
    if probe:
        driver.append('<script src="probe.js"></script>')
    driver.append("""<script>
window.__errs = [];
window.addEventListener('error', function (e) { window.__errs.push(String(e.message)); });
(function () {
  var P = window.__preview;
  window.__reportPreview.load(P.md, P.opts, P.breaks).then(function () {
    if (window.__reportPreviewProbe) window.__reportPreviewDump(window.__reportPreviewProbe());
    document.title = 'ready';
  }).catch(function (e) {
    window.__errs.push('load: ' + (e && e.message ? e.message : e));
    if (window.__reportPreviewDump) {
      window.__reportPreviewDump({left: {}, sign: [], errs: window.__errs});
    }
  });
})();
</script>""")

    i = html.rfind('</body>')
    page = out or BUILT
    with open(page, 'w', encoding='utf-8') as f:
        f.write(html[:i] + ''.join(driver) + html[i:])
    return page


def run_edge(page, mode='dom', dest=None, budget=25000, timeout=240):
    """跑一次 headless Edge。`mode` 是 'dom'（抓页面）或 'png' / 'pdf'（落文件）。"""
    edge = find_edge()
    if not edge:
        raise RuntimeError('找不到 Edge（设 GWREPORT_EDGE 指到 msedge.exe）')
    profile = tempfile.mkdtemp(prefix='gongwen_preview_')
    try:
        cmd = [edge, '--headless=new', '--disable-gpu',
               '--allow-file-access-from-files',
               '--virtual-time-budget=' + str(budget),
               '--user-data-dir=' + profile]
        url = 'file:///' + os.path.abspath(page).replace('\\', '/')
        if mode == 'dom':
            cmd += ['--dump-dom', url]
        elif mode == 'png':
            cmd += ['--window-size=1400,2400', '--screenshot=' + dest, url]
        else:
            cmd += ['--no-pdf-header-footer', '--print-to-pdf=' + dest, url]
        return subprocess.run(cmd, capture_output=True, text=True,
                              encoding='utf-8', errors='replace', timeout=timeout)
    finally:
        shutil.rmtree(profile, ignore_errors=True)


def measure(page):
    """→ 探针量到的几何（dict）；没量到就是 None。"""
    r = run_edge(page, 'dom')
    m = re.search(r'id="xprobe">(.*?)</div>', r.stdout or '', re.S)
    if not m:
        return None
    import html as H
    return json.loads(H.unescape(m.group(1)))


def main():
    sys.stdout.reconfigure(encoding='utf-8', line_buffering=True)
    p = argparse.ArgumentParser(prog='build.py', description='把报告放进预览页')
    p.add_argument('report', nargs='?', help='报告 Markdown；不给就用页面自带的说明')
    p.add_argument('--to', default='', help='主送机关（决定标题下那一行要不要顶格）')
    p.add_argument('--org', default='', help='发文机关署名')
    p.add_argument('--date', default='', help='成文日期 YYYY-MM-DD，默认本机当天')
    p.add_argument('--png', metavar='PATH', help='截一张图')
    p.add_argument('--pdf', metavar='PATH', help='印一份 PDF')
    p.add_argument('--break', dest='breaks', action='append', default=[],
                   metavar='WHAT', help='故意改坏：indent / sign / font / table / paper')
    p.add_argument('--print-frontier', action='store_true', help='看看找不找得到 Edge')
    a = p.parse_args()

    if a.print_frontier:
        print(find_edge() or '（没找到 Edge；设 GWREPORT_EDGE 指到 msedge.exe）')
        return 0 if find_edge() else 2

    md = ''
    if a.report:
        with open(a.report, encoding='utf-8') as f:
            md = f.read()

    breaks = {k: True for k in a.breaks}
    page = build_page(md, {'recipient': a.to, 'org': a.org, 'date': a.date}, breaks)
    print(f'页面 → {page}')

    if not find_edge():
        print('找不到 Edge，没出图（这一层没验，不是通过）')
        return 2
    if a.png:
        r = run_edge(page, 'png', a.png)
        print(f'PNG → {a.png}' if os.path.exists(a.png)
              else f'没出 PNG（退出码 {r.returncode}）：{(r.stderr or "")[:200]}')
        return 0 if os.path.exists(a.png) else 1
    if a.pdf:
        r = run_edge(page, 'pdf', a.pdf)
        print(f'PDF → {a.pdf}' if os.path.exists(a.pdf)
              else f'没出 PDF（退出码 {r.returncode}）：{(r.stderr or "")[:200]}')
        return 0 if os.path.exists(a.pdf) else 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
