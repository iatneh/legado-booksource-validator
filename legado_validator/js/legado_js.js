'use strict';
/* ============================================================================
 * Legado 风格的 JS 沙箱底座（供 resolve.js 引入）
 *
 * 这里的 API 形态**照着 Legado 官方源码**对齐，不是猜的：
 *
 *   - ``java.ajax(url)``            -> String（响应体）        JsExtensions.ajax
 *   - ``java.connect(url)``         -> StrResponse             JsExtensions.connect
 *   - ``java.get(url, headers)``    -> Jsoup Connection.Response
 *   - ``java.post(url, body, headers)`` -> Jsoup Connection.Response
 *   - ``java.put(key, value)`` / ``java.get(key)`` -> 变量存储
 *                                     AnalyzeRule.put / AnalyzeRule.get
 *   - ``Packages.org.jsoup.Jsoup.parse(html)`` -> Jsoup Document
 *
 * 早期版本把 ajax 返回成对象、post/get 返回成自定义对象，导致
 * ``java.ajax(url).match(...)``、``java.post(...).header(...)`` 这类
 * 写法在沙箱里直接抛错，很多实际能用的书源被判成"无法解析"。
 * ========================================================================== */

const VOID_TAGS = new Set(['area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input',
  'link', 'meta', 'param', 'source', 'track', 'wbr', 'basefont', 'frame', 'isindex']);

const IMPLICIT_PARENT = {
  li: ['li'], p: ['p'], tr: ['tr', 'td', 'th'], td: ['td', 'th'],
  th: ['td', 'th'], option: ['option'], dd: ['dd', 'dt'], dt: ['dt', 'dd'],
  tbody: ['tbody', 'thead', 'tfoot', 'tr', 'td', 'th']
};

const TAG_RE = /<(\/)?([a-zA-Z][\w:-]*)((?:"[^"]*"|'[^']*'|[^>"'])*?)(\/)?>/g;
const ATTR_RE = /([\w:.-]+)(?:\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'>]+)))?/g;
const SIMPLE_RE = /^([a-zA-Z][\w-]*)?((?:[.#][\w-]+)*)$/;
const PSEUDO_RE = /^(.*?):(nth-child|nth-of-type|first-child|last-child|eq|not)(?:\(\s*(-?\d+)\s*\))?$/;
const ATTR_SEL_RE = /\[\s*([\w-]+)\s*(?:(\*=|\^=|\$=|!=|=)\s*(?:"([^"]*)"|'([^']*)'|([^\]]*?))\s*)?\]/g;

/* ------------------------------------------------------------------ 节点 */
function El(tag, attrs) {
  this.tag = tag;
  this.attrs = attrs || {};
  this.children = [];
  this.parent = null;
}
El.prototype.classes = function () {
  const c = this.attrs['class'];
  if (!c) return [];
  return String(c).split(/\s+/).filter(Boolean);
};
El.prototype.text = function () {
  let out = '';
  for (const ch of this.children) {
    if (typeof ch === 'string') out += ch;
    else out += ch.text();
  }
  return out;
};
El.prototype.outerHtml = function () {
  let out = '<' + this.tag;
  for (const k of Object.keys(this.attrs)) {
    out += ' ' + k + '="' + String(this.attrs[k]).replace(/"/g, '&quot;') + '"';
  }
  out += '>';
  for (const ch of this.children) {
    out += typeof ch === 'string' ? ch : ch.outerHtml();
  }
  out += '</' + this.tag + '>';
  return out;
};
El.prototype.innerHtml = function () {
  let out = '';
  for (const ch of this.children) out += typeof ch === 'string' ? ch : ch.outerHtml();
  return out;
};
El.prototype.iterDesc = function () {
  const out = [];
  for (const ch of this.children) {
    if (typeof ch === 'string') continue;
    out.push(ch);
    out.push.apply(out, ch.iterDesc());
  }
  return out;
};

/* ------------------------------------------------------------ HTML 解析器 */
function parseAttrs(txt) {
  const attrs = {};
  if (!txt) return attrs;
  ATTR_RE.lastIndex = 0;
  let m;
  while ((m = ATTR_RE.exec(txt)) !== null) {
    const name = m[1];
    const val = m[2] !== undefined ? m[2] : (m[3] !== undefined ? m[3]
      : (m[4] !== undefined ? m[4] : ''));
    if (name) attrs[name.toLowerCase()] = val;
  }
  return attrs;
}

function parseHtml(html) {
  const root = new El('#root', {});
  const stack = [root];
  const s = String(html || '');
  const lower = s.toLowerCase();
  let i = 0;
  const n = s.length;
  while (i < n) {
    const lt = s.indexOf('<', i);
    if (lt < 0) { stack[stack.length - 1].children.push(s.slice(i)); break; }
    if (lt > i) stack[stack.length - 1].children.push(s.slice(i, lt));
    if (s.startsWith('<!--', lt)) {
      const end = s.indexOf('-->', lt);
      i = end >= 0 ? end + 3 : n;
      continue;
    }
    if (s.startsWith('<!', lt) || s.startsWith('<?', lt)) {
      const end = s.indexOf('>', lt);
      i = end >= 0 ? end + 1 : n;
      continue;
    }
    TAG_RE.lastIndex = lt;
    const m = TAG_RE.exec(s);
    if (!m || m.index !== lt) {
      stack[stack.length - 1].children.push('<');
      i = lt + 1;
      continue;
    }
    const closing = m[1];
    const tag = m[2].toLowerCase();
    const attrtext = m[3] || '';
    const selfclose = m[4];
    i = m.index + m[0].length;
    if (closing) {
      for (let idx = stack.length - 1; idx > 0; idx--) {
        if (stack[idx].tag === tag) { stack.length = idx; break; }
      }
      continue;
    }
    const el = new El(tag, parseAttrs(attrtext));
    el.parent = stack[stack.length - 1];
    stack[stack.length - 1].children.push(el);
    if (tag === 'script' || tag === 'style') {
      const end = lower.indexOf('</' + tag, i);
      const stop = end < 0 ? n : end;
      el.children.push(s.slice(i, stop));
      i = stop;
      continue;
    }
    if (VOID_TAGS.has(tag) || selfclose === '/') continue;
    const parents = IMPLICIT_PARENT[tag];
    if (parents) {
      while (stack.length > 1 && parents.indexOf(stack[stack.length - 1].tag) >= 0) {
        stack.pop();
      }
    }
    stack.push(el);
  }
  return root;
}

/* ------------------------------------------------------------- CSS 选择器 */
function attrMatch(el, attr, op, want) {
  const val = el.attrs[attr];
  if (val === undefined) return false;
  if (!op) return true;
  if (op === '=') return String(val) === String(want);
  if (op === '*=') return String(val).indexOf(want) >= 0;
  if (op === '^=') return String(val).indexOf(want) === 0;
  if (op === '$=') return String(val).slice(-want.length) === String(want);
  if (op === '!=') return String(val) !== String(want);
  return false;
}

function matchAttrs(el, sel) {
  ATTR_SEL_RE.lastIndex = 0;
  let m;
  while ((m = ATTR_SEL_RE.exec(sel)) !== null) {
    let want = m[3];
    if (want === undefined) want = m[4];
    if (want === undefined) want = m[5];
    if (want === undefined) want = '';
    want = String(want).trim();
    if (!attrMatch(el, m[1], m[2], want)) return false;
  }
  return true;
}

function matchPseudo(el, kind, arg) {
  const parent = el.parent;
  if (!parent) return false;
  // nth-of-type 数同标签兄弟；其余的按全部元素子节点计数
  const sibs = kind === 'nth-of-type'
    ? parent.children.filter(function (c) { return c instanceof El && c.tag === el.tag; })
    : parent.children.filter(function (c) { return c instanceof El; });
  const idx = sibs.indexOf(el);
  if (idx < 0) return false;
  if (kind === 'first-child') return idx === 0;
  if (kind === 'last-child') return idx === sibs.length - 1;
  if (kind === 'nth-child' || kind === 'nth-of-type') {
    const n = arg ? parseInt(arg, 10) : 1;
    return idx + 1 === n;
  }
  if (kind === 'eq') {
    // :eq(n) 是"整个匹配集合里的第 n 个"，由 cssFind 在收集完候选后取
    return true;
  }
  if (kind === 'not') {
    return !matchNotArg(el, arg);
  }
  return false;
}

/* :not(...) 里的选择器命中了就要排除 */
function matchNotArg(el, arg) {
  const a = String(arg == null ? '' : arg).trim();
  if (!a) return false;
  if (a.charAt(0) === '[') return matchAttrs(el, a);
  return simpleMatch(el, a);
}

function simpleMatch(el, sel) {
  sel = String(sel).trim();
  let notArg = null;
  const nm = /^(.*?):not\(([^()]*)\)$/.exec(sel);
  if (nm) {
    notArg = String(nm[2]).trim();
    sel = String(nm[1]).trim();
  }
  let pseudo = null;
  const pm = PSEUDO_RE.exec(sel);
  if (pm) {
    sel = String(pm[1]).trim();
    pseudo = [pm[2], pm[3]];
  }
  if (sel.indexOf('[') >= 0) {
    if (!matchAttrs(el, sel)) return false;
    sel = sel.replace(ATTR_SEL_RE, '').trim();
  }
  const sm = SIMPLE_RE.exec(sel);
  if (!sm) return false;
  const tag = sm[1];
  if (tag && el.tag !== tag.toLowerCase()) return false;
  const toks = String(sm[2] || '').match(/[.#][\w-]+/g) || [];
  for (const tok of toks) {
    if (tok[0] === '.') {
      if (el.classes().indexOf(tok.slice(1)) < 0) return false;
    } else if (el.attrs['id'] !== tok.slice(1)) {
      return false;
    }
  }
  if (pseudo && !matchPseudo(el, pseudo[0], pseudo[1])) return false;
  if (notArg !== null && matchNotArg(el, notArg)) return false;
  return true;
}

/* 把 'a.b > c d' 拆成 [{rel, sel}] */
function splitCss(selector) {
  const parts = [];
  let rel = ' ';
  let buf = '';
  for (let i = 0; i < selector.length; i++) {
    const ch = selector[i];
    if (ch === '>' || ch === '+' || ch === '~') {
      if (buf.trim()) { parts.push({ rel: rel, sel: buf.trim() }); buf = ''; }
      rel = ch;
      continue;
    }
    if (/\s/.test(ch)) {
      if (buf.trim()) { parts.push({ rel: rel, sel: buf.trim() }); buf = ''; rel = ' '; }
      continue;
    }
    buf += ch;
  }
  if (buf.trim()) parts.push({ rel: rel, sel: buf.trim() });
  return parts;
}

function elementSiblings(el) {
  if (!el || !el.parent) return [];
  return el.parent.children.filter(function (c) { return c instanceof El; });
}

function nextSiblings(el) {
  const sibs = elementSiblings(el);
  const i = sibs.indexOf(el);
  if (i < 0) return [];
  return sibs.slice(i + 1, i + 2);
}

function followingSiblings(el) {
  const sibs = elementSiblings(el);
  const i = sibs.indexOf(el);
  if (i < 0) return [];
  return sibs.slice(i + 1);
}

/* 从左往右匹配：结果是最右边那一段的匹配（和 Jsoup 的 select 一致） */
function cssFind(root, selector) {
  const out = [];
  const groups = String(selector).split(',');
  for (const g of groups) {
    const parts = splitCss(g.trim());
    if (!parts.length) continue;
    let cur = [root];
    for (let pi = 0; pi < parts.length; pi++) {
      const p = parts[pi];
      const next = [];
      for (const scope of cur) {
        let cands;
        if (pi === 0) {
          cands = [scope].concat(scope.iterDesc());
        } else if (p.rel === '>') {
          cands = scope.children.filter(function (c) { return c instanceof El; });
        } else if (p.rel === '+') {
          cands = nextSiblings(scope);
        } else if (p.rel === '~') {
          cands = followingSiblings(scope);
        } else {
          cands = scope.iterDesc();
        }
        for (const el of cands) {
          if (simpleMatch(el, p.sel)) next.push(el);
        }
      }
      /* :eq(n) 取整个匹配集合里的第 n 个 */
      const pm = PSEUDO_RE.exec(p.sel);
      if (pm && pm[2] === 'eq') {
        const n = pm[3] ? parseInt(pm[3], 10) : 0;
        const picked = (n >= 0 && n < next.length) ? [next[n]] : [];
        next.length = 0;
        for (const p2 of picked) next.push(p2);
      }
      cur = next;
      if (!cur.length) break;
    }
    for (const c of cur) if (out.indexOf(c) < 0) out.push(c);
  }
  return out;
}

/* ----------------------------------------------------- Jsoup 风格的 API */
function jsoupElements(els) {
  const list = els || [];
  const api = {
    size: function () { return list.length; },
    length: list.length,
    get: function (i) { return jsoupElement(list[i]); },
    first: function () { return jsoupElement(list[0]); },
    last: function () { return jsoupElement(list[list.length - 1]); },
    eq: function (i) { return jsoupElement(list[i]); },
    each: function (fn) { list.forEach(function (el, i) { fn.call(el, jsoupElement(el), i); }); return api; },
    toArray: function () { return list.map(function (el) { return jsoupElement(el); }); },
    text: function () { return list.map(function (el) { return el.text(); }).join(' '); },
    html: function () { return list.map(function (el) { return el.innerHtml(); }).join(''); },
    outerHtml: function () { return list.map(function (el) { return el.outerHtml(); }).join(''); },
    attr: function (n) {
      for (const el of list) {
        if (el && el.attrs[n] !== undefined) return el.attrs[n];
      }
      return '';
    },
    absUrl: function (n) { return api.attr(n); },
    select: function (sel) {
      const acc = [];
      for (const el of list) {
        for (const x of cssFind(el, sel)) if (acc.indexOf(x) < 0) acc.push(x);
      }
      return jsoupElements(acc);
    },
    isEmpty: function () { return list.length === 0; },
    toString: function () { return api.outerHtml(); }
  };
  return api;
}

function jsoupElement(el) {
  if (!el) {
    const empty = jsoupElements([]);
    empty.text = function () { return ''; };
    empty.html = function () { return ''; };
    empty.attr = function () { return ''; };
    empty.hasAttr = function () { return false; };
    empty.isEmpty = function () { return true; };
    empty.outerHtml = function () { return ''; };
    empty.toString = function () { return ''; };
    return empty;
  }
  const api = jsoupElements([el]);
  api.hasAttr = function (n) { return el.attrs[n] !== undefined; };
  api.parent = function () { return jsoupElement(el.parent); };
  api.prev = function (sel) {
    const sibs = siblings(el);
    const p = sibs[sibs.indexOf(el) - 1];
    if (sel && p && !simpleMatch(p, sel)) return jsoupElement(null);
    return jsoupElement(p);
  };
  api.next = function (sel) {
    const sibs = siblings(el);
    const nx = sibs[sibs.indexOf(el) + 1];
    if (sel && nx && !simpleMatch(nx, sel)) return jsoupElement(null);
    return jsoupElement(nx);
  };
  api.children = function () { return jsoupElements(el.children.filter(function (c) { return c instanceof El; })); };
  api.wholeText = function () { return el.text(); };
  api.data = function () { return el.text(); };
  return api;
}

function siblings(el) {
  if (!el || !el.parent) return [];
  return el.parent.children.filter(function (c) { return c instanceof El; });
}

function jsoupDocument(html, baseUrl) {
  const root = parseHtml(html);
  const doc = {
    select: function (sel) { return jsoupElements(cssFind(root, sel)); },
    text: function () { return root.text(); },
    wholeText: function () { return root.text(); },
    html: function () { return root.innerHtml(); },
    outerHtml: function () { return root.outerHtml(); },
    title: function () {
      const t = cssFind(root, 'title');
      return t.length ? t[0].text() : '';
    },
    attr: function (n) { return root.attrs[n] === undefined ? '' : root.attrs[n]; },
    absUrl: function (n) { return doc.attr(n); },
    location: function () { return baseUrl || ''; },
    baseUri: function () { return baseUrl || ''; },
    first: function () { return jsoupElement(root); },
    toString: function () { return root.outerHtml(); }
  };
  return doc;
}

function jsoupStub(baseUrl) {
  return {
    Jsoup: {
      parse: function (html) { return jsoupDocument(html, baseUrl); },
      connect: function (url) {
        return {
          get: function () { return { body: function () { return ''; }, statusCode: function () { return 0; } }; },
          execute: function () { return { body: function () { return ''; }, statusCode: function () { return 0; } }; }
        };
      }
    },
    Connection: { Response: function () { } },
    Parser: { parse: function (html) { return jsoupDocument(html, baseUrl); } },
    Element: function () { }
  };
}

module.exports = {
  El: El, parseHtml: parseHtml, cssFind: cssFind, simpleMatch: simpleMatch,
  jsoupStub: jsoupStub, jsoupDocument: jsoupDocument, jsoupElements: jsoupElements,
  jsoupElement: jsoupElement
};
