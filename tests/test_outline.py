"""分阶段报告：目录收敛、章节切分/替换、CLI 的目录/改稿入口。不联网。"""
import inspect
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _harness import Tally, main_hook, run_cli                  # noqa: E402

from gongwen import generate as G                               # noqa: E402
from gongwen import outline                                    # noqa: E402

FAKE_OUTLINE = {
    'title': '关于某市低空经济产业的报告',
    'sections': [
        {'title': '一、摘要', 'level': 1,
         'brief': '背景 + 主要结论 + 三条建议', 'words': 600},
        {'title': '二、发展现状', 'level': 1,
         'brief': '规模、增速、区域分布', 'words': 1200},
        {'title': '（一）产业规模', 'level': 2,
         'brief': '用统计局的规模数据', 'words': 600},
        {'title': '三、对策建议', 'level': 1,
         'brief': '三条具体措施', 'words': 800},
    ],
}

REPORT = """# 关于某市低空经济产业的报告

## 一、摘要
摘要里的原始内容。

## 二、发展现状
发展现状的原始内容。

### （一）产业规模
产业规模的原始内容。

## 三、对策建议
对策建议的原始内容。

## 数据来源
参考资料里的来源。
"""

FAKE_SECTION = """## 二、发展现状
修改后的发展现状：规模继续扩大。

### （一）产业规模
修改后的产业规模：用最新数据说明。
"""


class Fake:
    """假的 provider：只把预设文本吐回来。"""

    name = 'fake'

    def __init__(self, text):
        self.text = text

    def available(self):
        return True

    def complete(self, system, user, on_delta=None):
        if on_delta:
            on_delta(self.text, self.text)
        return self.text


def main():
    t = Tally()

    print('--- 一、目录收敛')
    ol, warns = outline.normalize_outline(FAKE_OUTLINE, 'gw', '某市低空经济产业')
    t(len(ol['sections']) == 5, f'gw 补上「数据来源」后 5 节（实际 {len(ol["sections"])}）')
    t(any('数据来源' in s['title'] for s in ol['sections']), '确实补了数据来源')
    t(any('数据来源' in w for w in warns), '补数据来源给了提示')
    t(all(s['level'] in (1, 2) for s in ol['sections']), 'level 收敛成 1/2')
    t(all(s.get('id') for s in ol['sections']), '每节都分配了 id')
    t(ol['title'].startswith('关于'), '标题保留')
    try:
        outline.normalize_outline({'sections': []}, 'gw', 'x')
        t(False, '空目录必须报错 —— 没报')
    except ValueError:
        t(True, '空目录报 ValueError')
    bad = {'sections': [{'title': '（一）只有小节', 'level': 2}]}
    ol2, _ = outline.normalize_outline(bad, 'gw', 'x')
    t(ol2['sections'][0]['level'] == 1, '全是二级时把第一节提为一级')
    huge = {'sections': [
        {'title': '一、甲', 'level': 1, 'words': 3000},
        {'title': '二、乙', 'level': 1, 'words': 3000},
        {'title': '三、丙', 'level': 1, 'words': 3000},
        {'title': '四、丁', 'level': 1, 'words': 3000},
        {'title': '五、戊', 'level': 1, 'words': 3000},
        {'title': '六、己', 'level': 1, 'words': 3000},
    ]}
    ol3, w3 = outline.normalize_outline(huge, 'gw', 'x')
    t(sum(s['words'] for s in ol3['sections']) <= 16000, '超长字数被压到 16000 以内')
    t(any('16000' in w for w in w3) or any('14000' in w for w in w3), '压缩给了提示')

    print('--- 二、结构块')
    sb = outline.structure_block(ol)
    t('## 一、摘要' in sb and '写作说明：背景' in sb, '结构块带章节和写作说明')
    t('## 数据来源' in sb, '结构块带数据来源')
    t('最多不要超过 16000 字' in sb, '结构块带全篇上限')

    print('--- 三、章节切分 / 替换')
    secs = outline.parse_sections(REPORT)
    t([s['title'] for s in secs] ==
      ['一、摘要', '二、发展现状', '（一）产业规模', '三、对策建议', '数据来源'],
      f'切出 5 节：{[s["title"] for s in secs]}')
    target = [s for s in secs if s['title'] == '二、发展现状'][0]
    t('（一）产业规模' in target['text'], '一级章节把子节包进来')
    new_md, ok, _w = outline.replace_section(REPORT, target, FAKE_SECTION)
    t(ok and '修改后的发展现状' in new_md, '正常替换写进去了')
    t('摘要里的原始内容' in new_md and '对策建议的原始内容' in new_md,
      '替换没有误伤其他章节')
    short_md, ok2, w2 = outline.replace_section(REPORT, target, '太短')
    t(not ok2 and short_md == REPORT and w2, '太短的修改退回原文并给提示')
    wrong = ('## 改了个标题\n这一段内容足够长，足够通过长度检查，但是标题和原来不一致，'
             '应该被换回原标题，并保留这段正文。再多写几句确保超过五十个字。')
    wrong_md, ok3, _ = outline.replace_section(REPORT, target, wrong)
    t(ok3 and '## 二、发展现状' in wrong_md, '标题不一致时换回原标题')

    print('--- 四、generate_outline / revise_section')
    fake = Fake(json.dumps(FAKE_OUTLINE, ensure_ascii=False))
    got, gwarns, raw, fmt = G.generate_outline('某市低空经济产业', fake,
                                               refs_text='参考资料 123')
    t(fmt == 'gw' and len(got['sections']) == 5, 'generate_outline 返回规范目录')
    t(json.loads(raw)['sections'][0]['title'] == '一、摘要',
      '目录生成返回的原始 JSON 可解析')
    fake2 = Fake(FAKE_SECTION)
    md, ok, warn, _raw = G.revise_section(
        '某市低空经济产业', fake2, got, target, REPORT, '补数据')
    t(ok and '修改后的发展现状' in md, 'revise_section 替换成功')
    t('摘要里的原始内容' in md, 'revise_section 没误伤摘要')

    print('--- 五、outline 只依赖标准库、不联网')
    src = inspect.getsource(outline)
    net = re.findall(r'^\s*(?:import|from)\s+(httpx|urllib|requests|socket|http)\b',
                     src, re.M)
    t(not net, f'outline.py 没有网络库 import（{net or "无"}）')

    print('--- 六、CLI：目录/改稿的零密钥入口')
    code, out, err = run_cli('--outline', '--print-system', '--topic', '某市低空经济')
    t(code == 0, f'--outline --print-system 退出码 {code}')
    t('只输出 JSON' in out and '报告主题：某市低空经济' in out,
      '打出了目录提示词和主题')
    t('===== user =====' in out, 'system 和 user 都打出来了')

    saved = os.environ.pop('DEEPSEEK_API_KEY', None)
    try:
        code, out, err = run_cli('--outline', '--topic', '某市低空经济')
        t(code == 2 and '没配 key' in err, f'没 key 时出目录退出码 {code}')
    finally:
        if saved is not None:
            os.environ['DEEPSEEK_API_KEY'] = saved

    code, out, err = run_cli('--revise', 'fixtures/golden_gw.md', '--section', '0',
                             '--instruction', '改短一点', '--print-system')
    t(code == 0 and '正在修改' in out and '修改要求：改短一点' in out,
      f'改稿 --print-system 退出码 {code}')
    code, out, err = run_cli('--revise', 'fixtures/golden_gw.md', '--section', '999',
                             '--instruction', 'x', '--print-system')
    t(code == 2 and '找不到这一节' in err, f'越界章节退出码 {code}')
    code, out, err = run_cli('--revise', 'fixtures/golden_gw.md',
                             '--instruction', 'x', '--print-system')
    t(code == 2 and '要指定' in err, f'没给章节也没给 --all 退出码 {code}')
    code, out, err = run_cli('--gen', '--topic', 'x', '--outline-file', 'nope.json',
                             '--print-system')
    t(code == 2 and '参数不对' in err, f'坏目录文件退出码 {code}')

    return t.ok, t.notes


if __name__ == '__main__':
    sys.exit(main_hook(main, 'test_outline：分阶段目录/改稿（不联网）'))
