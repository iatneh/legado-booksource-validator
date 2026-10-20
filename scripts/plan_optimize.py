# -*- coding: utf-8 -*-
"""规划优化任务的下标清单。

把校验结果分成两类活：

* **搜索层修复**（``repair``）：搜索页能打开但规则取不到条目（weak /
  nores / alive），或者能取到条目但书名是空的。
* **深链层修复**（``deep-repair``）：搜索正常，但目录取不到章节
  （no_toc_items）、正文取不到字（empty_content）等。

按可达性分流：只有国内能访问的交给 aliyun，其余交给 rack-nerd。
输出纯下标列表，给两个节点的 ``--only`` 用。
"""
import argparse
import json
import os
from collections import Counter

SEARCH_BAD = ('weak', 'nores', 'alive')
DEEP_BAD = ('no_toc_items', 'empty_content', 'no_chapter_url',
            'no_chapter_url_rule', 'content_fetch_failed')


def load_results(paths):
    """按下标汇总各节点的结果（后读到的覆盖先读到的）。"""
    out = {}
    for p in paths:
        if not os.path.exists(p):
            continue
        with open(p, encoding='utf-8') as fh:
            for e in json.load(fh):
                out.setdefault(e.get('i'), {})[e.get('server') or p] = e
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--union', required=True, help='final_union.json（打标签后的保留集）')
    ap.add_argument('--patched', required=True, help='patched.json（原始顺序）')
    ap.add_argument('--result', action='append', required=True, help='节点结果文件')
    ap.add_argument('--out-dir', required=True)
    args = ap.parse_args()

    with open(args.union, encoding='utf-8') as fh:
        union = json.load(fh)
    with open(args.patched, encoding='utf-8') as fh:
        patched = json.load(fh)
    results = load_results(args.result)

    # union 下标 -> patched 下标（union 是 patched 的子序列）
    m = {}
    pi = 0
    for ui, s in enumerate(union):
        while pi < len(patched):
            if (patched[pi].get('bookSourceUrl'),
                    patched[pi].get('bookSourceName')) == (
                    s.get('bookSourceUrl'), s.get('bookSourceName')):
                m[ui] = pi
                pi += 1
                break
            pi += 1
        else:
            print('警告：union 第 %d 条在 patched 里找不到对应项' % ui)
    inv = {v: k for k, v in m.items()}

    cn_only = set()
    for ui, s in enumerate(union):
        access = (s.get('_validation') or {}).get('access')
        if access == 'cn_only':
            cn_only.add(m.get(ui))

    search_ali, search_rn = [], []
    deep_ali, deep_rn = [], []
    stat = Counter()
    for pidx, recs in results.items():
        if pidx not in inv:
            continue
        statuses = {r.get('status') for r in recs.values()}
        reasons = {(r.get('deep') or {}).get('reason') for r in recs.values()}
        name_bad = any(r.get('status') == 'ok' and r.get('name_ok') is False
                       for r in recs.values())
        need_search = bool(statuses & set(SEARCH_BAD)) or name_bad
        need_deep = bool(reasons & set(DEEP_BAD))
        if need_search:
            stat['search'] += 1
            (search_ali if pidx in cn_only else search_rn).append(pidx)
        if need_deep:
            stat['deep'] += 1
            (deep_ali if pidx in cn_only else deep_rn).append(pidx)

    os.makedirs(args.out_dir, exist_ok=True)
    files = {
        'search_aliyun': sorted(search_ali),
        'search_rn': sorted(search_rn),
        'deep_aliyun': sorted(deep_ali),
        'deep_rn': sorted(deep_rn),
    }
    for name, idxs in files.items():
        path = os.path.join(args.out_dir, 'opt_%s.txt' % name)
        with open(path, 'w', encoding='utf-8') as fh:
            fh.write(','.join(str(i) for i in idxs))
        print('%-14s %4d 条 -> %s' % (name, len(idxs), path))
    print('\n搜索层待修 %d，深链层待修 %d' % (stat['search'], stat['deep']))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
