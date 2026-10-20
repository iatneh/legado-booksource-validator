# -*- coding: utf-8 -*-
"""深链修复驱动：把「搜索 -> 书籍页 -> 目录页 -> 章节页 -> 正文」走一遍，
对断掉的 ``ruleToc`` / ``ruleContent`` 现场反推新规则并**实测验证**。

只在"当前规则确实取不到东西"时才动手；新规则必须能取到足够的章节 /
正文，否则保持原样（宁可不动，也不要改坏）。
"""
import json
import re

from . import deepfix
from .engine import eval_rule, rule_items
from .rules import abs_url, book_items, keywords_for, norm_base, parse_body, src_headers, swap_kw


def _fetch(url, method, body, headers, timeout, user_agent):
    from .http import fetch
    return fetch(url, method or 'GET', body, headers, timeout, user_agent)


def _first(value):
    if isinstance(value, (list, tuple)):
        for v in value:
            if isinstance(v, str) and v.strip():
                return v.strip()
        return ''
    return str(value or '').strip()


def _eval(rule, doc, js, item=None):
    if not rule:
        return []
    try:
        return eval_rule(rule, doc=doc, js=js, item=item)
    except Exception:
        return []


def _chapter_items(src, doc, js):
    cl = (src.get('ruleToc') or {}).get('chapterList')
    if not cl:
        return []
    try:
        return rule_items(cl, doc=doc, js=js) or []
    except Exception:
        return []


def _content_text(src, doc, js):
    cr = (src.get('ruleContent') or {}).get('content')
    if not cr:
        return ''
    vals = _eval(cr, doc, js)
    return ' '.join(v for v in vals if isinstance(v, str)).strip()


def deep_repair_one(src, spec, timeout=25, user_agent=None, kw0='修真',
                    keywords=None):
    """修一条书源的深链规则；返回 (新规则 or None, 诊断)。"""
    diag = {'name': src.get('bookSourceName'), 'url': src.get('bookSourceUrl'),
            'toc': None, 'content': None}
    rules = src.get('ruleSearch') or {}
    bu = rules.get('bookUrl')
    if not bu:
        diag['why'] = 'no_book_url_rule'
        return None, diag
    headers = src_headers(src)
    spec_spec = (spec or {}).get('spec') or {}
    url = spec_spec.get('url')
    if not url:
        diag['why'] = 'no_request_url'
        return None, diag
    h = dict(headers)
    h.update(spec_spec.get('headers') or {})
    # 关键词轮换：有些站的搜索页只有换词才出书单，跟 repair 走同一套策略。
    kws = [kw0]
    for k in keywords_for(src, keywords):
        if k and k not in kws:
            kws.append(k)
    r1 = None
    js = doc = None
    items = []
    for kw in kws:
        use = spec_spec
        if kw != kw0:
            swapped = swap_kw(spec_spec, kw0, kw)
            if not swapped:
                continue
            use = swapped
        r1 = _fetch(use.get('url'), use.get('method'), use.get('body'), h,
                    timeout, user_agent)
        if not r1['ok'] or r1['status'] >= 400:
            continue
        js, doc = parse_body(r1)
        try:
            items = book_items(src, doc=doc, js=js)
        except Exception:
            items = []
        if items:
            break
    if not r1 or not r1['ok'] or r1['status'] >= 400:
        diag['why'] = 'search_fetch_failed'
        return None, diag
    if not items:
        diag['why'] = 'no_items'
        return None, diag
    # ---- 书籍页 ----
    hrefs = _eval(bu, doc, js, items[0])
    href = _first(hrefs)
    if not href:
        for it in items[1:5]:
            href = _first(_eval(bu, doc, js, it))
            if href:
                break
    if not href:
        diag['why'] = 'no_book_url'
        return None, diag
    if isinstance(items[0], dict):
        from .rules import json_path
        def _repl(m):
            v = json_path(items[0], m.group(1))
            return '' if v is None else str(v)
        href = re.sub(r'\{\{([^}]+)\}\}', _repl, href) or href
    base = norm_base(src.get('bookSourceUrl'))
    book_url = abs_url(base, href)
    r2 = _fetch(book_url, 'GET', None, h, timeout, user_agent)
    if not r2['ok'] or r2['status'] >= 400:
        diag['why'] = 'book_fetch_failed'
        return None, diag
    js2, doc2 = parse_body(r2)

    # ---- 目录页（Legado 语义：写了 tocUrl 就用目录页，否则用书籍页本身）----
    toc_url = book_url
    toc_rule = (src.get('ruleBookInfo') or {}).get('tocUrl')
    if toc_rule:
        cand = _first(_eval(toc_rule, doc2, js2))
        if cand:
            toc_url = abs_url(r2.get('url') or book_url, cand)
    toc_doc, toc_js, toc_res = doc2, js2, r2
    if toc_url != book_url:
        r2b = _fetch(toc_url, 'GET', None, h, timeout, user_agent)
        if not r2b['ok'] or r2b['status'] >= 400:
            diag['why'] = 'toc_fetch_failed'
            return None, diag
        toc_js, toc_doc = parse_body(r2b)
        toc_res = r2b
    cur = _chapter_items(src, toc_doc, toc_js)
    toc_fixed = None
    if not cur:
        # 目录规则确实坏了 -> 反推
        host = ''
        try:
            from urllib.parse import urlsplit
            host = urlsplit(toc_url).netloc.lower()
        except ValueError:
            host = ''
        rules, d = deepfix.propose_toc_rules(toc_doc, host)
        diag['toc'] = d
        if rules:
            try:
                check = rule_items(rules['chapterList'], doc=toc_doc) or []
            except Exception:
                check = []
            if len(check) >= deepfix.MIN_CHAPTERS:
                toc_fixed = rules
                cur = check
    if not cur:
        diag['why'] = 'toc_unfixable'
        return None, diag
    # ---- 章节页 -> 正文 ----
    cu = (src.get('ruleToc') or {}).get('chapterUrl')
    churl = ''
    for it in cur[:3]:
        churl = _first(_eval(cu, toc_doc, toc_js, it))
        if churl:
            break
    if not churl:
        diag['why'] = 'no_chapter_url'
        return None, diag
    content_fixed = None
    content_url = abs_url(toc_res.get('url') or toc_url, churl)
    r3 = _fetch(content_url, 'GET', None, h, timeout, user_agent)
    if not r3['ok'] or r3['status'] >= 400:
        diag['why'] = 'content_fetch_failed'
        return None, diag
    js3, doc3 = parse_body(r3)
    text = _content_text(src, doc3, js3)
    if len(deepfix._strip_notice(text)) < deepfix.MIN_CONTENT_CHARS:
        rule, d = deepfix.propose_content_rule(doc3)
        diag['content'] = d
        if rule:
            check = ' '.join(v for v in _eval(rule, doc3, js3) if isinstance(v, str)).strip()
            if len(deepfix._strip_notice(check)) >= deepfix.MIN_CONTENT_CHARS:
                content_fixed = {'content': rule}
    else:
        diag['content'] = {'ok': True, 'chars': len(text), 'note': '原规则可用'}
    if not toc_fixed and not content_fixed:
        diag['why'] = 'nothing_to_fix'
        return None, diag
    out = {'ruleToc': toc_fixed, 'ruleContent': content_fixed}
    return out, diag


def deep_repair_all(sources, specs, server, out_path, report_path, result_path=None,
                    timeout=25, kw0='修真', keywords=None, user_agent=None,
                    only=None, progress=None):
    """对深链断裂的书源做修复，返回 (修好的书源, 诊断报告)。"""
    by_index = dict((s.get('i'), s) for s in specs)
    statuses = {}
    if result_path:
        with open(result_path, 'r', encoding='utf-8') as fh:
            for r in json.load(fh):
                statuses[r.get('i')] = (r.get('status') or '',
                                        (r.get('deep') or {}).get('reason') or '')
    indexes = list(range(len(sources)))
    if only:
        indexes = [i for i in indexes if i in set(only)]
    elif statuses:
        # 只挑"搜索能出条目、但深链断了"的
        indexes = [i for i in indexes
                   if statuses.get(i, ('', ''))[0] == 'ok'
                   and statuses.get(i, ('', ''))[1] in
                   ('no_toc_items', 'empty_content', 'no_chapter_url',
                    'no_chapter_url_rule', 'content_fetch_failed')]
    fixed, report = [], {}
    for i in indexes:
        src = sources[i]
        si = by_index.get(i)
        if not si or not si.get('ok'):
            continue
        try:
            rules, diag = deep_repair_one(src, si, timeout, user_agent, kw0, keywords)
        except Exception as exc:
            report[i] = {'ok': False, 'name': src.get('bookSourceName'),
                         'reason': 'exc: %s' % exc}
            continue
        if rules and (rules.get('ruleToc') or rules.get('ruleContent')):
            new_src = dict(src)
            if rules.get('ruleToc'):
                merged = dict(src.get('ruleToc') or {})
                merged.update(rules['ruleToc'])
                new_src['ruleToc'] = merged
            if rules.get('ruleContent'):
                merged = dict(src.get('ruleContent') or {})
                merged.update(rules['ruleContent'])
                new_src['ruleContent'] = merged
            new_src['_deep_repaired'] = diag
            new_src['_orig_index'] = i
            new_src['_deep_repaired_on'] = server
            fixed.append(new_src)
            report[i] = {'ok': True, 'name': src.get('bookSourceName'),
                         'url': src.get('bookSourceUrl'),
                         'rules': rules, 'diag': diag}
        else:
            report[i] = {'ok': False, 'name': src.get('bookSourceName'),
                         'url': src.get('bookSourceUrl'), 'reason': diag.get('why'),
                         'diag': diag}
        if progress and i % 20 == 0:
            progress('deep-repair %d/%d fixed=%d' % (i, len(indexes), len(fixed)))
    with open(out_path, 'w', encoding='utf-8') as fh:
        json.dump(fixed, fh, ensure_ascii=False, indent=1)
    with open(report_path, 'w', encoding='utf-8') as fh:
        json.dump(report, fh, ensure_ascii=False, indent=1)
    return fixed, report
