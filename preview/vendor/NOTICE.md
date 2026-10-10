# 这里放的是两个第三方库的**原样**副本，没有改过一个字节

预览那一层（`--png` / `tests/test_print.py`）要在一个离线环境里渲染 Markdown，
所以把两个库连文件带许可一起放进来了，不走 CDN。版本号写死在文件名旁边的代码里，
升级的时候照着下面这几行比一比就知道该换哪个。

| 文件 | 版本 | 许可 | 上游 |
|---|---|---|---|
| `marked.umd.js` | 18.0.14 | MIT | https://github.com/markedjs/marked |
| `purify.min.js` | 3.4.16 | Apache-2.0 / MPL-2.0 双许可 | https://github.com/cure53/DOMPurify |

两个文件的**开头都保留着上游的许可声明**（marked 是那两行 `(MIT License)`，DOMPurify
是那行 `/*! @license DOMPurify 3.4.16 …`），谁打开这两个文件都看得见出处，所以这里不再
重复抄一遍各自的全文 —— 上游仓库里那份才是准的。

## 为什么要懂一点

- **marked** 把 Markdown 变成 HTML。它**不负责安全**：`<script>`、`onclick=` 都会原样
  出去。
- **DOMPurify** 才是那道闸门，`report.js` 里过完它才往页面上放。这两件事分开是有意的：
  报告正文是模型生成的（可能夹带任意 HTML），而这一层要量的是**排版**，不能让一段
  夹带的东西凭空多出几个元素来，把「层次序数同起排」之类的判据量歪。
