# -*- coding: utf-8 -*-
"""书源去重：找出功能重复的书源并剔除，只保留其中最完整的一条。

怎么算「重复」
--------------
Legado 以 ``bookSourceUrl`` 作书源主键，同键的会互相覆盖；但同一站点
经常被拆成几条书源（换域名、换 http/https、换锚点备注），主键不同所以
能共存，用起来却是同一个站，列表里还多出好几条同名条目。

判定规则
--------

* **规则 A（主）**：把 ``searchUrl`` 解析成实际搜索端点（host + path），
  端点完全相同即视为同站重复。
  端点来源优先级：**JS 解析器还原的真实请求地址** > 静态规则解析。
  真实地址由 ``legado_validator resolve`` 在目标节点本机跑出（``@js:``
  这类静态解析不出的规则也能还原出实际打的接口）。
* **规则 B（辅）**：完全拿不到端点的书源，若主域名相同、书源名归一化后
  也相同，同样视为重复。

关键词会被从端点里抹掉（``{kw}``），保证端点只反映"打的是哪个接口"，
不受搜索词影响。

保留哪一条
----------
按「质量等级 → 规则完整度 → 主域名是否与搜索端点一致 → 有无发现页 →
更新时间」打分，分高者保留；完全同分时保留序号靠前的那条，保证结果稳定
可复现。

同名但不同站的**不会**被删（笔趣阁、顶点小说这类是几十个不同域名的
镜像站，删了会丢真实可用的站），只会在报告里列出来。
"""
import argparse
import json
import os
import re
import sys
from collections import defaultdict
from urllib.parse import quote, urljoin, urlsplit

QUALITY_SCORE = {
    'verified': 5, 'alive': 4, 'weak': 3, 'antibot': 3, 'api_quirk': 2,
    'unverified': 1,
}
EMOJI_RE = re.compile(
    '[\U0001F000-\U0001FAFF\U00002600-\U000027BF\U0001F1E6-\U0001F1FF☀-➿️]+')
NOTE_RE = re.compile(r'[（(\[【].*?[)）\]】]')

RESOLVED = {}      # (书源名, 归一化主地址) -> 真实搜索端点（host+path）


def base_norm(url):
    """归一化主地址：去掉 ##备注 / #锚点，补上 https://。

    解析规格里记的是归一化后的 base，用它和书源对齐。
    """
    u = str(url or '').strip().split('##')[0].split('#')[0].strip()
    if not u:
        return ''
    if not u.startswith('http'):
        u = 'https://' + u
    return u


def src_key(src):
    """书源在解析规格里的对应键。"""
    return (src.get('bookSourceName') or '', base_norm(src.get('bookSourceUrl')))


def base_of(src):
    """书源主地址（去掉 ##备注 / #锚点）。"""
    u = (src.get('bookSourceUrl') or '').strip()
    u = u.split('##')[0].split('#')[0].strip()
    if not u:
        return ''
    if not u.startswith('http'):
        u = 'https://' + u
    return u


def host_of(u):
    try:
        h = urlsplit(u).netloc.lower()
    except ValueError:
        return ''
    return h[4:] if h.startswith('www.') else h


def mask_kw(u, kw='修真'):
    """把搜索关键词从地址里抹掉，端点只反映"打的是哪个接口"。"""
    if not kw:
        return u
    for pat in (quote(kw, safe=''), kw):
        if pat:
            u = u.replace(pat, '{kw}')
    return u


PLACEHOLDER_RE = re.compile(r'\{\{\s*([a-zA-Z_][\w]*)\s*\}\}')


def norm_placeholder(u):
    """把 ``{{key}}`` / ``{{page}}`` 这类占位符归一化。

    静态规则里是 ``{{key}}``，解析器还原后是真实关键词，两边要能对上，
    所以统一成 ``{kw}`` / ``{pg}``。
    """
    def _sub(m):
        key = m.group(1).lower()
        if key in ('key', 'keyword', 'bookname', 'skey', 'q'):
            return '{kw}'
        if key in ('page', 'pageindex', 'pn'):
            return '{pg}'
        return '{p}'
    return PLACEHOLDER_RE.sub(_sub, u)


def endpoint_of(u, kw='修真'):
    """地址 -> 规范端点（host + path，丢掉 query 与 www. 前缀）。"""
    if not u:
        return ''
    try:
        p = urlsplit(norm_placeholder(mask_kw(u, kw)))
    except ValueError:
        return ''
    h = p.netloc.lower()
    if h.startswith('www.'):
        h = h[4:]
    return (h + (p.path or '/').rstrip('/')).lower()


def static_endpoint(src, kw='修真'):
    """静态解析 searchUrl 得到的端点；解析不出来返回空串。"""
    raw = src.get('searchUrl')
    if not raw:
        return ''
    txt = str(raw).strip()
    if txt.startswith('@js:') or txt.startswith('<js>'):
        return ''
    first = txt.split('\n')[0]
    first = first.split('::')[-1] if '::' in first else first
    first = first.split(',')[0].strip()
    m = re.search(r'https?://[^\s"\'<>,)]+', first)
    if m:
        return endpoint_of(m.group(0), kw)
    base = base_of(src)
    if first.startswith('/') and base:
        try:
            return endpoint_of(urljoin(base, first), kw)
        except ValueError:
            return ''
    return ''


def search_endpoint(src, index=None, kw='修真'):
    """实际搜索端点；解析不出来时返回空串。

    优先使用 JS 解析器还原出的真实请求地址（``legado_validator resolve``
    的产物，节点本机跑出），它能还原 ``@js:`` 规则实际打的接口。
    """
    ep = RESOLVED.get(src_key(src))
    if ep:
        return ep
    return static_endpoint(src, kw)


def endpoint_source(src, index=None, kw='修真'):
    """端点是从哪来的：resolved / static / none。"""
    if RESOLVED.get(src_key(src)):
        return 'resolved'
    return 'static' if static_endpoint(src, kw) else 'none'


def norm_name(src):
    """归一化书源名：去 emoji、去括号备注、去空白。"""
    n = EMOJI_RE.sub('', src.get('bookSourceName') or '')
    n = NOTE_RE.sub('', n)
    n = n.replace('#', '').replace('·', '').replace('🎃', '')
    return re.sub(r'\s+', '', n).strip()


def rule_fill(src):
    """规则里非空字段的总数：规则越完整越该保留。"""
    n = 0
    for f in ('ruleSearch', 'ruleExplore', 'ruleBookInfo', 'ruleToc', 'ruleContent'):
        v = src.get(f)
        if isinstance(v, dict):
            n += sum(1 for x in v.values() if x not in (None, '', {}, []))
    return n


def has_explore(src):
    """有没有可用的发现页：exploreUrl 非空且 ruleExplore 有内容。"""
    if not (src.get('exploreUrl') or '').strip():
        return False
    d = src.get('ruleExplore') or {}
    if not isinstance(d, dict):
        return bool(d)
    return any(v not in (None, '', {}, []) for v in d.values())


def is_clean(src):
    """书源标识是否干净：主地址无 #/## 备注，书源名无括号备注。"""
    url = (src.get('bookSourceUrl') or '')
    if '#' in url:
        return False
    name = src.get('bookSourceName') or ''
    return not re.search(r'[（(\[【]', name)


def score(src, index=None, kw='修真'):
    """保留优先级打分。"""
    v = src.get('_validation') or {}
    s = QUALITY_SCORE.get(v.get('quality'), 1) * 10
    s += min(rule_fill(src), 20)        # 规则越完整越该保留
    base_h = host_of(base_of(src))
    ep = search_endpoint(src, index, kw)
    if ep and base_h:
        ep_h = ep.split('/')[0]
        if ep_h == base_h:
            s += 3                       # 主域名与搜索端点完全一致
        elif ep_h.endswith('.' + base_h):
            s += 2                       # 搜索端点是主域名的子域
    if is_clean(src):
        s += 2                           # 没有锚点/备注包袱
    if has_explore(src):
        s += 4                           # 有可用的发现页，功能更全
    up = src.get('lastUpdateTime') or 0
    if isinstance(up, str):
        up = 0
    s += min(int(up), 9)
    return s


def find_groups(sources, kw='修真'):
    """返回 [[源下标, ...], ...]，每组是互相重复的书源。"""
    by_ep = defaultdict(list)
    by_name = defaultdict(list)
    for i, src in enumerate(sources):
        ep = search_endpoint(src, i, kw)
        if ep:
            by_ep[ep].append(i)
        else:
            h = host_of(base_of(src))
            nm = norm_name(src)
            if h and nm:
                by_name[(h, nm)].append(i)
    groups = [v for v in by_ep.values() if len(v) > 1]
    groups += [v for v in by_name.values() if len(v) > 1]
    return groups


def load_resolved(paths, sources, kw='修真'):
    """读取节点解析规格，建立 (书源名, 主地址) -> 真实端点 的映射。

    按**键**对齐而不是按下标：解析规格通常是对完整书源列表解析的，而
    去重跑在保留子集上，下标根本对不上。

    多个节点的规格若对同一条给出不同端点（JS 规则依赖出口环境），记为
    冲突并采用先到的那个，冲突条目会在报告里单列。
    """
    global RESOLVED
    RESOLVED = {}
    conflicts = []
    wanted = set(src_key(s) for s in sources)
    for path in paths:
        if not os.path.exists(path):
            print('  ! 解析规格不存在，跳过：%s' % path)
            continue
        with open(path, encoding='utf-8') as fh:
            data = json.load(fh)
        hit = 0
        for e in data:
            spec = e.get('spec') or {}
            u = spec.get('url')
            if not u:
                continue
            key = (e.get('name') or '', base_norm(e.get('base')))
            if wanted and key not in wanted:
                continue
            ep = endpoint_of(u, kw)
            if not ep:
                continue
            hit += 1
            if key in RESOLVED and RESOLVED[key] != ep:
                conflicts.append((key, RESOLVED[key], ep, path))
            RESOLVED.setdefault(key, ep)
        print('  - %s: 还原真实端点 %d 条' % (os.path.basename(path), hit))
    for key, a, b, path in conflicts:
        print('  ! 端点冲突 %s: %s vs %s（来自 %s）' % (key[0], a, b, os.path.basename(path)))
    return conflicts


def main():
    ap = argparse.ArgumentParser(description='剔除功能重复的书源')
    ap.add_argument('--src', required=True, help='final_union.json')
    ap.add_argument('--out-dir', required=True, help='输出目录')
    ap.add_argument('--spec', action='append', default=[],
                    help='节点解析规格 JSON（可重复），给出真实搜索端点')
    ap.add_argument('--kw', default='修真', help='解析时用的搜索关键词')
    ap.add_argument('--report', action='store_true', help='额外输出重复组详情')
    args = ap.parse_args()

    with open(args.src, encoding='utf-8') as fh:
        sources = json.load(fh)

    if args.spec:
        print('载入节点解析规格：')
        load_resolved(args.spec, sources, args.kw)

    groups = find_groups(sources, args.kw)
    drop = set()
    removed = []
    print('\n总书源 %d 条，检出 %d 组重复' % (len(sources), len(groups)))
    for g in groups:
        g = sorted(g, key=lambda i: (-score(sources[i], i, args.kw), i))
        keeper = g[0]
        ep = search_endpoint(sources[keeper], keeper, args.kw)
        src_kind = endpoint_source(sources[keeper], keeper, args.kw)
        print('\n组：%s  (%d 条，判据=%s)' % (ep or ('主域名+同名:' + host_of(base_of(sources[keeper]))),
                                          len(g), src_kind))
        for i in g:
            s = sources[i]
            mark = '保留' if i == keeper else '剔除'
            print('   [%s] %-24s url=%-40s 分=%d 质量=%s 规则字段=%d'
                  % (mark, s.get('bookSourceName'),
                     (s.get('bookSourceUrl') or '')[:38], score(s, i, args.kw),
                     (s.get('_validation') or {}).get('quality'), rule_fill(s)))
            if i != keeper:
                drop.add(i)
                removed.append({
                    'bookSourceName': s.get('bookSourceName'),
                    'bookSourceUrl': s.get('bookSourceUrl'),
                    'searchEndpoint': ep,
                    'endpointSource': endpoint_source(s, i, args.kw),
                    'keptAs': sources[keeper].get('bookSourceName'),
                    'keptUrl': sources[keeper].get('bookSourceUrl'),
                    'reason': '与 %s 指向同一搜索端点，规则功能重复'
                              % sources[keeper].get('bookSourceName'),
                })

    kept = [s for i, s in enumerate(sources) if i not in drop]
    out_dir = args.out_dir
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, 'final_union_dedup.json'), 'w', encoding='utf-8') as fh:
        json.dump(kept, fh, ensure_ascii=False, indent=1)
    with open(os.path.join(out_dir, 'removed_duplicates.json'), 'w', encoding='utf-8') as fh:
        json.dump(removed, fh, ensure_ascii=False, indent=1)
    print('\n保留 %d 条，剔除重复 %d 条' % (len(kept), len(drop)))
    print('输出 %s/final_union_dedup.json、%s/removed_duplicates.json'
          % (out_dir, out_dir))
    return 0


if __name__ == '__main__':
    sys.exit(main())
