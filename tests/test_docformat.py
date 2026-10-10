"""上传文档那一层：标记串往返、闸门、体例抽取。

三件事分开验：

1. **标记串**（`wrap_upload` / `parse_uploads` / `join_uploads`）是唯一定义处，往返必须
   一字不差 —— 报告旁边那份 `_refs.md`、提示词里的文件名、检查时的来源核对，都走它。
2. **闸门**（`wants_doc_format`）：判不准就不认（fail-closed）。**漏判只是退回公文格式，
   误判会把别人的骨架套到报告上**，所以「不认」的那些说法是故意不认的，下面逐个写明白。
3. **体例抽取**（`describe_format`）：抽出来的只是「提示」，措辞里就写着「以文档原文
   为准」。它认的是 PDF/Word 抽出来的**裸标题**，Markdown 的 `## 一、引言` 一行都认不
   出来 —— 这是踩过的坑，下面有一条专门钉着。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _harness import Tally, main_hook                        # noqa: E402

from gongwen import docformat as D                           # noqa: E402

BARE = ('某市低空经济产业的空间集聚\n\n摘  要\n\n本文以……\n\n关键词\n\n低空经济\n\n'
        '一、引言\n\n正文。\n\n二、研究设计\n\n正文。\n\n参考文献\n\n[1] 某某.\n')
W_UP = ('表 1 分析框架\n\n| 维度 | 指标 |\n| --- | --- |\n| 规模 | 产值 |\n\n'
        '注：数据来源为公开报道。\n\n一、引言\n\n正文。\n\n二、结论\n\n正文。\n')
W_DOWN = ('一、引言\n\n正文。\n\n| a | b |\n| --- | --- |\n\n表 1 分析框架\n\n'
          '二、结论\n\n正文。\n')


def main():
    t = Tally()

    print('--- 一、标记串：往返一字不差')
    one = D.wrap_upload('甲.md', '正文一。')
    t('甲.md' in one and '正文一。' in one and '内容如下' in one, f'标记串长这样：{one.splitlines()[0]}')
    t(D.wrap_upload('甲.md', 'x', 4.1).count('4.1 KB') == 1, '给了 KB 就写进标记行')
    t('KB' not in D.wrap_upload('甲.md', 'x'), '没给 KB 就不写（不编一个数）')
    back = D.parse_uploads(one)
    t(back == [('甲.md', '正文一。')], f'单份往返：{back}')
    many = D.join_uploads([('甲.md', '正文一。'), ('乙.md', '正文二。', 3.5)])
    t(many == D.wrap_upload('甲.md', '正文一。') + D.wrap_upload('乙.md', '正文二。', 3.5),
      'join_uploads 就是逐份拼 wrap_upload（同一个定义处）')
    back2 = D.parse_uploads(many)
    t(back2 == [('甲.md', '正文一。'), ('乙.md', '正文二。')], f'两份往返、顺序不变：{back2}')
    t(D.parse_uploads('') == [] and D.parse_uploads('没有标记的正文') == [],
      '空串、没有标记的文本：都返回空表（不抛）')
    t(D.filenames(many) == ['甲.md', '乙.md'], f'文件名抽得出来：{D.filenames(many)}')
    t(D.filenames('没有标记') == [], '没有标记时文件名是空的')

    print('--- 二、闸门：认的说法')
    doc = D.wrap_upload('去年那份.md', BARE)
    for s in ('模仿这篇文章写一篇', '按照这份文档的格式来写', '格式参考上传的文档',
              '请模仿附件里的体例', '仿照我上传的文件的行文风格'):
        t(D.wants_doc_format(s, doc), f'认：{s}')
    print('--- 三、闸门：不认的说法（**故意不认**，fail-closed）')
    for s, why in (
            ('写一份行业分析报告', '没提格式'),
            ('格式随便', '没有文档指代'),
            ('不要模仿这篇文章，按公文格式写', '否定了（否定词在动词前）'),
            ('按我上传文档的格式写，文档只是素材', '把文档降格成了素材（否定词在配对段之后）'),
            ('按上传文档的格式写，这份文件只作素材', '同上，「只作」也算否定'),
            ('参考这份文档里的数据', '提的是内容不是格式（「参考」故意不收）'),
            ('以附件为准', '说的是什么「为准」——可能指数据，判不准就不认'),
            ('照着我上传的报告的格式写', '「上传的报告」这种说法不在文档指代那一组里'),
    ):
        t(not D.wants_doc_format(s, doc), f'不认：{s} —— {why}')
    # 边界记在案：否定词离配对的那一段超过 8 个字（「但那份文档只是素材」）就不看了，
    # 闸门会开。判据原样搬自老实现（交叉验证逐条等价），这一处不改 —— 改了就不再是
    # 同一把尺子，而且这是**已知**的边界，不是意外。
    t(D.wants_doc_format('按照我上传文档的格式写，但那份文档只是素材', doc),
      '**已知边界**（不改，只记着）：否定词隔了 9 个字以上时闸门仍会开')
    t(not D.wants_doc_format('模仿这篇文章写一篇', ''), '没有附件：不认（认了就是「没有骨架」）')
    t(not D.wants_doc_format('', doc), '没有补充说明：不认')
    t(not D.wants_doc_format('按公文格式写。我上传了文档', doc),
      '跨句不算（在别的小句里提到文档，不能凑出格式要求）')

    print('--- 四、体例抽取：裸标题认得，Markdown 井号标题一行都认不出')
    got = D.describe_format(doc)
    t('章节骨架' in got and '一、引言' in got and '参考文献' in got, '裸标题文档抽得出骨架')
    t('篇长：约' in got, '写了篇长量级')
    t('以文档原文为准' in got, '措辞里就写着「自动识别、以原文为准」（不把它说成权威的）')
    t('开篇有' in got and '摘  要' in got, '开篇的体例认出来了')
    t('结尾有' in D.describe_format(BARE), '结尾的体例认出来了（不含上传标记的裸文本）')
    # 同一个坑记在案：拼上「[用户上传了文件…]」和分隔行之后，尾部四分之一被它们占掉，
    # 「结尾有」就不列了。**骨架里仍然有「参考文献」这一行** —— 那一行才是换骨架真正
    # 要用的东西，这个只是提示里的锦上添花。
    t('结尾有' not in got,
      '**已知边界**：带上传标记时分隔行挤掉尾部四分之一，「结尾有」不列（骨架不受影响）')
    md = '# 标题\n\n## 一、引言\n\n正文。\n\n## 二、结论\n\n正文。\n'
    t(D.describe_format(md) == '',
      'Markdown 的 ## 标题**一行都认不出来**（认的是 PDF/Word 抽出来的裸文本）'
      '—— 上传 .md 时要注意这一点')
    t(D.describe_format('') == '' and D.describe_format('   ') == '',
      '空文档抽不出东西（调用方据此退回公文骨架）')
    t(D.describe_format('通篇没有编号标题的一段话。' * 3) == '',
      '有正文但没有编号标题：同样抽不出（表格导出的 xlsx 就是这样）')

    print('--- 五、体例抽取：表格、截断、长短')
    up = D.describe_format(D.wrap_upload('a.md', W_UP))
    t('表格 1 张' in up and '上方' in up, '表题在表格上方：认出来了')
    down = D.describe_format(D.wrap_upload('a.md', W_DOWN))
    t('表格 1 张' in down and '下方' in down, '表题在表格下方：也认出来了')
    trunc = D.describe_format(D.wrap_upload('a.md', BARE + D.TRUNC_MARK + '……'))
    t('被截断' in trunc and '未能识别' in trunc,
      '带截断标记：如实说结尾那一部分没识别到（不假装知道有没有参考文献）')
    short = D.describe_format(doc, max_chars=40)
    t(len(short) < len(got) and '…（略）' in short, f'max_chars 生效（{len(short)} < {len(got)}）')
    t(len(D.describe_format(doc)) > 0, '默认不截断（正文里那份默认值）')
    return t.ok, t.notes


if __name__ == '__main__':
    sys.exit(main_hook(main, 'test_docformat：上传文档体例'))
