# -*- coding: utf-8 -*-
"""用节点实测时的真实请求（URL + 方法 + 请求体），对最终合集抽样复核。

关键点：校验器会在多个关键词之间轮换（``checkKeyWord`` 优先，再退回通用
词），**成功的那个请求**记在结果里的 ``req_url``。复核时必须照抄那个
请求，否则会拿另一个关键词去问站点，问出 0 条结果——那是关键词不匹配，
不是书源坏了。
"""
import json
import random
import sys
import urllib.parse

sys.path.insert(0, '.')
from legado_validator.engine import eval_rule, json_path, rule_items  # noqa: E402
from legado_validator.http import fetch  # noqa: E402
from legado_validator.rules import parse_body, src_headers  # noqa: E402

KEYWORDS = ['修真', '斗破苍穹', '都市', '剑']


def body_for(spec, url):
    """把请求体里的关键词换成 ``url`` 实际用的那个。"""
    body = spec.get('body')
    if not body:
        return body
    for kw in KEYWORDS:
        enc = urllib.parse.quote(kw)
        if enc in url or kw in url:
            body = body.replace(urllib.parse.quote('修真'), enc)
            body = body.replace('修真', kw)
            break
    return body


def main():
    union = json.load(open(sys.argv[1], encoding='utf-8'))
    results = json.load(open(sys.argv[2], encoding='utf-8'))
    specs = json.load(open(sys.argv[3], encoding='utf-8'))
    n = int(sys.argv[4]) if len(sys.argv) > 4 else 12
    seed = int(sys.argv[5]) if len(sys.argv) > 5 else 11

    by_index = dict((r['i'], r) for r in results)
    spec_by_index = dict((s['i'], s) for s in specs)

    picks = [i for i in by_index
             if by_index[i].get('status') == 'ok'
             and by_index[i].get('req_url')
             and (spec_by_index.get(i) or {}).get('ok')
             and i < len(union)]
    random.seed(seed)
    picks = random.sample(picks, min(n, len(picks)))

    ok = 0
    for i in picks:
        s = union[i]
        r = by_index[i]
        spec = spec_by_index[i]['spec']
        url = r['req_url']
        headers = dict(src_headers(s))
        headers.update(spec.get('headers') or {})
        res = fetch(url, r.get('method') or 'GET', body_for(spec, url),
                    headers, 25, None)
        if not res.get('ok'):
            print('  %-26s 请求失败 %s' % (s.get('bookSourceName'), res.get('err')))
            continue
        js, doc = parse_body(res)
        bl = (s.get('ruleSearch') or {}).get('bookList')
        items = rule_items(bl, doc=doc, js=js) or []
        names = []
        for it in items[:2]:
            vals = []
            if js is not None and isinstance(it, dict):
                # JSON 源的书名规则是相对条目求值的（Legado 的做法）
                v = json_path(it, (s.get('ruleSearch') or {}).get('name') or '')
                if isinstance(v, (str, int, float)) and str(v).strip():
                    vals = [str(v)]
                else:
                    try:
                        vals = eval_rule((s.get('ruleSearch') or {}).get('name'),
                                         js=js, item=it)
                    except Exception:
                        vals = []
            else:
                try:
                    vals = eval_rule((s.get('ruleSearch') or {}).get('name'),
                                     doc=doc, js=js, item=it)
                except Exception:
                    vals = []
            names.append(next((x for x in vals if isinstance(x, str) and x.strip()), ''))
        good = bool(items) and any(n.strip() for n in names)
        ok += 1 if good else 0
        print('  %-26s %-4s 条目=%-3d 书名=%-20s %s' % (
            s.get('bookSourceName'), (r.get('method') or 'GET'),
            len(items), (names[0] if names else '')[:20],
            '✓' if good else '✗'))
    print('\n抽样 %d 条，书名正常 %d 条' % (len(picks), ok))


if __name__ == '__main__':
    main()
