"""扫全仓，明文密钥一个字都不许有。

老仓库的教训：三把明文密钥跟着 20 个提交进了历史，`api_key = os.getenv("…", "sk-真钥匙")`
的第二参数就是钥匙本身。删掉那一行不算修好 —— 历史里的每一版都还有。所以这个新仓库
从第一个提交起就由这条测试守着。

**扫描器自己也要被证伪**：下面拿一份「假钥匙」当阳性对照，扫不到就说明这条测试根本没
在判（那种「永远绿」的检查比没有更坏）。所以 `scan()` 是纯函数，能被对照组直接调用。
"""
import ast
import os
import re
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _harness import Tally, ROOT, main_hook                  # noqa: E402

from gongwen import provider                                 # noqa: E402

SKIP_DIRS = {'.git', '__pycache__', '_derived', 'node_modules', '.venv', 'venv'}
SKIP_EXT = {'.pdf', '.png', '.jpg', '.jpeg', '.gif', '.ico', '.zip', '.gz',
            '.pyc', '.woff', '.woff2', '.ttf', '.exe', '.dll'}
SKIP_NAMES = {'_page.html', '_probe.pdf'}      # 预览生成的中间件

# 名字里带这些的，都是「不该有兜底值」的那一类
KEYISH = re.compile(r'(?i)key|token|secret|passw|credential|auth')


def _p(*parts):
    """把模式拼起来。**不用完整字面量** —— 不然这个文件自己就会命中自己。"""
    return ''.join(parts)


# 名字 → 正则。前六条是各家钥匙的固定形状，最后一条是 JSON 里的键值对。
PATTERNS = (
    ('OpenAI/DeepSeek 风格', re.compile(_p('s', 'k-') + r'[A-Za-z0-9_\-]{16,}')),
    ('百度千帆', re.compile(_p('bce', '-v3/ALTAK-') + r'[A-Za-z0-9]{8,}')),
    ('硅基流动/其他 hf_ 形状', re.compile(_p('h', 'f_') + r'[A-Za-z0-9]{20,}')),
    ('GitHub token', re.compile(r'gh[pousr]_[A-Za-z0-9]{20,}')),
    ('AWS access key', re.compile(r'AKIA[0-9A-Z]{16}')),
    ('私钥文件', re.compile(r'-----BEGIN [A-Z ]*PRIVATE KEY-----')),
    ('JSON/JS 里的长串键值', re.compile(
        r'(?i)"(?:api[_-]?key|apikey|token|secret|password)"\s*[:=]\s*"[^"]{16,}"')),
)


# 这几份文件必须在扫描范围里 —— 不按扩展名抽查（`.txt 在不在` 这种断言是空的：
# 一个文件都没有的扩展名，判它「在」纯是自找的，判它「不在」又什么也没说明）。
MUST_SCAN = ('report_check.py', os.path.join('gongwen', 'provider.py'),
             os.path.join('gongwen', 'cli.py'), os.path.join('tests', '_harness.py'),
             os.path.join('preview', 'vendor', 'marked.umd.js'))


def files(root=ROOT):
    """→ 这个仓库里该扫的文件（按扩展名和目录名排掉二进制与生成物）。"""
    out = []
    for dirpath, dirnames, names in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for n in names:
            if n in SKIP_NAMES or os.path.splitext(n)[1].lower() in SKIP_EXT:
                continue
            out.append(os.path.join(dirpath, n))
    return sorted(out)


def scan(paths):
    """→ [(文件, 行号, 命中的是哪一条, 那一行的原文)]。**纯函数**，对照组也用它。"""
    hits = []
    for p in paths:
        try:
            with open(p, encoding='utf-8') as f:
                for i, line in enumerate(f, 1):
                    for name, rx in PATTERNS:
                        if rx.search(line):
                            hits.append((p, i, name, line.strip()[:120]))
                            break
        except (UnicodeDecodeError, OSError):
            continue          # 二进制或者读不动的一律跳过，不因此报红
    return hits


def default_keys(src):
    """→ 「名字像钥匙的环境变量」带了兜底常量的调用原文。

    **只挑名字像钥匙的**（`*_KEY` / `*TOKEN` / `*SECRET`…）：地址和模型名有兜底是该有的
    （没配也能跑，跑的是同一个公开接口），钥匙有兜底是这里最坏的一种错 —— 没配也能跑，
    跑的是**别人的**钥匙，而且从外面完全看不出来（老仓库就是这样跑了 20 个提交）。

    **按语法树判，不按文本判**：老仓库那个教训是要写进注释里的（「当初这里是一把真
    钥匙」），拿正则去 grep 会先命中注释和文档字符串 —— 于是要么把教训删掉，要么把断言
    关掉，两条路都不对。语法树只认真的调用。
    """
    out = []
    for node in ast.walk(ast.parse(src)):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        is_env = (node.func.attr == 'getenv'
                  or (node.func.attr == 'get' and 'environ' in ast.unparse(node.func.value)))
        if not is_env or len(node.args) < 2:
            continue
        first = node.args[0]
        # 第一个参数可能是字面量，也可能是个变量名（迁移期写成 BASE_ENV 这种），两种都认
        name = first.value if isinstance(first, ast.Constant) else ast.unparse(first)
        if not KEYISH.search(str(name)):
            continue
        v = node.args[1]
        if not (isinstance(v, ast.Constant) and v.value == ''):
            out.append(ast.unparse(node))
    return out


def main():
    t = Tally()

    print('--- 一、阳性对照：真有钥匙时扫得出来吗')
    tmp = tempfile.mkdtemp(prefix='gongwen_secret_')
    fake = os.path.join(tmp, 'leak.py')
    with open(fake, 'w', encoding='utf-8') as f:
        f.write('# 这一行是故意的假钥匙，只在临时目录里\n')
        f.write('KEY = "' + _p('s', 'k-') + 'A1b2C3d4E5f6G7h8I9j0K1l2"\n')
    got = scan([fake])
    t(bool(got) and got[0][2] == 'OpenAI/DeepSeek 风格',
      f'阳性对照被抓到了：{got[0][2] if got else "一条都没抓到 —— 这条检查根本没在判"}')
    # 这一行也得拼着写：直接写成 "api_key": "xxxx…" 的话，**这个文件自己**会被扫出来
    # （第一版就是这样，扫描器把自己扫红了 —— 那次报红是真的，只是红错了对象）。
    fake2 = os.path.join(tmp, 'leak2.json')
    with open(fake2, 'w', encoding='utf-8') as f:
        f.write('{"%s": "%s"}\n' % (_p('api', '_key'), 'x' * 32))
    t(bool(scan([fake2])), 'JSON 里那种键值对也抓得到')
    t(not scan([fake2.replace('leak2', 'nope')]), '对不上的文件当然扫不出来（对照组不是万能的）')
    os.remove(fake); os.remove(fake2); os.rmdir(tmp)

    print('--- 二、全仓扫一遍')
    path = files()
    rel = {os.path.relpath(p, ROOT) for p in path}
    t(len(path) > 20, f'扫了 {len(path)} 个文件（太少就说明排除规则把该扫的也排掉了）')
    for name in MUST_SCAN:
        t(name in rel, f'{name} 在扫描范围里')
    for name in SKIP_NAMES | {os.path.join('preview', '_page.html')}:
        t(not any(os.path.basename(p) == name for p in path), f'{name}（生成物）不在扫描范围里')
    hits = scan(path)
    for p, i, name, line in hits:
        print(f'      {os.path.relpath(p, ROOT)}:{i}  [{name}]  {line}')
    t(not hits, f'全仓 {len(path)} 个文件，明文密钥 0 处（实际 {len(hits)} 处）')

    print('--- 三、结构上不给自己留后路')
    saved = os.environ.pop('DEEPSEEK_API_KEY', None)
    try:
        t(provider.from_env().api_key == '',
          'from_env() 在没配环境变量时给空串 —— 没有「兜底钥匙」这种东西')
        t(provider.OpenAICompat('').available() is False, '空钥匙 = 不可用（不是「用默认的」）')
    finally:
        if saved is not None:
            os.environ['DEEPSEEK_API_KEY'] = saved
    # 这条判据自己也先证伪一遍：能抓到该抓的、放过该放的。
    t(default_keys('import os\nk = os.getenv("DEEPSEEK_API_KEY", "' + _p('s', 'k-') + 'real")\n'),
      '阳性对照：名字像钥匙的变量带了兜底值，看得出来')
    t(default_keys('import os\nk = os.environ.get("MY_TOKEN", "abc")\n'),
      '阳性对照：os.environ.get 那种写法也看得出来')
    t(default_keys('import os\nk = os.getenv(API_KEY_ENV, "abc")\n'),
      '阳性对照：第一个参数写成变量名也看得出来（迁移期就是这种写法）')
    t(not default_keys('import os\nk = os.getenv("DEEPSEEK_API_KEY", "")\n'),
      '阴性对照：第二参数是空串的不算')
    t(not default_keys('import os\nk = os.getenv("DEEPSEEK_API_KEY")\n'),
      '阴性对照：只给一个参数的不算')
    t(not default_keys('import os\nk = os.getenv("DEEPSEEK_BASE_URL", "https://x/v1")\n'),
      '阴性对照：**地址、模型名的兜底是应该的**，不算兜底钥匙'
      '（没配也能跑，跑的是同一个公开接口）')
    bad = []
    for p in path:
        if p.endswith('.py') and os.sep + 'gongwen' + os.sep in p:
            for call in default_keys(open(p, encoding='utf-8').read()):
                bad.append(f'{os.path.relpath(p, ROOT)}: {call}')
    t(not bad, f'gongwen/ 下没有一个像钥匙的变量带兜底值（实际 {bad}）')

    env_ex = os.path.join(ROOT, '.env.example')
    if os.path.exists(env_ex):
        body = open(env_ex, encoding='utf-8').read()
        vals = [ln.split('=', 1)[1].strip() for ln in body.splitlines()
                if '=' in ln and not ln.strip().startswith('#')]
        t(vals and all(not v or v.startswith('<') for v in vals),
          f'.env.example 里的 {len(vals)} 个值全是空的或 <占位符>，没有一个真值')
    else:
        t.skip('.env.example', '还没有这个文件')

    gi = os.path.join(ROOT, '.gitignore')
    if os.path.exists(gi):
        body = open(gi, encoding='utf-8').read()
        t('.env' in body, '.gitignore 挡住了 .env（真钥匙不该有机会进仓库）')
    else:
        t.skip('.gitignore', '还没有这个文件')
    return t.ok, t.notes


if __name__ == '__main__':
    sys.exit(main_hook(main, 'test_no_secrets：明文密钥扫描'))
