# -*- coding: utf-8 -*-
"""对最终合集做抽样实测：用产出的规则真打一次搜索接口（开发辅助脚本）。"""
import json
import random
import sys
import urllib.parse

sys.path.insert(0, '.')
from legado_validator.engine import eval_rule, rule_items  # noqa: E402
from legado_validator.http import fetch  # noqa: E402
from legado_validator.rules import parse_body, src_headers  # noqa: E402

KW = '修真'


def build_url(src, base):
    raw = str(src.get('searchUrl') or '').strip()
    if not raw or raw.startswith('@js:') or '<js>' in raw:
        return None
    url = raw.replace('{{key}}', urllib.parse.quote(KW))
    url = url.replace('{{bookName}}', urllib.parse.quote(KW))
    url = url.replace('{{page}}', '1').replace('{{pageIndex}}', '1')
    if url.startswith('//'):
        return 'https:' + url
    if url.startswith('http'):
        return url
    return base.rstrip('/') + '/' + url.lstrip('/')


def main():
    path = sys.argv[1]
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 6
    data = json.load(open(path, encoding='utf-8'))
    cand = [s for s in data if s.get('ruleSearch', {}).get('bookList')]
    random.seed(int(sys.argv[3]) if len(sys.argv) > 3 else 7)
    picks = random.sample(cand, min(n, len(cand)))
    ok = 0
    for s in picks:
        base = s.get('bookSourceUrl') or ''
        url = build_url(s, base)
        if not url:
            print('  跳过（JS 规则）: %s' % s.get('bookSourceName'))
            continue
        res = fetch(url, 'GET', None, src_headers(s), 25, None)
        if not res.get('ok'):
            print('  请求失败 %-22s %s' % (s.get('bookSourceName'), res.get('err')))
            continue
        js, doc = parse_body(res)
        items = rule_items(s['ruleSearch']['bookList'], doc=doc, js=js) or []
        names = []
        for it in items[:2]:
            try:
                v = eval_rule(s['ruleSearch'].get('name'), doc=doc, js=js, item=it)
            except Exception:
                v = []
            names.append(next((x for x in v if isinstance(x, str) and x.strip()), ''))
        good = bool(items) and all(n.strip() for n in names[:1])
        ok += 1 if good else 0
        print('  %-24s http=%-4s 条目=%-3d 书名=%s %s' % (
            s.get('bookSourceName'), res.get('status'), len(items),
            (names[0] if names else '')[:22], '✓' if good else '✗'))
    print('\n抽样 %d 条，可用 %d 条' % (len(picks), ok))


if __name__ == '__main__':
    main()
