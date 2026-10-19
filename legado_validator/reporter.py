# -*- coding: utf-8 -*-
"""生成 Markdown 校验报告。"""
import os
from collections import Counter

from .merger import ACCESS_DESC, QUALITY_DESC

QUALITY_ORDER = ('verified', 'weak', 'alive', 'api_quirk', 'antibot', 'unverified')
ACCESS_ORDER = ('both', 'cn_only', 'overseas_only', 'unverified')


def build_report(sources, kept, removed, servers):
    """生成报告正文。"""
    quality = Counter(s.get('_validation', {}).get('quality') for s in kept)
    access = Counter(s.get('_validation', {}).get('access') for s in kept)
    lines = []
    lines.append('# Legado 书源校验报告')
    lines.append('')
    lines.append('- 原始书源总数：%d' % len(sources))
    lines.append('- 保留（至少一个节点可访问）：%d' % len(kept))
    lines.append('- 剔除（所有节点均不可用）：%d' % len(removed))
    lines.append('- 校验节点：%s' % '、'.join(servers))
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
    return '\n'.join(lines)


def write_report(text, path):
    with open(path, 'w', encoding='utf-8') as fh:
        fh.write(text)
    return path
