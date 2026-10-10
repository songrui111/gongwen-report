/* 量尺：量真页面，不读 CSS。

   **只有测试用它。** page.html 里没有这个 <script>，是 build.py 生成测试页时才加进去
   的 —— 页面上多一行只是多一行，但这个文件里全是「给机器看的中间量」，留在页面里会
   让人误以为版式渲染依赖它。

   量的是元素**第一个字符的左边缘**（Range.getBoundingClientRect），相对 .rendered 的
   左边缘；以及落款两行的字号、字族、右空和宽度。量宽度而不是数字数，是因为成文日期
   里的阿拉伯数字是半角，「2026年10月10日」按字数是 7 个字、实际只有 5 个多字宽 ——
   按字数估出来的右空，纸面上差着一截。

   结果写成 JSON 塞进 <div id="xprobe">，由外面的 Edge --dump-dom 抓走。
   （2026-10-10 的教训：这些数字全都读 CSS 推不出来。缩进 2em 按谁的字号算、落款能不能
   继承到那一对变量、右空是「都空二字」还是「日期再错开二字」—— 三处都是印出来才看见的。） */
(function () {
  function charLeft(el, base) {
    let node = null;
    for (let i = 0; i < el.childNodes.length; i++) {
      if (el.childNodes[i].nodeType === 3 && el.childNodes[i].textContent.trim()) {
        node = el.childNodes[i];
        break;
      }
    }
    if (!node) return null;
    const r = document.createRange();
    r.setStart(node, 0);
    r.setEnd(node, 1);
    return r.getBoundingClientRect().left - base;
  }

  function textWidth(el) {
    const r = document.createRange();
    r.selectNodeContents(el);
    return r.getBoundingClientRect().width;
  }

  window.__reportPreviewProbe = function () {
    const content = document.getElementById('reportContent');
    const rend = document.getElementById('reportRendered');
    const base = rend.getBoundingClientRect().left;
    const left = {};

    // 每种标签取第一个非顶格元素：屏幕上的层次序数就靠这几个比
    ['h1', 'h2', 'h3', 'h4', 'p'].forEach(function (tag) {
      const list = rend.querySelectorAll(tag);
      for (let i = 0; i < list.length; i++) {
        const el = list[i];
        if (el.classList.contains('doc-to') || el.classList.contains('no-indent')) continue;
        if (el.textContent.trim()) { left[tag] = charLeft(el, base); return; }
      }
    });
    ['doc-to', 'no-indent'].forEach(function (cls) {
      const el = rend.querySelector('p.' + cls) || content.querySelector('p.' + cls);
      left[cls] = el ? charLeft(el, base) : null;
    });

    const sign = [];
    const ps = content.querySelectorAll('.doc-sign p');
    for (let k = 0; k < ps.length; k++) {
      const cs = getComputedStyle(ps[k]);
      sign.push({
        text: ps[k].textContent,
        fontFamily: cs.fontFamily,
        fontSize: parseFloat(cs.fontSize),
        htmlFontSize: parseFloat(getComputedStyle(rend).fontSize),
        paddingRight: parseFloat(cs.paddingRight),
        width: textWidth(ps[k])
      });
    }
    return { left: left, sign: sign, errs: window.__errs || [] };
  };

  window.__reportPreviewDump = function (obj) {
    const d = document.createElement('div');
    d.id = 'xprobe';
    d.textContent = JSON.stringify(obj);
    document.body.appendChild(d);
  };
})();
