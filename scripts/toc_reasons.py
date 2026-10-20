# -*- coding: utf-8 -*-
"""统计 deep check 在"目录"环节失败的规则写法（开发辅助脚本）。"""
import json
import sys
from collections import Counter

with open(sys.argv[1], encoding='utf-8') as fh:
    res = json.load(fh)
with open(sys.argv[2], encoding='utf-8') as fh:
    src = json.load(fh)

by_index = dict((x['i'], x) for x in res)
reason = sys.argv[3] if len(sys.argv) > 3 else 'no_toc_items'
field = sys.argv[4] if len(sys.argv) > 4 else 'chapterList'

c = Counter()
samples = []
for i, x in by_index.items():
    if x['status'] != 'ok':
        continue
    if (x.get('deep') or {}).get('reason') != reason:
        continue
    s = src[i]
    rule = (s.get('ruleToc') or {}).get(field)
    c[str(rule)[:56]] += 1
    if len(samples) < 10:
        samples.append((s.get('bookSourceName'), s.get('bookSourceUrl'),
                        (s.get('ruleToc') or {}).get('chapterList'),
                        (s.get('ruleToc') or {}).get('chapterUrl')))
print('原因 %s（字段 %s）共 %d 条' % (reason, field, sum(c.values())))
for k, v in c.most_common(15):
    print('  %-58s %d' % (k, v))
print()
for n, u, cl, cu in samples:
    print('  %-26s %s' % (n, u))
    print('     chapterList: %s' % str(cl)[:78])
    print('     chapterUrl : %s' % str(cu)[:78])
