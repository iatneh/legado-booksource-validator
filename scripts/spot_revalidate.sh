#!/usr/bin/env bash
# 在节点上对抽样下标重跑真实校验，确认产出仍然有效
set -euo pipefail
cd /tmp/legado-v10
python3 - <<'PY'
import json, random
r = json.load(open('res_aliyun.json'))
picks = [x['i'] for x in r if x.get('status') == 'ok' and x.get('req_url')]
random.seed(11)
picks = random.sample(picks, 16)
open('spot_idx.txt', 'w').write(','.join(map(str, picks)))
print('idx:', ','.join(map(str, picks)))
PY
IDX=$(cat spot_idx.txt)
python3 -m legado_validator validate --src final_union.json --spec spec_aliyun.json \
  --out res_spot.json --server aliyun --threads 6 --timeout 25 --only "$IDX" 2>&1 | tail -4
python3 - <<'PY'
import json
r = json.load(open('res_spot.json'))
u = json.load(open('final_union.json'))
for x in r:
    print('  %-26s %-12s items=%s' % (u[x['i']].get('bookSourceName'),
                                       x.get('status'), x.get('items')))
PY
