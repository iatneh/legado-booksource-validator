# -*- coding: utf-8 -*-
"""生成 Markdown 校验报告。"""
import os
from collections import Counter

from .merger import ACCESS_DESC, QUALITY_DESC

QUALITY_ORDER = ('verified', 'weak', 'alive', 'api_quirk', 'antibot', 'unverified')
ACCESS_ORDER = ('both', 'cn_only', 'overseas_only', 'unverified')


def build_report(sources, kept, removed, servers, groups=None, extra=None,
                 duplicates=None):
    """生成报告正文。"""
    quality = Counter(s.get('_validation', {}).get('quality') for s in kept)
    access = Counter(s.get('_validation', {}).get('access') for s in kept)
    duplicates = duplicates or []
    lines = []
    lines.append('# Legado 书源校验报告')
    lines.append('')
    lines.append('- 原始书源总数：%d' % len(sources))
    lines.append('- 保留（至少一个节点可访问）：%d' % len(kept))
    lines.append('- 剔除（所有节点均不可用）：%d' % len(removed))
    if duplicates:
        lines.append('- 剔除（与其它书源功能重复）：%d' % len(duplicates))
    lines.append('- 校验节点：%s' % '、'.join(servers))
    for note in (extra or []):
        lines.append('- %s' % note)
    lines.append('')
    lines.append('## 保留书源质量分布')
    lines.append('')
    lines.append('| 分类 | 数量 | 含义 |')
    lines.append('| --- | --- | --- |')
    for key in QUALITY_ORDER:
        if quality.get(key):
            lines.append('| %s | %d | %s |' % (key, quality[key],
                                              QUALITY_DESC.get(key, '')))
    lines.append('')
    lines.append('## 访问范围分布')
    lines.append('')
    lines.append('| 范围 | 数量 | 含义 |')
    lines.append('| --- | --- | --- |')
    for key in ACCESS_ORDER:
        if access.get(key):
            lines.append('| %s | %d | %s |' % (key, access[key],
                                              ACCESS_DESC.get(key, '')))
    lines.append('')
    if groups:
        lines.append('## 标签分布（重新组织后）')
        lines.append('')
        lines.append('| 标签组合 | 数量 |')
        lines.append('| --- | --- |')
        for g, n in sorted(groups.items(), key=lambda kv: -kv[1]):
            lines.append('| %s | %d |' % (g, n))
        lines.append('')
    for key, title in (('cn_only', '仅国内可访问（cn_only）'),
                       ('overseas_only', '仅海外可访问（overseas_only，需外网）')):
        picked = [s for s in kept if s.get('_validation', {}).get('access') == key]
        lines.append('## %s' % title)
        lines.append('')
        lines.append('共 %d 个' % len(picked))
        lines.append('')
        lines.append('| 书源 | 站点 | %s |' % ' | '.join(servers))
        lines.append('| --- | --- | %s |' % ' | '.join(['---'] * len(servers)))
        for s in picked:
            v = s['_validation']
            cells = []
            for name in servers:
                cells.append(str(v.get('servers', {}).get(name, {}).get('status', '')))
            lines.append('| %s | %s | %s |' % (
                s.get('bookSourceName', ''), s.get('bookSourceUrl', ''),
                ' | '.join(cells)))
        lines.append('')
    repaired = [s for s in kept if s.get('_repaired')]
    if repaired:
        lines.append('## 已修复书源（站点存活但选择器过时）')
        lines.append('')
        lines.append('共 %d 个' % len(repaired))
        lines.append('')
        lines.append('| 书源 | 站点 | 修复节点 | 命中条目 | 新 bookList |')
        lines.append('| --- | --- | --- | --- | --- |')
        for s in repaired:
            d = s.get('_repaired') or {}
            lines.append('| %s | %s | %s | %s | `%s` |' % (
                s.get('bookSourceName', ''), s.get('bookSourceUrl', ''),
                s.get('_repaired_on', ''), d.get('items', ''),
                (s.get('ruleSearch') or {}).get('bookList', '')))
        lines.append('')
    explored = [s for s in kept if s.get('_explore_fixed')]
    if explored:
        lines.append('## 已补全发现页规则的书源')
        lines.append('')
        lines.append('共 %d 个' % len(explored))
        lines.append('')
        lines.append('| 书源 | 站点 | 补全方式 | 命中条目 |')
        lines.append('| --- | --- | --- | --- |')
        for s in explored:
            d = s.get('_explore_fixed') or {}
            lines.append('| %s | %s | %s | %s |' % (
                s.get('bookSourceName', ''), s.get('bookSourceUrl', ''),
                d.get('method', ''), d.get('items', '')))
        lines.append('')
    lines.append('## 已剔除书源（所有节点均不可用）')
    lines.append('')
    lines.append('共 %d 个' % len(removed))
    lines.append('')
    lines.append('| 书源 | 站点 | %s |' % ' | '.join(servers))
    lines.append('| --- | --- | %s |' % ' | '.join(['---'] * len(servers)))
    for r in removed:
        cells = [str(r.get('reason', {}).get(name, '')) for name in servers]
        lines.append('| %s | %s | %s |' % (
            r.get('bookSourceName', ''), r.get('bookSourceUrl', ''),
            ' | '.join(cells)))
    if duplicates:
        lines.append('')
        lines.append('## 已剔除书源（与其它书源功能重复）')
        lines.append('')
        lines.append('共 %d 个，判据为搜索端点（host + path）完全相同，保留功能更全的一条。'
                     % len(duplicates))
        lines.append('')
        lines.append('| 剔除的书源 | 站点 | 同一端点 | 保留为 |')
        lines.append('| --- | --- | --- | --- |')
        for r in duplicates:
            lines.append('| %s | %s | %s | %s |' % (
                r.get('bookSourceName', ''), r.get('bookSourceUrl', ''),
                r.get('searchEndpoint', ''), r.get('keptAs', '')))
    return '\n'.join(lines)


def write_report(text, path):
    with open(path, 'w', encoding='utf-8') as fh:
        fh.write(text)
    return path
