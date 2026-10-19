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


def deep_check(src, items, doc, js, base, headers, timeout, user_agent=None):
    """书单 -> 书籍详情 -> 目录 -> 章节正文，验证整条链路。"""
    d = {'book': False, 'toc': False, 'content': False, 'reason': ''}
    rules = src.get('ruleSearch') or {}
    bu = rules.get('bookUrl')
    if not bu:
        d['reason'] = 'no_book_url_rule'
        return d
    try:
        hrefs = eval_rule(bu, doc=doc, js=js, item=items[0])
    except Exception:
        d['reason'] = 'bookurl_err'
        return d
    href = next((h.strip() for h in hrefs if isinstance(h, str) and h.strip()), '')
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
    r2 = fetch(abs_url(base, href), 'GET', None, headers, timeout, user_agent)
    if not r2['ok'] or r2['status'] >= 400:
        d['reason'] = 'book_fetch_failed'
        return d
    d['book'] = True
    toc = src.get('ruleToc') or {}
    cl = toc.get('chapterList')
    js2, doc2 = parse_body(r2)
    toc_items = []
    if cl:
        try:
            from .engine import rule_items
            toc_items = rule_items(cl, doc=doc2, js=js2) or []
        except Exception:
            toc_items = []
    if not toc_items:
        d['reason'] = 'no_toc_items'
        return d
    d['toc'] = True
    cu = toc.get('chapterUrl')
    if not cu:
        d['reason'] = 'no_chapter_url_rule'
        return d
    try:
        hrefs = eval_rule(cu, doc=doc2, js=js2, item=toc_items[0])
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
    saw200 = sawkw = sawblk = sawhttp = sawnet = sawquirk = False
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
                sawkw = True
            js, doc = parse_body(res)
            items = book_items(src, doc=doc, js=js)
            if items:
                out['status'] = STATUS_OK
                out['items'] = len(items)
                out['deep'] = deep_check(src, items, doc, js, base, h, timeout, user_agent)
                return out
    if saw200:
        out['status'] = STATUS_WEAK if sawkw else STATUS_ALIVE
        out['note'] = 'site_alive_no_items'
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
