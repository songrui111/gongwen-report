"""分阶段报告：出目录、收敛目录、切分/替换正文章节。

**为什么单独一层。** 原来只有「一次生成整篇」，用户看不到模型准备写哪几章、
也没法在动笔前补要求；成稿后改一节要整篇重来。这一层把报告拆成
「目录 → 正文 → 按节改」三步，目录和章节操作都是纯函数，不碰网络、不碰磁盘。

只依赖标准库。提示词里的「参考资料」由调用方通过 `--refs` / `--docs` 传入，
本模块不联网。
"""
import json
import re

MAX_SECTIONS = 40
MAX_TITLE = 80
MAX_BRIEF = 400
MAX_WORDS = 3000
MIN_SECTION_CHARS = 50


# ==========================================================================
# 出目录
# ==========================================================================

_SYSTEM_GW = """你是资深行业研究员，现在只做一件事：为一份行业分析报告拟定目录。

**只输出 JSON，不要写正文，不要解释。**

输出格式：
{
  "title": "关于……的报告",
  "sections": [
    {"title": "一、摘要", "level": 1, "brief": "这一节写什么、用哪些数据、要回答什么问题", "words": 600},
    {"title": "（一）行业界定与产业链构成", "level": 2, "brief": "……", "words": 400}
  ]
}

要求：
1. level=1 是一级章节，level=2 是二级小节；按正文顺序平铺，不要嵌套。
2. **一级章节的标题和顺序必须遵守下面给的骨架**（可以按主题微调措辞，但不能增删）；
   二级小节可以按行业特点调整、合并或拆分。
3. 每一节都要写 `brief`：这一节写什么、用哪些资料、要回答什么问题、注意什么。
   写作说明是给下一步写正文看的，要具体，不要写成「介绍行业发展情况」这种空话。
4. `words` 是这一节的目标字数（整数）。全篇合计 10000 到 14000 字；
   摘要 500～700，一级章节 1200～2600，二级小节 400～900。
5. 标题不要带 Markdown 的 `#`，编号直接写在标题里（如「一、摘要」「（一）行业界定」）。
6. 最后一节是「数据来源」时，说明只列参考资料里真实出现过的来源。
7. 不要写发文机关署名、成文日期、抄送机关、印发机关。
8. 资料只来自下面给的参考资料；**不要联网，不要自己编数据或来源**。"""

_SYSTEM_EXEMPLAR = """你是资深行业研究员。用户给了一份文档，本次报告的**章节骨架必须照它来**。
你只做一件事：把范本的骨架整理成可编辑的目录。

**只输出 JSON，不要写正文，不要解释。**

输出格式：
{
  "title": "……",
  "sections": [
    {"title": "一、……", "level": 1, "brief": "这一节写什么、用哪些资料", "words": 600}
  ]
}

要求：
1. 一级/二级标题、顺序、开篇和结尾**严格照范本**；范本没有的章节不要加。
2. 范本里识别出来的编号写法照原样保留（如「第一章」「1.」「（一）」）。
3. 每一节写 `brief`：这一节写什么、用哪些资料、要回答什么问题。
4. `words` 是目标字数，按范本的篇幅量级分配，合计和范本相当。
5. 标题不要带 Markdown 的 `#`。
6. 不要写发文机关署名、成文日期、抄送机关、印发机关。
7. 资料只来自下面给的参考资料；**不要联网，不要自己编数据或来源**。"""


def outline_messages(topic, description='', refs_text='', docs_text='',
                     recipient='', today=''):
    """→ (system, user, fmt)。`fmt` 是骨架标签 gw/exemplar。

    骨架直接复用 `prompt.report_structure`：默认公文体例，或用户上传范本那一套。
    """
    from . import prompt
    structure, fmt = prompt.report_structure(topic, description, docs_text)
    system = _SYSTEM_EXEMPLAR if fmt == 'exemplar' else _SYSTEM_GW
    lines = [f'报告主题：{topic}']
    if description:
        lines.append(f'补充说明：{description}')
    if recipient:
        lines.append(f'主送机关：{recipient}')
    lines.append(f'今天：{prompt.today_text(today)}')
    lines.append('')
    lines.append('下面是必须遵守的报告骨架：')
    lines.append(structure.strip())
    refs = prompt.refs_block(refs_text, docs_text)
    if refs:
        lines.append('')
        lines.append('## 参考资料（只用来判断每一节该写什么，不要在这里写正文）')
        lines.append(refs.strip())
    return system, '\n'.join(lines), fmt


# ==========================================================================
# 收敛目录
# ==========================================================================

_NUM2_RE = re.compile(r'^\s*(?:（\s*[一二三四五六七八九十0-9]+\s*）|'
                      r'\(\s*[一二三四五六七八九十0-9]+\s*\)|'
                      r'第\s*[一二三四五六七八九十0-9]+\s*[节章])')
_TITLE_STRIP_RE = re.compile(r'^\s*#{1,6}\s*')


def _clean_title(s):
    """标题去掉 Markdown #、压空白、截长。"""
    s = _TITLE_STRIP_RE.sub('', str(s or '')).strip()
    s = re.sub(r'\s+', ' ', s)
    return s[:MAX_TITLE]


def _infer_level(title, raw_level=None):
    """level 只认 1/2；没给或给了怪值就按标题编号推断。"""
    try:
        lv = int(raw_level)
        if lv in (1, 2):
            return lv
    except (TypeError, ValueError):
        pass
    return 2 if _NUM2_RE.match(title or '') else 1


def _coerce_words(v, level):
    try:
        n = int(float(v))
    except (TypeError, ValueError):
        n = 1200 if level == 1 else 500
    return max(100, min(MAX_WORDS, n))


def normalize_outline(raw, fmt='gw', topic=''):
    """模型给的 JSON → 规范目录。返回 (outline, warnings)。

    规范形式：
        {"title": "...", "sections": [
            {"id":"s1","title":"一、摘要","level":1,"brief":"...","words":600}
        ]}
    """
    warnings = []
    if not isinstance(raw, dict):
        raise ValueError('目录不是 JSON 对象')
    raw_sections = raw.get('sections') or raw.get('outline') or raw.get('chapters')
    if not isinstance(raw_sections, list) or not raw_sections:
        raise ValueError('目录里没有任何章节')

    title = _clean_title(raw.get('title'))
    if not title:
        title = f'关于{topic}的报告' if topic else '行业分析报告'

    out, seen = [], set()
    for x in raw_sections:
        if isinstance(x, str):
            x = {'title': x}
        if not isinstance(x, dict):
            continue
        t = _clean_title(x.get('title'))
        if not t:
            continue
        lv = _infer_level(t, x.get('level'))
        key = (lv, t)
        if key in seen:
            warnings.append(f'目录里有重复章节「{t}」，已去掉后一条')
            continue
        seen.add(key)
        brief = re.sub(r'\s+', ' ', str(x.get('brief') or '')).strip()[:MAX_BRIEF]
        out.append({
            'title': t,
            'level': lv,
            'brief': brief,
            'words': _coerce_words(x.get('words'), lv),
        })
        if len(out) >= MAX_SECTIONS:
            warnings.append(f'目录超过 {MAX_SECTIONS} 节，后面的已截掉')
            break

    if not out:
        raise ValueError('目录里没有可用的章节标题')

    if all(s['level'] == 2 for s in out):
        out[0]['level'] = 1
        warnings.append('目录没有一级章节，已把第一节提为一级')

    if fmt == 'gw' and not any('数据来源' in s['title'] for s in out):
        out.append({
            'title': '数据来源',
            'level': 1,
            'brief': '逐条列出本报告实际用到的来源；只列参考资料里真实出现过的，'
                     '没有就写「本报告未使用外部资料」。',
            'words': 400,
        })
        warnings.append('目录里缺少「数据来源」一节，已自动补上')

    total = sum(s['words'] for s in out)
    if total > 16000:
        scale = 14000 / total
        for s in out:
            s['words'] = max(100, int(s['words'] * scale))
        warnings.append(f'目标字数合计 {total} 字，已按比例压到 14000 字以内')
    elif total < 8000:
        warnings.append(f'目标字数合计只有 {total} 字，偏少；可以加大章节的字数')

    for i, s in enumerate(out, 1):
        s['id'] = f's{i}'
    return {'title': title, 'sections': out}, warnings


def parse_json(text):
    """从模型回复里取 JSON。模型经常裹 markdown 代码块，前后再加句话。"""
    s = (text or '').strip()
    m = re.match(r'^\s*```[a-zA-Z0-9_-]*\s*\n(.*?)\n\s*```\s*$', s, re.S)
    if m:
        s = m.group(1).strip()
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        i, j = s.find('{'), s.rfind('}')
        if i >= 0 and j > i:
            return json.loads(s[i:j + 1])
        raise


# ==========================================================================
# 目录 → 正文提示词的 structure 槽
# ==========================================================================

def structure_block(outline):
    """规范目录 → 塞进 report_template 的 `structure` 槽。

    **这里的话要说得硬。** 用户已经确认过目录，模型再自行增删章节，
    用户看到的就和确认的不一样了。
    """
    title = _clean_title(outline.get('title')) or '行业分析报告'
    lines = [
        '## 报告结构（本次按用户确认的目录写）',
        '',
        f'**标题**：单独一行、一级标题（Markdown 的 `#`），逐字写成：{title}',
        '',
        '**章节必须严格按下面的顺序和标题写**：不得增删章节、不得改写章节标题、'
        '不得调换顺序。每节下面的「写作说明」和「目标字数」是本次的具体要求，必须照办。',
        '',
    ]
    for s in outline.get('sections') or []:
        lv = 2 if int(s.get('level') or 1) == 2 else 1
        mark = '###' if lv == 2 else '##'
        lines.append(f'{mark} {s.get("title") or ""}'.rstrip())
        if s.get('brief'):
            lines.append(f'写作说明：{s["brief"]}')
        if s.get('words'):
            lines.append(f'目标字数：约 {s["words"]} 字')
        lines.append('')
    total = sum(int(s.get('words') or 0)
                for s in (outline.get('sections') or []))
    if total:
        lines.append(f'全篇合计目标约 {total} 字，最多不要超过 16000 字。')
    lines.append('写到最后一节就结束。**不要写**发文机关署名、成文日期、抄送机关、'
                 '印发机关和印发日期 —— 署名和成文日期由程序按标准排。')
    return '\n'.join(lines)


# ==========================================================================
# 正文切分 / 按节替换
# ==========================================================================

_HEAD_RE = re.compile(r'^(#{1,6})\s+(.+?)\s*$')
_NUM_PREFIX_RE = re.compile(
    r'^\s*(?:第\s*[一二三四五六七八九十百千0-9]+\s*[章节篇部分讲]|'
    r'[一二三四五六七八九十]+\s*[、．.]|'
    r'（\s*[一二三四五六七八九十0-9]+\s*）|'
    r'\(\s*[一二三四五六七八九十0-9]+\s*\)|'
    r'\d+(?:\.\d+)*\s*[、．.]?)\s*')


def title_key(s):
    """比较标题用：去掉编号、空白和标点，只留文字。"""
    s = _TITLE_STRIP_RE.sub('', str(s or ''))
    s = _NUM_PREFIX_RE.sub('', s)
    return re.sub(r'[\s　:：、，,。.；;]+', '', s)


def parse_sections(markdown):
    """按 `##` / `###` 切章节。返回 [{index, level, title, start, end, text}]。

    `start` 是标题行行号，`end` 是本节结束位置（下一个同级或更高级标题之前）。
    `#` 一级标题（报告标题）不进列表；`####` 及更深也不切。
    """
    lines = (markdown or '').splitlines()
    heads = []
    for i, ln in enumerate(lines):
        m = _HEAD_RE.match(ln)
        if not m:
            continue
        n = len(m.group(1))
        if n not in (2, 3):
            continue
        heads.append((i, n - 1, m.group(2).strip()))

    out = []
    for k, (i, lv, title) in enumerate(heads):
        end = len(lines)
        for j, lv2, _t in heads[k + 1:]:
            if lv2 <= lv:
                end = j
                break
        out.append({
            'index': len(out),
            'level': lv,
            'title': title,
            'start': i,
            'end': end,
            'text': '\n'.join(lines[i:end]).strip('\n'),
        })
    return out


def public_sections(sections):
    """给调用方/前端的章节列表（不带正文）。"""
    return [{'index': s['index'], 'level': s['level'], 'title': s['title']}
            for s in sections]


def find_section(sections, index=None, title=''):
    """按 index 找；index 不合法再按标题文字找。找不到返回 None。"""
    if isinstance(index, int) and 0 <= index < len(sections):
        return sections[index]
    key = title_key(title)
    if key:
        for s in sections:
            if title_key(s['title']) == key:
                return s
    return None


def outline_from_sections(markdown, topic=''):
    """没有目录文件时，从正文里反推一个最小目录（只用来给改稿提示词当上下文）。"""
    secs = parse_sections(markdown)
    return {
        'title': topic or '',
        'sections': [{'title': s['title'], 'level': s['level'],
                      'brief': '', 'words': 0} for s in secs],
    }


_FENCE_RE = re.compile(r'^\s*```[a-zA-Z0-9_-]*\s*\n(.*?)\n\s*```\s*$', re.S)


def _strip_fence(text):
    """模型爱把 markdown 裹在代码块里。"""
    s = (text or '').strip()
    m = _FENCE_RE.match(s)
    return m.group(1).strip() if m else s


def replace_section(markdown, section, new_text):
    """把 section 那一段替换成 new_text。返回 (新全文, ok, 警告)。

    标题必须对得上；对不上就用原标题 + 模型给的新正文（不把标题改掉）。
    """
    body = _strip_fence(new_text)
    if not body:
        return markdown, False, '模型没有返回修改后的内容，已保留原文'
    if len(body) < MIN_SECTION_CHARS:
        return markdown, False, f'修改后的这一节只有 {len(body)} 字，太短，已保留原文'

    first = body.splitlines()[0].strip()
    want = '#' * (section['level'] + 1)
    if not re.match(r'^#{1,6}\s+', first):
        body = f'{want} {section["title"]}\n\n{body}'
    else:
        got = re.sub(r'^#{1,6}\s+', '', first).strip()
        if title_key(got) != title_key(section['title']):
            rest = '\n'.join(body.splitlines()[1:]).lstrip('\n')
            body = f'{want} {section["title"]}\n\n{rest}'

    lines = (markdown or '').splitlines()
    out = lines[:section['start']] + body.splitlines() + lines[section['end']:]
    s = '\n'.join(out)
    s = re.sub(r'\n{4,}', '\n\n\n', s)
    return s, True, ''


# ==========================================================================
# 修改提示词
# ==========================================================================

_SECTION_SYSTEM = """你是资深行业研究员，正在修改一份行业分析报告中的**一节**。

只输出修改后的这一节 Markdown，不要输出其他章节，不要解释，不要写代码块围栏。
第一行必须是这一节原来的标题，一个字都不要改。
这一节之外的内容一个字都不要写。
保留这一节里没有被要求改动的内容；用户的修改要求优先。
资料只能来自参考资料；参考资料没有的，不写，也不要编来源，不要联网。"""

_REVISE_ALL_SYSTEM = """你是资深行业研究员，正在按用户要求修改一整份行业分析报告。

输出修改后的**完整报告** Markdown，不要解释，不要写代码块围栏。
保持原来的标题和章节结构不变；用户没要求改动的章节尽量保持原样。
资料只能来自参考资料；参考资料没有的，不写，也不要编来源，不要联网。"""


def _outline_lines(outline):
    return '\n'.join(
        ('  ' if int(s.get('level') or 1) == 2 else '') + str(s.get('title') or '')
        for s in outline.get('sections') or [])


def section_messages(topic, outline, section, current, instruction, refs_text='',
                     docs_text=''):
    """→ (system, user)，只改一节。"""
    from . import prompt
    user = [f'报告主题：{topic}', '', '全篇目录（仅作上下文，不要改它）：',
            _outline_lines(outline), '',
            f'当前这一节（{section["title"]}）：', current, '',
            f'修改要求：{instruction}']
    refs = prompt.refs_block(refs_text, docs_text)
    if refs:
        user += ['', '## 参考资料', refs.strip()]
    return _SECTION_SYSTEM, '\n'.join(user)


def revise_all_messages(topic, outline, current, instruction, refs_text='',
                        docs_text=''):
    """→ (system, user)，改全文。"""
    from . import prompt
    user = [f'报告主题：{topic}', '', '报告目录：', _outline_lines(outline), '',
            '当前报告全文：', current, '',
            f'修改要求：{instruction}']
    refs = prompt.refs_block(refs_text, docs_text)
    if refs:
        user += ['', '## 参考资料', refs.strip()]
    return _REVISE_ALL_SYSTEM, '\n'.join(user)
