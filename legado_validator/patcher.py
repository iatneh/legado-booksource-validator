# -*- coding: utf-8 -*-
"""把「修复结果」和「发现页补全结果」合并回原始书源列表。

- ``repair`` 产出的书源带有修好的 ``ruleSearch``，按下标覆盖原书源；
- ``explore`` 产出的书源带有补好的 ``ruleExplore``（有时还补了 exploreUrl）。

同一条书源被多个节点修过时，按传入顺序后者优先（保证最终书源里的规则
和后续重测用的规则是同一份，校验结论才自洽）。
"""
import json


def _index_by_orig(sources):
    out = {}
    for i, s in enumerate(sources):
        out[i] = s
    return out


def _load_list(path):
    with open(path, 'r', encoding='utf-8') as fh:
        return json.load(fh)


def patch_sources(sources, repair_files=None, explore_files=None):
    """返回 (打补丁后的书源列表, 统计 dict)。"""
    out = [dict(s) for s in sources]
    stats = {'repair_applied': 0, 'explore_applied': 0, 'deep_applied': 0,
             'repair_sources': 0, 'explore_sources': 0, 'deep_sources': 0}
    repair_files = repair_files or []
    explore_files = explore_files or []
    for path in repair_files:
        rows = _load_list(path)
        stats['repair_sources'] += len(rows)
        for row in rows:
            i = row.get('_orig_index')
            if i is None or not (0 <= i < len(out)):
                continue
            # 搜索层修复：只有真的带 ruleSearch 改动才算数。
            # deep-repair 的产出只带 ruleToc / ruleContent，不能混进这个计数。
            if row.get('ruleSearch'):
                old = out[i].get('ruleSearch') or {}
                new = dict(old)
                new.update(row['ruleSearch'])
                out[i]['ruleSearch'] = new
                stats['repair_applied'] += 1
            if row.get('_repaired'):
                out[i]['_repaired'] = row['_repaired']
            if row.get('_repaired_on'):
                out[i]['_repaired_on'] = row['_repaired_on']
            # 深链修复（deep-repair 产出）：目录 / 正文规则
            touched = False
            for field in ('ruleToc', 'ruleContent'):
                if row.get(field):
                    merged = dict(out[i].get(field) or {})
                    merged.update(row[field])
                    out[i][field] = merged
                    stats['deep_applied'] += 1
                    touched = True
            if touched:
                stats['deep_sources'] += 1
            if row.get('_deep_repaired'):
                out[i]['_deep_repaired'] = row['_deep_repaired']
                out[i]['_deep_repaired_on'] = row.get('_deep_repaired_on')
    for path in explore_files:
        rows = _load_list(path)
        stats['explore_sources'] += len(rows)
        for row in rows:
            i = row.get('_orig_index')
            if i is None or not (0 <= i < len(out)):
                continue
            if row.get('ruleExplore'):
                out[i]['ruleExplore'] = row['ruleExplore']
                stats['explore_applied'] += 1
            if row.get('exploreUrl') and not out[i].get('exploreUrl'):
                out[i]['exploreUrl'] = row['exploreUrl']
            if row.get('_explore_fixed'):
                out[i]['_explore_fixed'] = row['_explore_fixed']
    return out, stats


def write_patched(sources, path):
    with open(path, 'w', encoding='utf-8') as fh:
        json.dump(sources, fh, ensure_ascii=False, indent=1)
    return path
