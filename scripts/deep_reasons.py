# -*- coding: utf-8 -*-
"""统计 deep check 失败原因对应的规则写法（开发辅助脚本）。"""
import json
import sys
from collections import Counter

with open(sys.argv[1], encoding='utf-8') as fh:
    res = json.load(fh)
with open(sys.argv[2], encoding='utf-8') as fh:
    src = json.load(fh)

reason = sys.argv[3] if len(sys.argv) > 3 else 'no_book_url'
by_index = dict((x['i'], x) for x in res)

c = Counter()
samples = []
for i, x in by_index.items():
    if x['status'] != 'ok':
        continue
    if (x.get('deep') or {}).get('reason') != reason:
        continue
    s = src[i]
    bu = (s.get('ruleSearch') or {}).get('bookUrl')
    c[str(bu)[:60]] += 1
    if len(samples) < 12:
        samples.append((s.get('bookSourceName'), s.get('bookSourceUrl'), bu,
                        (s.get('ruleSearch') or {}).get('bookList')))
print('原因 %s 共 %d 条' % (reason, sum(c.values())))
for k, v in c.most_common(15):
    print('  %-62s %d' % (k, v))
print()
for n, u, bu, bl in samples:
    print('  %-26s %-34s' % (n, u))
    print('     bookList: %s' % str(bl)[:80])
    print('     bookUrl : %s' % str(bu)[:80])
