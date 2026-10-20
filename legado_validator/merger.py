# -*- coding: utf-8 -*-
"""多节点结果合并：取合集、剔除两台都不通的源、给书源打访问范围标签。"""
import json
import os
from collections import Counter

from . import tags

DEAD = {'net_error', 'http_error', 'no_rule'}
ALIVE = {'ok', 'weak', 'nores', 'blocked', 'api_quirk'}
UNVERIFIED = {'unsupported', 'error', 'unknown', 'missing'}

TAGS = {'overseas_only': '🌍需外网', 'cn_only': '🇨🇳仅国内', 'both': '🌐全球可用'}

QUALITY_DESC = {
    'verified': '搜索接口真实返回书单条目（已实测可用）',
    'weak': '站点存活、页面可读，但规则含 JS/特殊语法未能解析出条目',
    'alive': '站点存活并返回 200，但搜索无结果条目（可能软封禁或规则失效）',
    'api_quirk': '接口返回 4xx（签名/参数类错误），站点存活但本次请求格式未完全还原',
    'antibot': '站点存活但触发反爬（403/验证码/挑战页）',
    'unverified': '规则为 JS 聚合型，静态无法解析，未作判定',
}

ACCESS_DESC = {
    'both': '两台服务器都能访问',
    'cn_only': '只有国内节点能访问',
    'overseas_only': '只有海外节点能访问（需外网）',
    'unverified': '无法判定（规则未能解析）',
}


def classify(status_a, status_b):
    """给出 (verdict, access, quality)。

    verdict: keep / invalid —— 只有两台都硬失败才判 invalid。
    access : both / cn_only / overseas_only / unverified
    quality: verified / weak / alive / api_quirk / antibot / unverified
    """
    a_alive = status_a in ALIVE
    b_alive = status_b in ALIVE
    a_dead = status_a in DEAD
    b_dead = status_b in DEAD
    if status_a == 'ok' or status_b == 'ok':
        quality = 'verified'
    elif status_a == 'weak' or status_b == 'weak':
        quality = 'weak'
    elif status_a == 'nores' or status_b == 'nores':
        quality = 'alive'
    elif status_a == 'api_quirk' or status_b == 'api_quirk':
        quality = 'api_quirk'
    elif status_a == 'blocked' or status_b == 'blocked':
        quality = 'antibot'
    else:
        quality = 'unverified'
    if a_dead and b_dead:
        access = 'none'
    elif a_alive and b_alive:
        access = 'both'
    elif a_alive:
        access = 'cn_only'
    elif b_alive:
        access = 'overseas_only'
    elif status_a in UNVERIFIED and status_b in UNVERIFIED:
        access = 'unverified'
    elif a_dead or b_dead:
        access = 'unverified'
    else:
        access = 'none'
    verdict = 'invalid' if access == 'none' else 'keep'
    return verdict, access, quality


def _tag_note(access, info):
    if access == 'overseas_only':
        return '[%s] 需外网访问：国内节点 %s；海外节点 %s' % (
            TAGS[access], info['cn']['status'], info['overseas']['status'])
    if access == 'cn_only':
        return '[%s] 仅国内可访问：海外节点 %s；国内节点 %s' % (
            TAGS[access], info['overseas']['status'], info['cn']['status'])
    return ''


def merge(sources, results_by_server, cn_server=None, overseas_server=None,
          overrides_by_server=None, drop_keys=None):
    """合并多节点结果。

    results_by_server: {server_name: [result dict, ...]}
    overrides_by_server: {server_name: {index: result}} —— 修复后重测的结果，
                         优先级高于 results_by_server（只覆盖同下标的条目）
    cn_server / overseas_server: 用于生成标签文案的节点名（可自动推断）
    drop_keys: {(书源名, 书源地址)} —— 重复书源清单，这些源不进入任何产出
    """
    servers = list(results_by_server.keys())
    if cn_server is None:
        cn_server = servers[0] if servers else 'cn'
    if overseas_server is None:
        overseas_server = servers[-1] if len(servers) > 1 else cn_server
    # 传了结果集里不存在的节点名（手滑写错）时退回默认：
    # 否则该侧会被当成"死节点"，极端情况下整轮书源被误判成两台都死。
    if servers:
        if cn_server not in servers:
            cn_server = servers[0]
        if overseas_server not in servers:
            overseas_server = servers[-1]
    drop_keys = drop_keys or {}
    if not isinstance(drop_keys, dict):
        drop_keys = dict((k, None) for k in drop_keys)
    index = {}
    for name, results in results_by_server.items():
        index[name] = dict((r.get('i'), r) for r in results)
    for name, over in (overrides_by_server or {}).items():
        index.setdefault(name, {}).update(over)
    kept, removed, overseas, verified = [], [], [], []
    cn_only, by_group = [], Counter()
    dropped = []
    stats = Counter()
    for i, source in enumerate(sources):
        key = (source.get('bookSourceName'), source.get('bookSourceUrl'))
        if key in drop_keys:
            record = drop_keys[key] or {}
            entry = {
                'bookSourceName': source.get('bookSourceName'),
                'bookSourceUrl': source.get('bookSourceUrl'),
            }
            for k, v in record.items():
                if k not in ('bookSourceName', 'bookSourceUrl'):
                    entry[k] = v
            dropped.append(entry)
            continue
        info = {}
        for name in servers:
            r = index.get(name, {}).get(i, {})
            info[name] = {
                'status': r.get('status', 'missing'),
                'http': r.get('http'),
                'ms': r.get('ms'),
                'items': r.get('items'),
                'err': r.get('err'),
                'block': r.get('block'),
                'deep': (r.get('deep') or {}).get('content'),
            }
        # cn_server / overseas_server 允许指向不在结果集里的名字（例如手滑写错），
        # 缺失时按 "missing" 处理，而不是直接 KeyError 崩掉整轮合并。
        status_a = (info.get(cn_server) or {}).get('status', 'missing')
        status_b = (info.get(overseas_server) or {}).get('status', 'missing')
        verdict, access, quality = classify(status_a, status_b)
        stats['verdict_' + verdict] += 1
        stats['access_' + access] += 1
        stats['quality_' + quality] += 1
        payload = {
            'verdict': verdict,
            'access': access,
            'quality': quality,
            'servers': info,
        }
        if verdict != 'keep':
            removed.append({
                'bookSourceName': source.get('bookSourceName'),
                'bookSourceUrl': source.get('bookSourceUrl'),
                'bookSourceGroup': source.get('bookSourceGroup'),
                'reason': dict((n, info[n]['status']) for n in servers),
            })
            continue
        item = dict(source)
        # ---- 标签重构：内容分类 + 访问范围 + 质量状态 ----
        new_group = tags.build_groups(item, access, quality)
        item['bookSourceGroup'] = new_group
        payload['tags'] = new_group.split(',')
        payload['group_before'] = source.get('bookSourceGroup')
        by_group[new_group] += 1
        note = _tag_note(access, {
            'cn': info.get(cn_server) or {'status': 'missing'},
            'overseas': info.get(overseas_server) or {'status': 'missing'},
        })
        comment = str(item.get('bookSourceComment') or '')
        if note and note not in comment:
            item['bookSourceComment'] = (note + '\n' + comment).strip()
        if access == 'overseas_only':
            overseas.append(item)
        elif access == 'cn_only':
            cn_only.append(item)
        item['_validation'] = payload
        kept.append(item)
        if quality == 'verified':
            verified.append(item)
    return {
        'kept': kept,
        'removed': removed,
        'dropped': dropped,
        'overseas': overseas,
        'cn_only': cn_only,
        'verified': verified,
        'stats': stats,
        'groups': by_group,
    }


def write_outputs(result, out_dir):
    """写出合集 / 严格可用集 / 需外网集 / 仅国内集 / 剔除清单。"""
    os.makedirs(out_dir, exist_ok=True)
    paths = {}
    targets = (
        ('final_union.json', result['kept']),
        ('final_verified.json', result['verified']),
        ('needs_overseas.json', result['overseas']),
        ('cn_only.json', result.get('cn_only') or []),
        ('removed_invalid.json', result['removed']),
        ('removed_duplicates.json', result.get('dropped') or []),
    )
    for name, data in targets:
        path = os.path.join(out_dir, name)
        with open(path, 'w', encoding='utf-8') as fh:
            json.dump(data, fh, ensure_ascii=False, indent=1)
        paths[name] = path
    # 标签分布
    groups = result.get('groups') or {}
    path = os.path.join(out_dir, 'tag_distribution.json')
    with open(path, 'w', encoding='utf-8') as fh:
        json.dump(dict(sorted(groups.items(), key=lambda kv: -kv[1])),
                  fh, ensure_ascii=False, indent=1)
    paths['tag_distribution.json'] = path
    return paths
