# -*- coding: utf-8 -*-
"""书源规则自动修复：从真实搜索结果页反推 bookList / bookUrl / name / author。

思路：原书源写死的选择器往往已经过时（站点改版），但**页面结构还在**。
于是从活页里找出"重复出现、且内含书籍详情链接"的容器块，反推出新的
CSS 选择器，再用引擎验证是否真的能取到书单条目。
"""
from . import proposer


def repair_source(src, doc, base, max_items=40, keyword=None, page_body=None):
    """给单条书源找一组可用规则；找不到返回 (None, 诊断)。

    规则由 proposer.propose_candidates 反推，name / bookUrl 都是**相对书单
    元素**的写法（Legado 里这两条规则是在每个书单元素内部查找的）。

    ``keyword`` 命中页面正文时才允许"放宽"判据：只有确认拿到的确实是
    搜索结果页，放宽出来的容器才可能是书单；否则导航栏、筛选条会被
    误当成书单，反推出错误的规则。
    """
    from . import proposer
    allow_loose = bool(keyword) and bool(page_body) and keyword in page_body
    cands = proposer.propose_candidates(doc, max_items=max_items,
                                        allow_loose=allow_loose)
    tried = []
    for c in cands:
        rule, diag = proposer.build_rule(c, doc)
        tried.append((c['note'], diag.get('items')))
        if rule:
            return rule, {'ok': True, 'items': diag['items'], 'name': diag['name'],
                          'url': diag['url'], 'note': diag['note'],
                          'ratio': diag['ratio'], 'tried': len(tried)}
    best = None
    for c in cands[:5]:
        n, name, url, ratio, name_ok = proposer.evaluate(c, doc)
        if n >= 1 and url:
            score = ratio + (0.2 if name_ok else 0)
            if best is None or score > best[0]:
                best = (score, c, n, name, url, ratio, name_ok)
    if best:
        _, c, n, name, url, ratio, name_ok = best
        return None, {'ok': False, 'reason': 'quality_gate',
                      'candidates': len(cands), 'tried': len(tried),
                      'best': {'bookList': c['bookList'], 'bookUrl': c['bookUrl'],
                               'items': n, 'name': name, 'url': url,
                               'ratio': round(ratio, 2), 'name_ok': name_ok}}
    return None, {'ok': False, 'candidates': len(cands), 'tried': len(tried)}


def _fetch_search_page(src, spec_info, timeout=25, kw0='修真', keywords=None,
                       user_agent=None):
    """按校验器同样的方式取回搜索页；返回 (res, doc, js, 实际用的关键词)。

    多个关键词都试一遍，**优先取正文里带关键词的那一页**——有些站
    收录的书目里没有第一个关键词，那一页是空的，换个词才有结果。
    """
    from .http import fetch
    from .rules import (keywords_for, norm_base, parse_body,
                        src_headers, swap_kw)
    spec = spec_info.get('spec') or {}
    tries = []
    if spec.get('url'):
        tries.append(spec)
    for cand in (spec_info.get('cands') or [])[:3]:
        tries.append({'url': cand, 'method': 'GET', 'body': None, 'headers': {}})
    headers = src_headers(src)
    # 关键词顺序：规格是按 kw0 解析出来的，所以第一个候选对应的就是 kw0；
    # 其余关键词把 URL 里的 kw0 换掉。
    kws = [kw0]
    for k in keywords_for(src, keywords):
        if k and k not in kws:
            kws.append(k)
    fallback = None
    for cand in tries:
        for kwi, kw in enumerate(kws):
            use = cand if kwi == 0 else swap_kw(cand, kw0, kw)
            if not use or not use.get('url'):
                continue
            h = dict(headers)
            h.update(use.get('headers') or {})
            res = fetch(use['url'], use.get('method') or 'GET', use.get('body'),
                        h, timeout, user_agent)
            if not res['ok'] or res['status'] >= 400:
                continue
            js, doc = parse_body(res)
            if doc is None:
                continue
            body = res.get('body') or ''
            if kw and kw in body:
                # 命中关键词：这才是真正的搜索结果页
                return res, doc, js, kw
            if fallback is None:
                fallback = (res, doc, js, kw)
    if fallback:
        return fallback
    return None, None, None, ''


def repair_all(sources, specs, server, out_path, report_path, result_path=None,
                timeout=25, kw0='修真', keywords=None, user_agent=None,
                only=None, progress=None):
    """对指定节点上"活着但取不到条目"的书源做规则修复。"""
    import json
    from .rules import norm_base
    by_index = dict((s.get('i'), s) for s in specs)
    statuses = {}
    name_ok = {}
    if result_path:
        with open(result_path, 'r', encoding='utf-8') as fh:
            for r in json.load(fh):
                statuses[r.get('i')] = r.get('status')
                if 'name_ok' in r:
                    name_ok[r.get('i')] = bool(r.get('name_ok'))
    indexes = list(range(len(sources)))
    if only:
        indexes = [i for i in indexes if i in set(only)]
    elif statuses:
        # 需要修的两类：
        #  1) 站点活着但选择器取不到条目（weak / nores）
        #  2) 书单能取到、但书名规则已过时（ok 且 name_ok 为假）——这种源
        #     在阅读里书名是空的，同样属于"失效书源"
        indexes = [i for i in indexes
                   if statuses.get(i) in ('weak', 'nores', 'alive')
                   or (statuses.get(i) == 'ok' and not name_ok.get(i, True))]
    fixed, report = [], {}
    for i in indexes:
        src = sources[i]
        si = by_index.get(i)
        if not si or not si.get('ok'):
            continue
        res, doc, js, used_kw = _fetch_search_page(src, si, timeout, kw0,
                                                   keywords, user_agent)
        if doc is None:
            report[i] = {'ok': False, 'reason': 'no_page'}
            continue
        base = norm_base(src.get('bookSourceUrl'))
        rules, diag = repair_source(src, doc, base, keyword=used_kw,
                                    page_body=res.get('body') if res else '')
        if rules:
            new_src = dict(src)
            merged = dict(src.get('ruleSearch') or {})
            merged.update(rules)
            new_src['ruleSearch'] = merged
            new_src['_repaired'] = diag
            new_src['_orig_index'] = i
            new_src['_repaired_on'] = server
            fixed.append(new_src)
            report[i] = {'ok': True, 'name': src.get('bookSourceName'),
                         'url': src.get('bookSourceUrl'), 'diag': diag,
                         'old_rules': {k: (src.get('ruleSearch') or {}).get(k)
                                       for k in ('bookList', 'bookUrl', 'name')},
                         'new_rules': rules}
        else:
            report[i] = {'ok': False, 'name': src.get('bookSourceName'),
                         'url': src.get('bookSourceUrl'), 'reason': 'no_candidate',
                         'diag': diag}
        if progress and i % 20 == 0:
            progress('repair %d/%d fixed=%d' % (i, len(indexes), len(fixed)))
    with open(out_path, 'w', encoding='utf-8') as fh:
        json.dump(fixed, fh, ensure_ascii=False, indent=1)
    with open(report_path, 'w', encoding='utf-8') as fh:
        json.dump(report, fh, ensure_ascii=False, indent=1)
    return fixed, report
