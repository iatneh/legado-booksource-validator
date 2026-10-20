# -*- coding: utf-8 -*-
"""发现页（explore）规则补全。

书源里发现页由两部分组成：

- ``exploreUrl``  —— 发现页入口列表（分类 / 榜单）
- ``ruleExplore``  —— 发现页的解析规则（bookList / name / author / bookUrl）

实测发现大量书源**只有 exploreUrl、没有 ruleExplore**，在阅读里点进发现页
就是一片空白。这里按两条路径补全：

1. **有 exploreUrl 无 ruleExplore** —— 抓取发现页，用「搜索规则同构」假设
   （发现页和搜索结果页往往是同一套模板）先试 ``ruleSearch`` 的规则；
   试不通再从真实页面结构反推新的选择器。
2. **两者都没有** —— 抓首页，从导航里抠出分类链接生成 exploreUrl，再走 1。

产出的 name/author/bookUrl 统一用**相对书单元素**的 Legacy 链式写法
（``class.title@text``），这是阅读里兼容性最好的形式。
"""
import json
import re

from .http import fetch
from .htmlutil import good_book_url as _good_book_url, usable_link as _usable_link
from .rules import abs_url, norm_base, parse_body, src_headers

# 首页导航里常见的分类路径
CATEGORY_PATH_RE = re.compile(
    r'/(?:category|categories|class|classes|cat|type|types|sort|tag|tags|list|'
    r'booklist|books|genre|channel|folder|section|rank|top|'
    r'xiaoshuo|shuku|book|manga|comic|series|novel|type)(?:/|$|\?)', re.I)

# 分类标题里常出现的词
CATEGORY_TITLE_RE = re.compile(
    r'^(分类|排行|榜单|热门|推荐|最新|完结|完本|连载|免费|全部|书库|小说|'
    r'漫画|轻小说|有声|默认|更多|随机|玄幻|奇幻|武侠|仙侠|修真|都市|科幻|悬疑|'
    r'校园|女生|游戏|军事|历史|同人|二次元|官场|商战|现实|军事|青春|同人|'
    r'轻文|繁体|无弹窗|全文|阅读|小说大全|热门小说|完结小说|免费小说)')

# 分类标题的通用关键词（出现在标题任意位置即可）
CATEGORY_TITLE_KEYWORDS = (
    '分类', '排行', '榜单', '热门', '推荐', '最新', '完结', '完本', '连载',
    '免费', '书库', '全部', '玄幻', '奇幻', '武侠', '仙侠', '修真', '都市',
    '科幻', '悬疑', '校园', '同人', '二次元', '漫画', '轻小说', '有声',
)

# 明显不是分类的标题
NAV_NOISE_RE = re.compile(
    r'(登录|注册|收藏|书架|历史|下载|客户端|APP|关于|联系|首页|返回|'
    r'更多|意见反馈|投稿|QQ|微信|微博|邮箱|帮助|客服|繁体|English|'
    r'上一页|下一页|首页|尾页|首|末)', re.I)

# 看着像"书名"、其实是栏目/导航文字的噪声
NAME_NOISE_RE = re.compile(
    r'(推荐|排行|榜单|热门|更多|首页|上一页|下一页|点击|阅读|全文|目录|'
    r'书友|求票|收藏|投票|举报|广告|返回|顶部|底部|展开|收起|详情|简介)', re.I)


def parse_explore_urls(raw, base=''):
    """把 exploreUrl 解析成 [(title, url), ...]。

    ``@js:`` 形式的 exploreUrl 由阅读端自己执行 JS 生成列表，这里静态
    抓不出结构，但 JS 里通常内嵌了各分类的真实地址，提取出来用于实测。
    """
    raw = str(raw or '').strip()
    if not raw:
        return []
    if raw.startswith('@js:') or '<js>' in raw:
        out = []
        seen = set()
        for m in re.finditer(r'https?://[^\s\'"<>\\)]+', raw):
            u = m.group(0).rstrip('",')
            if u in seen:
                continue
            seen.add(u)
            out.append(('', u))
        return out
    out = []
    if raw[0] in '[{':
        try:
            data = json.loads(raw)
        except Exception:
            data = None
        if isinstance(data, dict):
            data = [data]
        if isinstance(data, list):
            for it in data:
                if isinstance(it, dict):
                    u = str(it.get('url') or it.get('link') or '').strip()
                    t = str(it.get('title') or it.get('name') or '').strip()
                    if u:
                        out.append((t, u))
            return out
    for line in re.split(r'[\n\r]+', raw):
        line = line.strip()
        if not line:
            continue
        if '::' in line:
            t, u = line.split('::', 1)
            t, u = t.strip(), u.strip()
        else:
            t, u = '', line
        if u:
            out.append((t, u))
    return out


def _fill_page(u):
    return re.sub(r'\{\{\s*page[^}]*\}\}', '1', str(u or ''))


def _pick_explore_target(entries, base):
    """挑一个适合实测的发现页入口：优先有标题、URL 绝对的。"""
    for t, u in entries:
        if not t:
            continue
        full = abs_url(base, _fill_page(u))
        if full.startswith('http'):
            return t, full
    for t, u in entries:
        full = abs_url(base, _fill_page(u))
        if full.startswith('http'):
            return t, full
    return None, None


# 明显不是"列表页"的地址（接口/脚本/静态资源）
_NON_PAGE_RE = re.compile(
    r'\.(?:json|js|css|png|jpe?g|gif|svg|ico|xml|txt)(?:$|\?)|'
    r'/api/|/ajax/|\.php\?.*\bjson\b', re.I)


def _candidate_targets(entries, base, limit=4):
    """列出可实测的发现页候选地址，按"像列表页"排序。"""
    out, seen = [], set()
    for t, u in entries:
        full = abs_url(base, _fill_page(u))
        if not full.startswith('http') or full in seen:
            continue
        seen.add(full)
        out.append((t, full))
    ranked = [x for x in out if not _NON_PAGE_RE.search(x[1])]
    ranked += [x for x in out if _NON_PAGE_RE.search(x[1])]
    return ranked[:limit]


# ------------------------------------------------------------ 反推选择器

def propose_explore_candidates(doc, max_items=60):
    """从发现页结构反推候选解析规则（委托给共享的 proposer）。

    产出的 name/author/bookUrl 都是**相对书单元素**的写法。
    """
    from . import proposer
    return proposer.propose_candidates(doc, max_items=max_items)


def build_explore_rule(cand, doc):
    """把候选变成最终 ruleExplore 字典。"""
    from . import proposer
    rule, diag = proposer.build_rule(cand, doc)
    if rule is None:
        return None, diag
    return rule, diag


# -------------------------------------------------- 首页 -> 生成 exploreUrl

def synthesize_explore_urls(doc, base, limit=10):
    """从首页导航里抠分类链接，生成 exploreUrl 条目。"""
    if doc is None:
        return []
    out, seen = [], set()
    for el in doc.iter_desc():
        if el.tag != 'a':
            continue
        href = (el.attrs.get('href') or '').strip()
        if not href or not _usable_link(el):
            continue
        if _good_book_url(href):
            continue
        text = re.sub(r'\s+', ' ', el.text()).strip()
        if not text or len(text) > 10:
            continue
        if NAV_NOISE_RE.search(text):
            continue
        path = href.split('#')[0]
        hit_path = CATEGORY_PATH_RE.search(path)
        hit_title = CATEGORY_TITLE_RE.match(text) or any(
            k in text for k in CATEGORY_TITLE_KEYWORDS)
        if not (hit_path or hit_title):
            continue
        full = abs_url(base, href)
        if not full.startswith('http') or full in seen:
            continue
        if full.rstrip('/') in (base.rstrip('/'), ''):
            continue
        seen.add(full)
        out.append((text, href))
        if len(out) >= limit:
            break
    return out


# ------------------------------------------------------------- 主流程

def _fetch(url, headers, timeout, user_agent=None):
    try:
        res = fetch(url, 'GET', None, headers, timeout, user_agent)
    except Exception:
        return None, None
    if not res.get('ok') or res.get('status', 0) >= 400:
        return res, None
    _js, doc = parse_body(res)
    return res, doc


def _search_rule_as_candidate(src):
    """把 ruleSearch 当作发现页候选（发现页与搜索页常同构）。"""
    from . import proposer
    return proposer.from_search_rule(src)


def supplement_one(src, timeout=25, user_agent=None, fetch_explore=True):
    """给单条书源补发现页规则。

    返回 (ruleExplore or None, 诊断 dict)。
    """
    base = norm_base(src.get('bookSourceUrl'))
    headers = src_headers(src)
    entries = parse_explore_urls(src.get('exploreUrl'), base)
    diag = {'has_explore_url': bool(entries), 'entries': len(entries)}

    targets = _candidate_targets(entries, base)
    if not targets:
        if not fetch_explore or not base:
            diag['reason'] = 'no_explore_url'
            return None, diag
        # 没有 exploreUrl：先尝试从首页合成
        res, doc = _fetch(base, headers, timeout, user_agent)
        if doc is None:
            diag['reason'] = 'home_unreachable'
            return None, diag
        synth = synthesize_explore_urls(doc, base)
        diag['synthesized'] = len(synth)
        if not synth:
            diag['reason'] = 'no_category_links'
            return None, diag
        for t, u in synth:
            full = abs_url(base, _fill_page(u))
            r2, d2 = _fetch(full, headers, timeout, user_agent)
            if d2 is not None:
                targets = [(t, full)]
                diag['synth_target'] = t
                break
        if not targets:
            diag['reason'] = 'synth_fetch_failed'
            return None, diag

    # 逐个候选入口尝试，直到某个页面能反推出规则
    last_reason = 'explore_unreachable'
    for target_title, target_url in targets:
        res, doc = _fetch(target_url, headers, timeout, user_agent)
        if doc is None:
            last_reason = 'explore_unreachable'
            continue
        diag['target'] = target_url
        diag['target_title'] = target_title

        # 候选 1：沿用 ruleSearch
        cand = _search_rule_as_candidate(src)
        if cand:
            rule, d = build_explore_rule(cand, doc)
            if rule:
                diag['method'] = 'reuse_rule_search'
                diag.update(d)
                return rule, diag
            diag['reuse_result'] = d

        # 候选 2：页面结构反推
        best = None
        for c in propose_explore_candidates(doc):
            rule, d = build_explore_rule(c, doc)
            if rule:
                diag['method'] = 'reverse_engineer'
                diag.update(d)
                return rule, diag
            score = d.get('ratio', 0) + (0.2 if d.get('name_ok') else 0)
            if best is None or score > best[0]:
                best = (score, d)
        if best:
            diag['best'] = best[1]
        last_reason = 'no_candidate'
    diag['reason'] = last_reason
    return None, diag


def supplement_all(sources, timeout=25, user_agent=None, only=None, progress=None,
                   force=False):
    """批量补全发现页规则。返回 (结果列表, 报告 dict)。

    结果列表与 sources 等长：只含成功补全的书源（含补好的 exploreUrl）。

    ``only`` 只是缩小处理范围，**不会**覆盖已经写好 ``ruleExplore.bookList``
    的书源；要重做已有的发现页规则请显式传 ``force=True``。
    """
    import concurrent.futures as cf
    indexes = list(range(len(sources)))
    if only:
        indexes = [i for i in indexes if i in set(only)]
    if not force:
        indexes = [i for i in indexes
                   if not (sources[i].get('ruleExplore') or {}).get('bookList')]
    fixed, report = [], {}
    done = 0
    with cf.ThreadPoolExecutor(max_workers=8) as pool:
        futs = {}
        for i in indexes:
            futs[pool.submit(supplement_one, sources[i], timeout, user_agent)] = i
        for fut in cf.as_completed(futs):
            i = futs[fut]
            src = sources[i]
            try:
                rule, diag = fut.result()
            except Exception as exc:
                rule, diag = None, {'reason': 'exc', 'err': str(exc)[:160]}
            report[i] = diag
            if rule:
                new_src = dict(src)
                new_src['ruleExplore'] = rule
                # 合成 exploreUrl 时一并写回（仅写回实测通过的入口）
                if not src.get('exploreUrl') and diag.get('target'):
                    new_src['exploreUrl'] = '%s::%s' % (diag.get('synth_target', ''),
                                                       diag['target'])
                new_src['_explore_fixed'] = diag
                new_src['_orig_index'] = i
                fixed.append(new_src)
            done += 1
            if progress and done % 50 == 0:
                progress('explore %d/%d fixed=%d' % (done, len(indexes), len(fixed)))
    fixed.sort(key=lambda s: s.get('_orig_index', 0))
    return fixed, report
