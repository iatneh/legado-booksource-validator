# -*- coding: utf-8 -*-
"""校验主流程：逐条书源实测搜索接口，并深链到目录/正文。"""
import concurrent.futures as cf
import json
import re
import time

from .engine import eval_rule, json_path
from .http import detect_block, fetch
from .rules import (abs_url, book_items, keywords_for, norm_base, parse_body,
                    src_headers, swap_kw)

STATUS_OK = 'ok'
STATUS_WEAK = 'weak'
STATUS_ALIVE = 'nores'
STATUS_BLOCKED = 'blocked'
STATUS_API_QUIRK = 'api_quirk'
STATUS_NET_ERROR = 'net_error'
STATUS_HTTP_ERROR = 'http_error'
STATUS_NO_RULE = 'no_rule'
STATUS_UNSUPPORTED = 'unsupported'
STATUS_ERROR = 'error'


def _json_template(rule, item):
    """展开 JSON 源里的 URL 模板，如 ``https://x/book/{{$.id}}``。

    JSON 接口的书源，bookUrl / chapterUrl 往往不是 JSONPath，而是拿当前
    条目的字段拼出来的 URL 模板，必须对着**条目**展开，不能对整份响应求值。
    """
    s = str(rule or '')
    if not s:
        return ''

    def _repl(m):
        v = json_path(item, m.group(1))
        return '' if v is None else str(v)

    if '{{' in s:
        return re.sub(r'\{\{([^}]+)\}\}', _repl, s)
    # 纯 JSONPath 形式：对着条目取字段
    if s.startswith('$'):
        v = json_path(item, s)
        if isinstance(v, (str, int, float)):
            return str(v)
    return s


def _resolve_link(rule, item, doc, js):
    """取出一个链接：JSON 响应走模板展开，HTML 响应走规则求值。"""
    if js is not None and isinstance(item, dict):
        return [_json_template(rule, item)]
    return eval_rule(rule, doc=doc, js=js, item=item)


def name_filled(src, items, doc, js, limit=3):
    """书名规则能在多少个条目上取到内容。

    书单能取到、但书名规则已经过时（站点改版）的情况很常见：这种源在
    阅读里能点进去，书名却是空的。这里单独量出来，好让修复环节把它们
    也纳入处理范围。

    JSON 接口的书源，书名规则是**相对条目**求值的（``$.title`` 指当前
    这本书的 title 字段），必须对着条目算，否则会误判成"书名规则失效"。
    """
    rule = (src.get('ruleSearch') or {}).get('name')
    if not rule or not items:
        return 0, 0
    filled = 0
    for it in items[:limit]:
        vals = []
        if js is not None and isinstance(it, dict):
            # 先按条目求值（Legado 的做法），再退回整份响应求值
            v = json_path(it, rule)
            if isinstance(v, (str, int, float)) and str(v).strip():
                vals = [str(v)]
            else:
                try:
                    vals = eval_rule(rule, js=js, item=it)
                except Exception:
                    vals = []
        else:
            try:
                vals = eval_rule(rule, doc=doc, js=js, item=it)
            except Exception:
                vals = []
        if any(isinstance(v, str) and v.strip() for v in vals):
            filled += 1
    return filled, min(limit, len(items))


def deep_check(src, items, doc, js, base, headers, timeout, user_agent=None):
    """书单 -> 书籍详情 -> 目录 -> 章节正文，验证整条链路。

    链路按 **Legado 真实语义** 走：

    1. ``ruleSearch.bookUrl`` -> 书籍详情页
    2. 书籍详情页上用 ``ruleBookInfo.tocUrl`` 取**目录页**地址；
       没写这条规则时，Legado 退回到用书籍页自身当目录页
    3. 目录页上用 ``ruleToc.chapterList / chapterName / chapterUrl`` 取章节
    4. 章节页上用 ``ruleContent.content`` 取正文

    早期版本把目录规则直接套在书籍页上判，导致"目录页独立"的站点
    （绝大多数）被误判成目录规则失效。
    """
    d = {'book': False, 'toc': False, 'content': False, 'reason': ''}
    rules = src.get('ruleSearch') or {}
    bu = rules.get('bookUrl')
    if not bu:
        d['reason'] = 'no_book_url_rule'
        return d
    try:
        hrefs = _resolve_link(bu, items[0], doc, js)
    except Exception:
        d['reason'] = 'bookurl_err'
        return d
    href = next((h.strip() for h in hrefs if isinstance(h, str) and h.strip()), '')
    if not href:
        # 第一条可能不是书籍条目（如表头/广告），往后找几条
        for it in items[1:5]:
            try:
                more = _resolve_link(bu, it, doc, js)
            except Exception:
                continue
            cand = next((h.strip() for h in more
                         if isinstance(h, str) and h.strip()), '')
            if cand:
                href = cand
                break
    if not href:
        d['reason'] = 'no_book_url'
        return d
    item = items[0]
    if isinstance(item, dict):
        def _repl(m):
            v = json_path(item, m.group(1))
            return '' if v is None else str(v)
        href2 = re.sub(r'\{\{([^}]+)\}\}', _repl, href)
        if href2:
            href = href2
    book_url = abs_url(base, href)
    r2 = fetch(book_url, 'GET', None, headers, timeout, user_agent)
    if not r2['ok'] or r2['status'] >= 400:
        d['reason'] = 'book_fetch_failed'
        return d
    d['book'] = True
    js2, doc2 = parse_body(r2)

    # ---- 目录页地址：ruleBookInfo.tocUrl，没有就退回书籍页本身 ----
    toc_url = book_url
    toc_rule = (src.get('ruleBookInfo') or {}).get('tocUrl')
    if toc_rule:
        try:
            vals = eval_rule(toc_rule, doc=doc2, js=js2)
        except Exception:
            vals = []
        cand = next((str(v).strip() for v in vals
                     if isinstance(v, str) and v.strip()), '')
        if cand:
            toc_url = abs_url(r2.get('url') or book_url, cand)

    toc = src.get('ruleToc') or {}
    cl = toc.get('chapterList')
    toc_items = []
    if cl:
        try:
            from .engine import rule_items
            toc_items = rule_items(cl, doc=doc2, js=js2) or []
        except Exception:
            toc_items = []
    if not toc_items and toc_url != book_url:
        # 目录另开一页：按 Legado 那样去目录页取章节
        r2b = fetch(toc_url, 'GET', None, headers, timeout, user_agent)
        if not r2b['ok'] or r2b['status'] >= 400:
            d['reason'] = 'toc_fetch_failed'
            return d
        js2, doc2 = parse_body(r2b)
        try:
            from .engine import rule_items
            toc_items = rule_items(cl, doc=doc2, js=js2) or []
        except Exception:
            toc_items = []
        if toc_items:
            r2 = r2b
    if not toc_items:
        d['reason'] = 'no_toc_items'
        return d
    d['toc'] = True
    cu = toc.get('chapterUrl')
    if not cu:
        d['reason'] = 'no_chapter_url_rule'
        return d
    try:
        hrefs = _resolve_link(cu, toc_items[0], doc2, js2)
    except Exception:
        d['reason'] = 'chapterurl_err'
        return d
    churl = next((h.strip() for h in hrefs if isinstance(h, str) and h.strip()), '')
    if not churl:
        d['reason'] = 'no_chapter_url'
        return d
    r3 = fetch(abs_url(r2.get('url') or base, churl), 'GET', None, headers, timeout, user_agent)
    if not r3['ok'] or r3['status'] >= 400:
        d['reason'] = 'content_fetch_failed'
        return d
    js3, doc3 = parse_body(r3)
    cr = (src.get('ruleContent') or {}).get('content')
    if not cr:
        d['content'] = True
        d['reason'] = 'no_content_rule'
        return d
    try:
        vals = eval_rule(cr, doc=doc3, js=js3)
    except Exception:
        d['reason'] = 'content_rule_err'
        return d
    text = ' '.join(v for v in vals if isinstance(v, str))
    if len(text.strip()) < 20:
        d['reason'] = 'empty_content'
        return d
    d['content'] = True
    return d


def validate_one(src, spec_info, server, timeout=25, kw0='修真', keywords=None,
                 user_agent=None):
    """校验单条书源。"""
    out = {
        'i': spec_info.get('i'), 'name': src.get('bookSourceName'),
        'url': src.get('bookSourceUrl'), 'server': server,
        'status': 'unknown', 'http': 0, 'ms': 0, 'items': 0,
        'req_url': '', 'method': '', 'err': None, 'block': None,
        'keyword_hit': False, 'links': 0,
        'deep': {'book': False, 'toc': False, 'content': False, 'reason': ''},
        'js': bool(spec_info.get('js')), 'fallback': bool(spec_info.get('fallback')),
    }
    bl = (src.get('ruleSearch') or {}).get('bookList')
    if not bl:
        out['status'] = STATUS_NO_RULE
        return out
    if not spec_info.get('ok'):
        out['status'] = STATUS_UNSUPPORTED
        out['err'] = spec_info.get('err')
        return out
    base = norm_base(src.get('bookSourceUrl'))
    headers = src_headers(src)
    spec = spec_info.get('spec') or {}
    tries = []
    if spec.get('url'):
        tries.append(spec)
    for cand in (spec_info.get('cands') or [])[:3]:
        tries.append({'url': cand, 'method': 'GET', 'body': None, 'headers': {}})
    saw200 = sawkw = sawmany = sawblk = sawhttp = sawnet = sawquirk = False
    kws = keywords_for(src, keywords)
    for cand in tries:
        for kwi, kw in enumerate(kws):
            use = cand if kwi == 0 else swap_kw(cand, kw0, kw)
            if not use or not use.get('url'):
                continue
            h = dict(headers)
            h.update(use.get('headers') or {})
            res = fetch(use['url'], use.get('method') or 'GET', use.get('body'),
                        h, timeout, user_agent)
            out['req_url'] = use['url']
            out['method'] = use.get('method') or 'GET'
            out['ms'] = res.get('ms', 0)
            if not res['ok']:
                out['status'] = STATUS_NET_ERROR
                out['err'] = res.get('err')
                sawnet = True
                break
            out['http'] = res['status']
            blk = detect_block(res['status'], res['body'])
            if res['status'] == 202:
                blk = blk or 'challenge_202'
            if blk:
                out['status'] = STATUS_BLOCKED
                out['block'] = blk
                sawblk = True
                break
            if res['status'] >= 400:
                if res['status'] in (404, 410):
                    out['status'] = STATUS_HTTP_ERROR
                    sawhttp = True
                elif res['status'] == 403:
                    out['status'] = STATUS_BLOCKED
                    out['block'] = 'http_403'
                    sawblk = True
                else:
                    out['status'] = STATUS_API_QUIRK
                    sawquirk = True
                continue
            saw200 = True
            body = res['body']
            if kw in body:
                out['keyword_hit'] = True
                sawkw = True
            nlinks = len(re.findall(r'<a\s', body, re.I))
            out['links'] = nlinks
            if nlinks >= 12 and len(body) >= 1500:
                sawmany = True
            js, doc = parse_body(res)
            items = book_items(src, doc=doc, js=js)
            if items:
                out['status'] = STATUS_OK
                out['items'] = len(items)
                filled, tried = name_filled(src, items, doc, js)
                out['name_filled'] = filled
                out['name_tried'] = tried
                out['name_ok'] = filled > 0
                out['deep'] = deep_check(src, items, doc, js, base, h, timeout, user_agent)
                return out
    if saw200:
        # 「页面活但取不到条目」里，只有**命中关键词**的才算 weak：
        # 连关键词都没有，说明请求打回了首页/空壳页，不是选择器过时。
        out['status'] = STATUS_WEAK if sawkw else STATUS_ALIVE
        out['note'] = ('site_alive_no_items' if sawkw
                       else ('search_returned_homepage' if sawmany
                             else 'site_alive_no_items'))
    elif sawquirk:
        out['status'] = STATUS_API_QUIRK
    elif sawblk:
        out['status'] = STATUS_BLOCKED
    elif sawhttp:
        out['status'] = STATUS_HTTP_ERROR
    elif sawnet:
        out['status'] = STATUS_NET_ERROR
    return out


def validate_all(sources, specs, server, timeout=25, threads=10, kw0='修真',
                 keywords=None, user_agent=None, only=None, progress=None):
    """并发校验全部书源，返回结果列表（按原始下标排序）。"""
    by_index = dict((s.get('i'), s) for s in specs)
    indexes = list(range(len(sources)))
    if only:
        indexes = [i for i in indexes if i in set(only)]
    results = []
    t0 = time.time()
    with cf.ThreadPoolExecutor(max_workers=threads) as pool:
        futures = {}
        for i in indexes:
            si = by_index.get(i, {'i': i, 'ok': False, 'err': 'missing_spec'})
            futures[pool.submit(validate_one, sources[i], si, server, timeout,
                                kw0, keywords, user_agent)] = i
        done = 0
        for fut in cf.as_completed(futures):
            i = futures[fut]
            try:
                res = fut.result()
            except Exception as exc:
                res = {'i': i, 'name': sources[i].get('bookSourceName'),
                       'url': sources[i].get('bookSourceUrl'), 'server': server,
                       'status': STATUS_ERROR, 'err': str(exc)[:160], 'http': 0,
                       'ms': 0, 'items': 0, 'req_url': '', 'method': '',
                       'block': None, 'keyword_hit': False,
                       'deep': {'book': False, 'toc': False, 'content': False,
                                'reason': 'exc'}}
            results.append(res)
            done += 1
            if progress and done % 100 == 0:
                progress('progress %d/%d (%.0fs)' % (done, len(indexes), time.time() - t0))
    results.sort(key=lambda r: r.get('i') or 0)
    return results


def save_results(results, path):
    with open(path, 'w', encoding='utf-8') as fh:
        json.dump(results, fh, ensure_ascii=False, indent=1)
