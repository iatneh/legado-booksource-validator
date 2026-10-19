# -*- coding: utf-8 -*-
"""多节点结果合并：取合集、剔除两台都不通的源、给书源打访问范围标签。"""
import json
import os
from collections import Counter

DEAD = {'net_error', 'http_error', 'no_rule'}
ALIVE = {'ok', 'weak', 'nores', 'blocked', 'api_quirk'}
UNVERIFIED = {'unsupported', 'error', 'unknown', 'missing'}

TAGS = {'overseas_only': '🌍需外网', 'cn_only': '🇨🇳仅国内'}

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


def merge(sources, results_by_server, cn_server=None, overseas_server=None):
    """合并多节点结果。

    results_by_server: {server_name: [result dict, ...]}
    cn_server / overseas_server: 用于生成标签文案的节点名（可自动推断）
    """
    servers = list(results_by_server.keys())
    if cn_server is None:
        cn_server = servers[0] if servers else 'cn'
    if overseas_server is None:
        overseas_server = servers[-1] if len(servers) > 1 else cn_server
    index = {}
    for name, results in results_by_server.items():
        index[name] = dict((r.get('i'), r) for r in results)
    kept, removed, overseas, verified = [], [], [], []
    stats = Counter()
    for i, source in enumerate(sources):
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
        status_a = info[cn_server]['status']
        status_b = info[overseas_server]['status']
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
        tag = TAGS.get(access)
        if tag:
            payload['tag'] = tag
            group = str(item.get('bookSourceGroup') or '')
            if tag not in group:
                item['bookSourceGroup'] = (group + '·' + tag) if group else tag
            note = _tag_note(access, {'cn': info[cn_server], 'overseas': info[overseas_server]})
            comment = str(item.get('bookSourceComment') or '')
            if note and note not in comment:
                item['bookSourceComment'] = (note + '\n' + comment).strip()
            if access == 'overseas_only':
                overseas.append(item)
        item['_validation'] = payload
        kept.append(item)
        if quality == 'verified':
            verified.append(item)
    return {
        'kept': kept,
        'removed': removed,
        'overseas': overseas,
        'verified': verified,
        'stats': stats,
    }


def write_outputs(result, out_dir):
    """写出合集 / 严格可用集 / 需外网集 / 剔除清单。"""
    os.makedirs(out_dir, exist_ok=True)
    paths = {}
    targets = (
        ('final_union.json', result['kept']),
        ('final_verified.json', result['verified']),
        ('needs_overseas.json', result['overseas']),
        ('removed_invalid.json', result['removed']),
    )
    for name, data in targets:
        path = os.path.join(out_dir, name)
        with open(path, 'w', encoding='utf-8') as fh:
            json.dump(data, fh, ensure_ascii=False, indent=1)
        paths[name] = path
    return paths
