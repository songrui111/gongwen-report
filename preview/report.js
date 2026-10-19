/* 报告正文的渲染与打标：Markdown → 干净 HTML → 按体例打类 → 挂落款。

   从 ai-chat.html 里搬出来，去掉的是和面板耦合的部分：不再从输入框读主题/主送机关/
   署名（改成 load() 的参数），不再自己发请求取报告（内容由调用方给）。

   对外只有一个入口：

     await window.__reportPreview.load(markdown, opts, breaks)

   opts   {recipient, org, date, head} —— 主送机关、发文机关署名、成文日期（'YYYY-MM-DD'）、
                                           版头/版记字段（见 mountHead / mountImprint）
   breaks {}                       —— 证伪用，见 applyBreaks()。默认全假。

   返回的 Promise 在**字体加载完、落款的右空算完**之后才 resolve —— 版式测试量的是
   真页面，量之前必须保证页面已经定下来。
*/

/* ============ Markdown 渲染（marked + DOMPurify，本地 vendored）============

   这两个库放在 vendor/ 里而不是走 CDN：**判据是量真页面**，CDN 挂了或者版本漂了，
   量出来的东西就不是这份代码印出来的东西了。离线可用也是这个仓库的一个卖点。 */
(function () {
  if (typeof marked !== 'undefined') {
    marked.use({ gfm: true, breaks: true });
  }

  function esc(s) {
    return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;')
                    .replace(/>/g, '&gt;');
  }

  function renderMarkdown(text) {
    if (!text) return '';
    if (typeof marked === 'undefined' || typeof DOMPurify === 'undefined') {
      // 脚本没加载（离线打开、路径写错）时降级为纯文本。**降级要显眼**：
      // 打印出来是一段没有层次的文字，一眼就知道渲染没跑，不会误以为版式没问题。
      return esc(String(text)).replace(/\n/g, '<br>');
    }
    const raw = marked.parse(String(text));
    const clean = DOMPurify.sanitize(raw);
    // 表格包一层 .table-wrap，横向滚动交给它
    return clean.replace(/<table>/g, '<div class="table-wrap"><table>')
                .replace(/<\/table>/g, '</table></div>');
  }

  /* ============ 按文本打类（CSS 认不出段落内容）============

     主送机关（标准 7.3.2）要**居左顶格**，不能跟着正文段落缩进两字。判据就用标准
     给的判据：紧跟在标题后面、以全角冒号收尾的那一段。
     但这条判据的前提是「标题后第一段就是主送机关」，而那只在默认公文体例下成立。
     加了「照上传文档的格式写」之后有两种开头，所以**只有在确实给了主送机关时才打
     这个类**：没给的时候模型被要求整行不写，标题后第一段是正文，正文里以「：」结尾
     的句子不该被顶格。

     表号表题、单位行、表注这几类按体例不缩进，判据取的是模板要求里那几种开头的原样：
     表题「表 1 …」、单位行「（单位：亿元）」、表注「注：」。 */
  function tagLines(rendered, recipient) {
    const firstP = rendered.querySelector('h1 + p');
    if (recipient && firstP && /：\s*$/.test(firstP.textContent)) {
      firstP.classList.add('doc-to');
    }
    for (const p of rendered.querySelectorAll('p')) {
      if (/^\s*(表\s*\d|图\s*\d|注[：:]|（单位|\(单位)/.test(p.textContent)) {
        p.classList.add('no-indent');
      }
    }
  }

  /* ============ 落款 ============

     这两样**故意不进模型的输出**。机关名由调用方逐字给 —— 模型最容易做的事就是把
     机关名简写（「某某市科学技术局」→「市科技局」），而署名恰恰是公文里最不能改的
     一处；日期取本机当天或调用方指定，不由模型猜。机关名留空就只出日期，**绝不替发文
     机关编一个署名**（提示词里第 14 条也是这么要求的）。

     成文日期的写法按标准 7.3.5.4：阿拉伯数字将年、月、日标全，年份标全称，月、日
     **不编虚位** —— 10 月写「10月」不写「010月」，3 日写「3日」不写「03日」。所以
     这里拼字符串而不是 toISOString().slice(0,10)。 */
  function docDate(d) {
    return d.getFullYear() + '年' + (d.getMonth() + 1) + '月' + d.getDate() + '日';
  }

  function signLines(opts) {
    const lines = [];
    if (opts.org) lines.push(opts.org);
    const date = opts.date ? parseDate(opts.date) : new Date();
    // 日期给死了就用给死的（快照、测试要可复现）；没给才取本机当天
    lines.push(docDate(date));
    return lines;
  }

  function parseDate(s) {
    const m = /^(\d{4})-(\d{1,2})-(\d{1,2})$/.exec(String(s).trim());
    if (!m) return new Date(s);
    return new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]));
  }

  /* 正文之后挂一块落款。用 DOM 造而不是写进 Markdown：署名要**右对齐**，Markdown 里
     表达不了；若改用「选中最后两段」的 CSS 选择器，模型多写一行就错位。

     右空多少按标准 7.3.5.2（**不加盖印章**的公文，这一路没有印章，走的就是这一条）：
     「在发文机关署名下一行编排成文日期，首字比发文机关署名首字右移二字，如成文日期
     长于发文机关署名，应当使成文日期右空二字编排，并相应增加发文机关署名右空字数。」
     两行都右对齐，于是
         署名右空 = 2 字；日期右空 = 署名宽 − 日期宽      （署名更宽时）
         日期右空 = 2 字；署名右空 = 2 字 + 日期宽 − 署名宽（日期更宽时）
     宽度**实测**，不按字数估：成文日期里的阿拉伯数字是半角（「2026年10月10日」按字数
     是 7 个字，实际只有 5 个多字宽）。 */
  function mountSign(content, lines) {
    const old = content.querySelector('.doc-sign');
    if (old) old.remove();
    const div = document.createElement('div');
    div.className = 'doc-sign';
    const ps = [];
    for (const t of lines) {
      const p = document.createElement('p');
      p.textContent = t;   // textContent：机关名是人给的，不进 HTML 解析
      div.appendChild(p);
      ps.push(p);
    }
    content.appendChild(div);
    return ps;
  }

  function textWidth(p) {
    const r = document.createRange();
    r.selectNodeContents(p);
    return r.getBoundingClientRect().width;
  }

  function measureSign(ps, breaks) {
    // 只有一行（没给发文机关，只剩日期）时，两行之间的那条关系不存在，按日期右空二字
    // 排就完了 —— CSS 里的 padding 就是这个值，不用再算。
    if (!ps || ps.length !== 2) return;
    if (breaks.sign) return;   // 证伪：两行都按右空二字排（标准要的不是这个）
    // 单位一律用 em：这个 p 的字号就是正文字号，em 跟着它走，屏幕上算出来的倍数拿到
    // 纸面上（3 号）同样成立，不用重算。
    const zi = parseFloat(getComputedStyle(ps[1]).fontSize);
    const w = ps.map(textWidth);
    // 页面没显示（宽度量出来是 0）就退回右空二字，别把落款顶到版心边上
    if (!zi || !(w[0] > 0) || !(w[1] > 0)) return;
    if (w[0] >= w[1]) {
      ps[0].style.paddingRight = 2 + 'em';
      ps[1].style.paddingRight = ((w[0] - w[1]) / zi).toFixed(3) + 'em';
    } else {
      ps[0].style.paddingRight = (2 + (w[1] - w[0]) / zi).toFixed(3) + 'em';
      ps[1].style.paddingRight = 2 + 'em';
    }
  }

  /* ============ 版头 ============

     版头（标准 7.2）排在正文之前。和落款一样，字段由调用方给，**不进模型的输出**：
     发文机关标志、发文字号、签发人这些是发文机关赋上的，模型编就是造假。

     每一项都选填，没填的整行不写。自上而下：
       份号 / 密级和保密期限 / 紧急程度 —— 顶格在版心左上角，3 号黑体；
       发文机关标志 —— 居中、红色大字，这就是「红头」；
       发文字号（有签发人时居左空一字、签发人居右空一字；没有签发人就居中）；
       红色分隔线 —— 红色、与版心等宽，把版头和主体一刀切开。
     红色分隔线跟发文字号/签发人绑在一起：没有这两样，说明版头不完整，线也不画 ——
     和导出 Word 那一路（ai智能体 report_docx.masthead）同一个口径。 */
  function headFields(head) {
    head = head || {};
    return {
      top: ['copy_no', 'secret', 'urgency'].map(function (k) {
        return (head[k] || '').trim();
      }).filter(Boolean),
      banner: (head.banner || '').trim(),
      docNo: (head.doc_no || '').trim(),
      signer: (head.signer || '').trim()
    };
  }

  function mountHead(content, head) {
    const f = headFields(head);
    const any = f.top.length || f.banner || f.docNo || f.signer;
    if (!any) return null;   // 一项都没填就不画 —— 不替发文机关编一个空壳版头
    const old = content.querySelector('.doc-head');
    if (old) old.remove();
    const div = document.createElement('div');
    div.className = 'doc-head' + (f.banner ? ' has-banner' : '');
    // 份号/密级/紧急收进一个块：有红头时这块**补足三行**（30pt×3），红头上边缘才落在
    // 35mm —— 见 paper.css 里 .has-banner 那两条。
    const top = document.createElement('div');
    top.className = 'head-top-block';
    for (const t of f.top) {
      const p = document.createElement('p');
      p.className = 'head-top';
      p.textContent = t;       // textContent：字段是人给的，不进 HTML 解析
      top.appendChild(p);
    }
    div.appendChild(top);
    if (f.banner) {
      const p = document.createElement('p');
      p.className = 'head-banner';
      p.textContent = f.banner;
      div.appendChild(p);
    }
    if (f.docNo || f.signer) {
      // 有签发人：发文字号居左空一字、签发人居右空一字；只有发文字号：居中（7.2.5）
      const row = document.createElement('div');
      row.className = 'head-no' + (f.signer ? '' : ' no-signer');
      const no = document.createElement('span');
      no.className = 'head-doc-no';
      no.textContent = f.docNo;
      row.appendChild(no);
      if (f.signer) {
        const sg = document.createElement('span');
        sg.className = 'head-signer';
        const lab = document.createElement('span');
        lab.textContent = '签发人：';
        sg.appendChild(lab);
        const nm = document.createElement('span');
        nm.className = 'head-signer-name';
        nm.textContent = f.signer;
        sg.appendChild(nm);
        row.appendChild(sg);
      }
      div.appendChild(row);
      const rule = document.createElement('div');
      rule.className = 'head-rule';
      div.appendChild(rule);
    }
    // 版头在 .rendered 之前：公文的顺序就是版头 → 主体 → 版记
    content.insertBefore(div, content.querySelector('.rendered'));
    return div;
  }

  /* ============ 版记 ============

     版记（标准 7.4）排在正文（和落款）之后：抄送机关、印发机关和印发日期，
     首末两条粗线、中间一条细线，都与版心等宽。
     **不复现「排在最后一面版心底端」这一条**：把一块内容锚到页面底部的定位，浏览器
     打印做不了 —— 这里是接在落款后面另起一段排，和导出 Word 那一路的口径一致。 */
  function mountImprint(content, head) {
    head = head || {};
    const cc = (head.cc || '').trim();
    const printer = (head.printer || '').trim();
    const pdate = (head.print_date || '').trim();
    if (!(cc || printer || pdate)) return null;
    const old = content.querySelector('.doc-imprint');
    if (old) old.remove();
    const div = document.createElement('div');
    div.className = 'doc-imprint';
    const rule = function (thin) {
      const r = document.createElement('div');
      r.className = 'imp-rule' + (thin ? ' imp-rule-thin' : '');
      div.appendChild(r);
    };
    rule(false);
    if (cc) {
      const p = document.createElement('p');
      p.className = 'imp-cc';
      p.textContent = '抄送：' + cc.replace(/。+$/, '') + '。';
      div.appendChild(p);
    }
    if (printer || pdate) {
      if (cc) rule(true);   // 有抄送行才有「中间那条细线」把它和印发行隔开
      const row = document.createElement('div');
      row.className = 'imp-print';
      const pr = document.createElement('span');
      pr.className = 'imp-printer';
      pr.textContent = printer;
      row.appendChild(pr);
      const dt = document.createElement('span');
      dt.className = 'imp-date';
      dt.textContent = pdate;
      row.appendChild(dt);
      div.appendChild(row);
    }
    rule(false);
    content.appendChild(div);
    return div;
  }

  /* ============ 证伪用的四个旋钮 ============

     下面四种「改坏」都是把上面某一条判据的前提去掉，用来看测试到底有没有在判。
     早先的做法是对 paper.css 做精确字符串替换（连空格都要对上），**一旦失配就变成
     一次静默的 no-op** —— 测试报绿，而你以为是版式没问题。现在改的是变量和规则本身，
     改不动就是改不动。

     indent  缩进按元素自身字号算（标准要的是所有层次都按正文字号算）
     sign    日期不和署名错开（见 measureSign）
     font    落款拿不到 .report-content 上的字族和字号，掉回默认字体和 12pt 小四
     table   表格字号回到四号
     paper   @page 的四边不是标准给的数（上 37 左 28 下 35 右 26） */
  function applyBreaks(el, breaks) {
    const style = document.createElement('style');
    let css = '';
    if (breaks.indent) el.style.setProperty('--body-indent', '2em');
    if (breaks.table) el.style.setProperty('--table-size', '14pt');
    if (breaks.font) {
      css += '.report-content > .doc-sign { font-family: serif; font-size: 12pt; }\n';
    }
    if (breaks.paper) {
      css += '@page { size: A4; margin: 25.4mm 31.7mm 25.4mm 31.7mm; }\n';
    }
    if (css) {
      style.textContent = css;
      document.head.appendChild(style);
    }
  }

  async function load(md, opts, breaks) {
    opts = opts || {};
    breaks = breaks || {};
    const content = document.getElementById('reportContent');
    const rendered = document.getElementById('reportRendered');
    applyBreaks(content, breaks);
    rendered.innerHTML = renderMarkdown(md);
    tagLines(rendered, opts.recipient);
    mountHead(content, opts.head);              // 版头在正文之前
    const ps = mountSign(content, signLines(opts));
    mountImprint(content, opts.head);           // 版记在落款之后
    /* **量落款宽度之前必须等字体就绪**：仿宋没加载完的时候量到的是一份替代字体的
       宽度，而那两个右空值是按宽度算出来的 —— 不等就偶发飘红，而且是那种「重跑一次
       就好了」的飘红，最难查。 */
    if (document.fonts && document.fonts.ready) {
      try { await document.fonts.ready; } catch (e) { /* 拿不到就算了，不至于因此不出报告 */ }
    }
    measureSign(ps, breaks);
    return { ok: true, sign: ps.length };
  }

  window.__reportPreview = { load: load, render: renderMarkdown, tagLines: tagLines };
})();
