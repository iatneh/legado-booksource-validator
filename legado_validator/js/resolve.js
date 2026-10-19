'use strict';
const fs = require('fs');
const vm = require('vm');
const cp = require('child_process');
const crypto = require('crypto');

const SRC = process.argv[2];
const OUT = process.argv[3];
const KEY = process.argv[4] || '修真';
const PAGE = parseInt(process.argv[5] || '1', 10);
const UA = 'Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 (KHTML, like Gecko) ' +
  'Chrome/120.0.0.0 Mobile Safari/537.36';

const sources = JSON.parse(fs.readFileSync(SRC, 'utf8'));

function substTpl(str, ctx) {
  return String(str).replace(/\{\{([^{}]*)\}\}/g, function (m, expr) {
    const e = String(expr).trim();
    if (e === 'key' || e === 'bookName' || e === 'sKey' || e === 'keyWord' || e === 'q') {
      return ctx.keyEnc;
    }
    if (e === 'page' || e === 'pageIndex') return String(ctx.page);
    if (e === 'baseUrl' || e === 'baseUrl ') return ctx.baseUrl;
    if (/^page/.test(e)) {
      try {
        const ex = e.replace(/\bpage\b/g, 'P');
        return String(new Function('P', 'return (' + ex + ')')(ctx.page));
      } catch (err) { return String(ctx.page); }
    }
    if (/^[A-Za-z_$][\w$]*$/.test(e)) return '';
    try {
      const ex = e.replace(/\bpage\b/g, 'P');
      return String(new Function('P', 'return (' + ex + ')')(ctx.page));
    } catch (err) { return ''; }
  });
}

function normalizeBase(u) {
  const s = String(u || '').trim();
  if (!s) return '';
  if (s.indexOf('//') === 0) return 'https:' + s;
  if (/^https?:\/\//i.test(s)) return s;
  if (/^[a-z0-9.-]+\.[a-z]{2,}(\/|$|:)/i.test(s)) return 'https://' + s;
  return '';
}

function joinBase(base, rel) {
  if (!rel) return base;
  if (/^https?:\/\//i.test(rel)) return rel;
  if (rel.indexOf('//') === 0) return 'https:' + rel;
  try {
    const b = base.indexOf('/') === -1 ? base + '/' : base;
    return new URL(rel, b).toString();
  } catch (e) {
    return base.replace(/\/+$/, '') + '/' + rel.replace(/^\/+/, '');
  }
}

function extractUrls(text) {
  const out = [];
  const re = /https?:\/\/[^\s'"<>\\)]+/g;
  let m;
  while ((m = re.exec(String(text))) !== null) {
    if (out.indexOf(m[0]) < 0) out.push(m[0]);
  }
  return out;
}

function curlFetch(url, opts) {
  opts = opts || {};
  const method = String(opts.method || 'GET').toUpperCase();
  const headers = opts.headers || {};
  const tmp = '/tmp/.legado_' + process.pid + '_' + Math.random().toString(36).slice(2);
  const args = ['-sS', '-L', '--max-time', '25', '--compressed', '-A', opts.ua || UA,
    '-o', tmp, '-w', '%{http_code}'];
  Object.keys(headers || {}).forEach(function (k) {
    if (headers[k] !== undefined && headers[k] !== null) args.push('-H', k + ': ' + headers[k]);
  });
  if (method !== 'GET' && method !== 'HEAD') {
    args.push('-X', method);
    if (opts.body !== undefined && opts.body !== null && opts.body !== '') {
      args.push('--data-raw', String(opts.body));
    }
  }
  args.push(String(url));
  let out = '';
  try {
    out = cp.execFileSync('curl', args, {
      encoding: 'utf8', maxBuffer: 64 * 1024 * 1024, timeout: 30000,
      stdio: ['ignore', 'pipe', 'ignore']
    });
  } catch (e) { out = ''; }
  let body = '';
  try { body = fs.readFileSync(tmp, 'utf8'); } catch (e) { body = ''; }
  try { fs.unlinkSync(tmp); } catch (e) { /* ignore */ }
  const code = parseInt(String(out).trim(), 10) || 0;
  return { code: code, body: body, error: code ? null : 'curl_failed' };
}

function makeResp(r, url) {
  return {
    string: function () { return r.body; },
    body: function () { return r.body; },
    json: function () { try { return JSON.parse(r.body); } catch (e) { return null; } },
    code: function () { return r.code; },
    headers: function () { return {}; },
    baseUrl: function () { return url; },
    url: function () { return url; },
    toString: function () { return r.body; },
    valueOf: function () { return r.body; }
  };
}

function makeJava(ctx, calls) {
  const store = {};
  function norm(url, a, b) {
    let opts = { method: 'GET', headers: {}, body: null };
    let u = String(url === undefined || url === null ? '' : url).trim();
    const sm = u.match(/^(.*?),\s*(\{[\s\S]*\})\s*$/);
    if (sm) {
      try {
        const o = JSON.parse(sm[2]);
        if (o && typeof o === 'object') { opts = Object.assign(opts, o); u = sm[1].trim(); }
      } catch (e) { /* keep url */ }
    }
    if (a && typeof a === 'object') {
      opts = Object.assign(opts, a);
    } else if (typeof a === 'string' && a.trim().charAt(0) === '{') {
      try { opts = Object.assign(opts, JSON.parse(a)); } catch (e) { /* ignore */ }
    } else if (typeof a === 'string' && a.length) {
      opts.headers = { 'User-Agent': UA };
    }
    if (typeof b === 'string') opts.body = b;
    else if (b && typeof b === 'object') {
      if (b.body !== undefined) opts.body = b.body;
      if (b.method) opts.method = b.method;
      if (b.headers) opts.headers = Object.assign({}, opts.headers, b.headers);
    }
    if (opts.header && !opts.headers) opts.headers = opts.header;
    if (!opts.headers) opts.headers = {};
    return { url: u, opts: opts };
  }
  function doReq(url, a, b) {
    const n = norm(url, a, b);
    const rec = {
      url: n.url, method: String(n.opts.method || 'GET').toUpperCase(),
      body: n.opts.body || null, headers: n.opts.headers || {}
    };
    const r = curlFetch(n.url, n.opts);
    rec.status = r.code;
    rec.len = r.body ? r.body.length : 0;
    rec.error = r.error;
    calls.push(rec);
    return makeResp(r, n.url);
  }
  const base = {
    ajax: doReq,
    get: function (url, a, b) { const n = norm(url, a, b); n.opts.method = 'GET'; return doReq(n.url, n.opts, null); },
    post: function (url, body, a) { const n = norm(url, a); n.opts.method = 'POST'; n.opts.body = body; return doReq(n.url, n.opts, null); },
    connect: function (url, a) { const n = norm(url, a); return doReq(n.url, n.opts, null); },
    webView: function (url) { const r = curlFetch(url, {}); return r.body; },
    put: function (k, v) { if (v === undefined) return store[k]; store[k] = v; return v; },
    encodeURI: function (s) { return encodeURIComponent(String(s)); },
    decodeURI: function (s) { try { return decodeURIComponent(String(s)); } catch (e) { return s; } },
    md5: function (s) { return crypto.createHash('md5').update(String(s)).digest('hex'); },
    md5Encode: function (s) { return crypto.createHash('md5').update(String(s)).digest('hex'); },
    sha1: function (s) { return crypto.createHash('sha1').update(String(s)).digest('hex'); },
    base64Encode: function (s) { return Buffer.from(String(s), 'utf8').toString('base64'); },
    base64Decode: function (s) { try { return Buffer.from(String(s), 'base64').toString('utf8'); } catch (e) { return ''; } },
    base64DecodeToByteArr: function (s) { try { return Array.from(Buffer.from(String(s), 'base64')); } catch (e) { return []; } },
    aesEncode: function (s) { return String(s); },
    getRandom: function () { return Math.floor(Math.random() * 90000000 + 10000000); },
    log: function () { }, toast: function () { }, longToast: function () { },
    getCookie: function () { return ''; }, getResponse: function () { return ''; },
    all: {}
  };
  return new Proxy(base, {
    get: function (t, p) {
      if (p in t) return t[p];
      if (typeof p === 'symbol') return undefined;
      return javaStub('java.' + String(p));
    }
  });
}

function makeSource(src) {
  return {
    getVariable: function () { return '{}'; },
    getKey: function () { return KEY; },
    getString: function () { return ''; },
    getHeader: function () { return src.header || ''; },
    getCookie: function () { return ''; },
    getLoginInfo: function () { return ''; },
    getLoginInfoMap: function () { return {}; },
    getVariableMap: function () { return {}; },
    get: function () { return ''; },
    getBook: function () { return null; }
  };
}

function makeCookie() {
  return {
    getCookie: function () { return ''; },
    setCookie: function () { },
    removeCookie: function () { },
    getCookieMap: function () { return {}; }
  };
}

function makeCache() {
  const m = {};
  return {
    put: function (k, v) { m[k] = v; },
    get: function (k) { return m[k]; }
  };
}

function javaStub(name) {
  const fn = function () { return javaStub(name + '()'); };
  return new Proxy(fn, {
    get: function (t, p) {
      if (p === Symbol.toPrimitive) return function () { return ''; };
      if (p === 'toString') return function () { return ''; };
      if (p === 'valueOf') return function () { return ''; };
      if (p === 'then') return undefined;
      return javaStub(name + '.' + String(p));
    },
    apply: function () { return javaStub(name + '()'); }
  });
}

function jsoupStub() {
  return {
    Jsoup: {
      parse: function (html) {
        const h = String(html || '');
        return {
          select: function (sel) {
            return {
              attr: function (n) {
                if (String(sel).indexOf('form') >= 0) {
                  const m = h.match(/<form[^>]*action=["']([^"']+)["']/i);
                  return m ? m[1] : '';
                }
                const nm = String(sel).match(/name=([\w-]+)/);
                if (nm) {
                  const re = new RegExp('<input[^>]*name=["\']' + nm[1] + '["\'][^>]*value=["\']([^"\']*)["\']', 'i');
                  const m2 = h.match(re);
                  if (m2) return m2[1];
                  const re2 = new RegExp('<input[^>]*value=["\']([^"\']*)["\'][^>]*name=["\']' + nm[1] + '["\']', 'i');
                  const m3 = h.match(re2);
                  if (m3) return m3[1];
                }
                return '';
              },
              text: function () { return ''; },
              first: function () { return this; }
            };
          },
          text: function () { return h; }
        };
      }
    }
  };
}

function buildSandbox(src, base, ctx, calls) {
  const sandbox = {
    key: ctx.key, page: ctx.page, baseUrl: base, bookSourceUrl: base,
    source: makeSource(src), java: makeJava(ctx, calls), cookie: makeCookie(),
    Packages: javaStub('Packages'), org: jsoupStub(),
    cache: makeCache(), result: undefined, book: undefined, chapter: undefined,
    JSON: JSON, Math: Math, Date: Date, String: String, Number: Number,
    Array: Array, Object: Object, RegExp: RegExp, parseInt: parseInt,
    parseFloat: parseFloat, isNaN: isNaN, Error: Error, TypeError: TypeError,
    Promise: Promise, Symbol: Symbol, Map: Map, Set: Set,
    encodeURIComponent: encodeURIComponent, decodeURIComponent: decodeURIComponent,
    encodeURI: encodeURI, decodeURI: decodeURI,
    console: { log: function () { }, warn: function () { }, error: function () { } }
  };
  sandbox.global = sandbox;
  sandbox.globalThis = sandbox;
  return sandbox;
}

function parseSpec(str, base, ctx) {
  let s = String(str).trim();
  if (s.charAt(0) === '"' || s.charAt(0) === "'") {
    try {
      s = JSON.parse(s.charAt(0) === '"' ? s : JSON.stringify(s.slice(1, -1)));
    } catch (e) { s = s.slice(1, -1); }
  }
  let opts = {};
  const m = s.match(/^(.*?),\s*(\{[\s\S]*\})\s*$/);
  if (m) {
    let parsed = null;
    try { parsed = JSON.parse(m[2]); } catch (e) {
      try { parsed = new Function('return (' + m[2] + ')')(); } catch (e2) { parsed = null; }
    }
    if (parsed && typeof parsed === 'object') {
      opts = parsed;
      s = m[1].trim();
    }
  }
  if (s.indexOf('{{') >= 0) s = substTpl(s, ctx);
  let url = s;
  if (url.indexOf('//') === 0) url = 'https:' + url;
  else if (!/^https?:\/\//i.test(url)) url = joinBase(base, url);
  const method = String(opts.method || 'GET').toUpperCase();
  let body = null;
  if (opts.body !== undefined && opts.body !== null) body = substTpl(String(opts.body), ctx);
  const headers = {};
  const hs = opts.headers || opts.header || {};
  Object.keys(hs).forEach(function (k) { headers[k] = hs[k]; });
  if (opts.charset) headers['X-Legado-Charset'] = String(opts.charset);
  return { url: url, method: method, body: body, headers: headers };
}

function resolveSource(src, idx) {
  const out = {
    i: idx, name: src.bookSourceName || '', base: src.bookSourceUrl || '',
    js: false, ok: false, spec: null, err: null, netErr: false, calls: []
  };
  const raw = String(src.searchUrl || '').trim();
  const base = normalizeBase(src.bookSourceUrl);
  const ctx = { key: KEY, keyEnc: encodeURIComponent(KEY), page: PAGE, baseUrl: base };
  if (!raw) { out.err = 'no_search_rule'; return out; }
  let result = null;
  const jsInline = raw.match(/<js>([\s\S]*?)<\/js>/);
  if (raw.indexOf('@js:') === 0 || jsInline) {
    out.js = true;
    const sandbox = buildSandbox(src, base, ctx, out.calls);
    const vmctx = vm.createContext(sandbox);
    const lib = String(src.jsLib || '');
    if (lib) {
      try { vm.runInContext(lib, vmctx, { timeout: 15000 }); } catch (e) { /* lib may need APIs */ }
    }
    const loginJs = String(src.loginUrl || '');
    if (loginJs && /function\s+\w+|=>|var\s|let\s|const\s/.test(loginJs)) {
      try { vm.runInContext(loginJs, vmctx, { timeout: 10000 }); } catch (e) { /* login helper optional */ }
    }
    try {
      const src_js = raw.indexOf('@js:') === 0 ? raw.slice(4) : jsInline[1];
      const code = substTpl(src_js, ctx);
      const script = new vm.Script(code, { filename: 'rule-' + idx + '.js' });
      result = script.runInContext(vmctx, { timeout: 30000 });
    } catch (e) {
      out.err = 'js_error: ' + String(e && e.message ? e.message : e).slice(0, 200);
    }
  } else {
    result = substTpl(raw, ctx);
  }
  out.calls.forEach(function (c) { if (!c.status) out.netErr = true; });
  if (result === undefined || result === null || result === '') {
    if (!out.err) out.err = 'empty_result';
    if (out.js) {
      const cands = extractUrls(raw);
      if (cands.length) {
        out.cands = cands.map(function (c) { return joinBase(base, substTpl(c, ctx)); });
        out.spec = { url: out.cands[0], method: 'GET', body: null, headers: {} };
        out.ok = true;
        out.fallback = true;
      }
    }
    return out;
  }
  try {
    out.spec = parseSpec(String(result), base, ctx);
    out.ok = true;
  } catch (e) {
    out.err = 'spec_error';
  }
  return out;
}

const results = [];
for (let i = 0; i < sources.length; i++) {
  let r;
  try {
    r = resolveSource(sources[i], i);
  } catch (e) {
    r = { i: i, name: sources[i].bookSourceName || '', base: sources[i].bookSourceUrl || '',
      js: false, ok: false, spec: null, err: 'fatal: ' + String(e && e.message ? e.message : e).slice(0, 150),
      netErr: false, calls: [] };
  }
  results.push(r);
}
fs.writeFileSync(OUT, JSON.stringify(results));
const okCount = results.filter(function (r) { return r.ok; }).length;
const jsCount = results.filter(function (r) { return r.js; }).length;
const netCount = results.filter(function (r) { return r.netErr; }).length;
console.log('total=' + results.length + ' resolved=' + okCount + ' js=' + jsCount + ' netErr=' + netCount);
