"""提示词：装出来的 system 逐字对快照，外加结构不变量。
改了提示词时用 --write 重写快照，diff 进提交记录。
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _harness import Tally, FIXTURES, load, main_hook      # noqa: E402

from gongwen import docformat, prompt                       # noqa: E402

# 范本那份假文档：学刊体，标题是**裸文本**（PDF/Word 抽出来的样子，编号是唯一还留着的
# 层级信息）。写成 Markdown 的 `## 一、引言` 反而一行都认不出来 —— 见 docformat 里
# _heading_kind 的说明，那是我第一版写错的地方。
DOC_BODY = """某市低空经济产业的空间集聚特征与形成机制

摘  要

本文以某市 347 家低空经济企业为样本，考察产业的空间集聚特征。

关键词

低空经济；空间集聚；形成机制

一、引言

低空经济是近年来各地争相布局的新兴产业方向。

二、研究设计与数据来源

本文的数据来自某市市场监督管理局的企业注册信息。

三、产业规模与空间分布

从规模看，某市低空经济产业近三年保持两位数增长。

四、结论与政策含义

本文认为，低空经济的集聚更多来自应用场景的差异。

参考文献

[1] 某某. 低空经济的产业组织特征[J]. 某某学报, 2025(3): 45-58.

附  录

附表 1 样本企业的行业分布
"""
DOC_SIZE_KB = 4.1

SNAP_GW = dict(topic='某市低空经济产业', description='',
               refs_text='某市推动低空经济高质量发展行动方案（2024—2027 年）。',
               recipient='某某市科学技术局', docs_text='', today='2026-10-10')
SNAP_EX = dict(topic='某市低空经济产业', description='模仿这篇文章写一篇',
               refs_text='（本次没有联网检索，资料来源由用户提供。）',
               recipient='某某市发展和改革委员会',
               docs_text=docformat.wrap_upload('低空经济研究报告.md', DOC_BODY,
                                               DOC_SIZE_KB),
               today='2026-10-10')

SNAPSHOTS = {'system_gw.md': SNAP_GW, 'system_exemplar.md': SNAP_EX}


def first_diff(a, b):
    """→ 第一处不同的行号与两边的原话；一样就是 None。快照红了要一眼看到差在哪。"""
    la, lb = a.splitlines(), b.splitlines()
    for i in range(max(len(la), len(lb))):
        x = la[i] if i < len(la) else '(没有这一行)'
        y = lb[i] if i < len(lb) else '(没有这一行)'
        if x != y:
            return i + 1, x, y
    return None


def main():
    t = Tally()

    if '--write' in sys.argv:
        for name, kw in SNAPSHOTS.items():
            text = prompt.report_system(**kw)
            with open(os.path.join(FIXTURES, name), 'w', encoding='utf-8') as f:
                f.write(text)
            print(f'  重写 fixtures/{name}（{len(text)} 字）')
        print('快照已重写。**看一眼 git diff 再提交** —— 这是提示词改动的评审记录。')
        return True, []

    print('--- 一、装出来的 system 逐字对快照')
    live = {}
    for name, kw in SNAPSHOTS.items():
        live[name] = prompt.report_system(**kw)
        want = load(name, t, '没有这份快照（跑 --write 生成）')
        if not want:
            continue
        d = first_diff(live[name], want)
        t(d is None, f'{name} 逐字一致（{len(want)} 字）'
                     + ('' if d is None else f'；第 {d[0]} 行：\n       现在 {d[1]!r}\n'
                                             f'       快照 {d[2]!r}'))

    print('--- 二、槽都填满了，而且模板里不许再有地域示例')
    for name, text in live.items():
        t(not prompt.slots(text), f'{name}：装完一个槽都不剩')
        t('{{' not in text, f'{name}：没有残留的双花括号')
    joined = '\n'.join(prompt.load(n) for n in prompt.TEMPLATES)
    t('重庆' not in joined, '三份模板里没有「重庆」（早先的示例已中性化）')
    t('某市' in joined, '示例已经改成「某市」这类中性写法')

    print('--- 三、上传文档必须进 system（搬过来时漏过这一句）')
    ex = live['system_exemplar.md']
    t('某市低空经济产业的空间集聚特征与形成机制' in ex,
      '范本正文在 system 里（不然模型只能看到骨架、看不到范本）')
    t(prompt.DOCS_HEAD in ex, f'system 里有「{prompt.DOCS_HEAD}」这一节')
    t(docformat.wrap_upload('x.md', 'y')[:6] in ex, '传进来的是带标记的原文，不是摘要')
    t(prompt.DOCS_HEAD not in live['system_gw.md'], '没给上传文档时没有这一节')
    # 顺序：上传文档接在 --refs 的资料**后面**（和 _report_refs 里一致）
    both = prompt.refs_block('参考资料正文', '上传文档正文')
    t(both.index('参考资料正文') < both.index(prompt.DOCS_HEAD)
      and both.index(prompt.DOCS_HEAD) < both.index('上传文档正文'),
      '两份都有时：资料在前、上传文档在后')

    print('--- 四、主送机关两态')
    with_to = prompt.report_system('主题', recipient='某某市科学技术局')
    without = prompt.report_system('主题')
    t('逐字照抄' in with_to and '某某市科学技术局' in with_to, '给了：要求逐字照抄')
    t('整行不写' in without and '逐字照抄' not in without, '没给：整行不写，不许自己编')
    t(without.count('某某市') == 0, '没给的时候 system 里不出现任何机关名')

    print('--- 五、今天：给了就用给的，没给取本机当天')
    t('2026年10月10日' in prompt.report_system('主题', today='2026-10-10'),
      'ISO 写法（2026-10-10）转成中文写法')
    t('2026年10月10日' in prompt.report_system('主题', today='2026年10月10日'),
      '已经是中文写法就原样用')
    lt = time.localtime()
    local = f'{lt.tm_year}年{lt.tm_mon}月{lt.tm_mday}日'
    t(local in prompt.report_system('主题'), f'没给就取本机当天（{local}）')
    jan = prompt.report_system('主题', today='2026-01-03')
    t('2026年1月3日' in jan and '01月' not in jan and '03日' not in jan,
      '月日不补虚位（标准 7.3.5.4）：1 月 3 日写「1月3日」，不写「01月03日」')

    print('--- 六、参考资料一节的出现条件')
    t('## 参考资料' not in prompt.report_system('主题'), '什么都没有：不加这一节')
    t('## 参考资料' in prompt.report_system('主题', refs_text='资料'),
      '只给 --refs：加上')
    t('## 参考资料' in prompt.report_system('主题', docs_text='上传文档'),
      '只给上传文档：也加（它同样是素材）')

    print('--- 七、超长文档：裁的时候头尾都留')
    for n, want_cut in ((prompt.DOCS_MAX, False), (prompt.DOCS_MAX + 1, True)):
        body = '甲' * n
        got = prompt.trim_docs(body)
        t(('（中间省略约' in got) == want_cut,
          f'{n} 字：{"裁" if want_cut else "原样"}（阈值 {prompt.DOCS_MAX}）')
    big = '头' * 20000 + '中' * 30000 + '尾' * 20000
    cut = prompt.trim_docs(big)
    t(cut.startswith('头') and cut.endswith('尾'), '裁过的文档：开头和结尾都在')
    t(len(cut) < len(big), '确实短了')
    t('省略约 30000 字' in cut, '写明了省掉多少字')
    # 只留头的话，正好会把「结尾有没有参考文献」这一条判断砍掉 —— 那是裁法的由来
    t('尾' * 100 in cut, '结尾那一段仍有一大截可用')

    print('--- 八、参数闸门：边界值恰好通过')
    t(prompt.validate('主题') == '', '正常主题：过')
    t(prompt.validate('') != '' and prompt.validate('   ') != '', '空主题：不过（只有空格也不过）')
    t(prompt.validate('主' * prompt.TOPIC_MAX) == '', f'主题 {prompt.TOPIC_MAX} 字：过')
    t(prompt.validate('主' * (prompt.TOPIC_MAX + 1)) != '', f'主题 {prompt.TOPIC_MAX + 1} 字：不过')
    t(prompt.validate('主题', '说' * prompt.DESC_MAX) == '', f'说明 {prompt.DESC_MAX} 字：过')
    t(prompt.validate('主题', '说' * (prompt.DESC_MAX + 1)) != '',
      f'说明 {prompt.DESC_MAX + 1} 字：不过')
    t(prompt.validate('主题', '', '局' * prompt.RECIPIENT_MAX) == '',
      f'主送机关 {prompt.RECIPIENT_MAX} 字：过')
    t(prompt.validate('主题', '', '局' * (prompt.RECIPIENT_MAX + 1)) != '',
      f'主送机关 {prompt.RECIPIENT_MAX + 1} 字：不过')

    print('--- 九、骨架三条路（模板槽必须填得满）')
    wrapped = docformat.wrap_upload('范本.md', DOC_BODY)
    s1, f1 = prompt.report_structure('主题', '', '')
    s2, f2 = prompt.report_structure('主题', '模仿这篇文章写一篇', wrapped)
    s3, f3 = prompt.report_structure('主题', '模仿这篇文章写一篇', '')
    s4, f4 = prompt.report_structure('主题', '模仿这篇文章写一篇',
                                     '一\n二\n三\n')     # 有附件但抽不出标题
    t(f1 == 'gw' and '一、' in s1, '没提范本：装公文骨架')
    t(f2 == 'exemplar' and '参考文献' in s2, '提了范本且有附件：装范本骨架')
    t(f3 == 'gw', '提了范本但没附件：退回公文骨架（认了就是「没有骨架」）')
    t(f4 == 'gw', '有附件但一行编号标题都抽不出来：同样退回公文骨架')
    return t.ok, t.notes


if __name__ == '__main__':
    sys.exit(main_hook(main, 'test_prompt：提示词（逐字快照）'))
