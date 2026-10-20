# -*- coding: utf-8 -*-
"""书单规则反推：从真实页面结构推出 bookList / name / author / bookUrl。

搜索规则（``ruleSearch``）和发现页规则（``ruleExplore``）的字段结构完全
一样，都是"书单 + 书名 + 作者 + 详情链接"，所以两者共用这里的实现。

**关键约束：name / author / bookUrl 必须是相对书单元素的规则。**

Legado 里 ``bookList`` 圈出一组元素后，``name`` / ``bookUrl`` 是在**每个
书单元素内部**再查找的（``class.title@text`` 这种链式写法）。如果写成
``@css:ol a@href`` 这种带前缀的形式，Legado 会在整页范围内做 CSS 选择，
结果就是"整页所有链接"而不是"这一条书的链接"，规则就废了。

因此本模块产出的规则形如::

    bookList = "ol"          # 文档级选择器
    name     = "a@text"     # 相对书单元素
    bookUrl  = "a@href"     # 相对书单元素
    author   = "class.author@text"
"""
import re
from collections import Counter

from .engine import eval_rule, rule_items
from .htmlutil import (css_class as _css_class, good_book_url as _good_book_url,
                       good_name as _good_name, sel_for as _sel_for,
                       usable_link as _usable_link)

# 书单至少要有这么多个条目才像"书单"
MIN_ITEMS = 3

# 看着像书名、其实是栏目/导航文字的噪声
NAME_NOISE_RE = re.compile(
    r'(推荐|排行|榜单|热门|更多|首页|上一页|下一页|点击|阅读|全文|目录|'
    r'书友|求票|收藏|投票|举报|广告|返回|顶部|底部|展开|收起|详情|简介)', re.I)


def clean_name(v):
    return re.sub(r'\s+', ' ', str(v or '')).strip()


def name_ok(name):
    """书名是否像样：非空、长度合理、不含乱码、不是导航文字。"""
    if not _good_name(name):
        return False
    return not NAME_NOISE_RE.search(name)


def _anchors_of(item):
    return [el for el in item.iter_desc() if el.tag == 'a' and _usable_link(el)]


def _path_of(href):
    return str(href or '').split('?')[0].split('#')[0]


def _common_prefix(paths):
    """一组链接路径的公共前缀（按 / 分段比）。"""
    segs = [_path_of(p).split('/') for p in paths if p]
    if not segs:
        return ''
    common = []
    for parts in zip(*segs):
        if len(set(parts)) == 1:
            common.append(parts[0])
        else:
            break
    return '/'.join(common)


def _plausible_prefix(prefix):
    """公共前缀像不像"一批同结构的书单链接"。"""
    if not prefix:
        return False
    segs = [s for s in prefix.split('/') if s]
    if not segs:
        return False
    if len(segs) >= 2:
        return True
    # 只有一段时，得像 id / 数字
    seg = segs[0]
    return bool(re.search(r'\d', seg)) or seg.lower() in ('book', 'read', 'novel', 'info', 'detail')


def _anchor_rule(link):
    """给"书名链接"生成一条相对书单元素的选择器。

    优先用链接自身的 class；没有 class 就退到父元素的 class 再 tag.a；
    都没有就用 'a'。返回 (取属性用的选择器, 取文本用的选择器)。
    """
    cls = _css_class(link)
    if cls:
        return cls, cls
    parent = link.parent
    if parent is not None:
        pcls = _css_class(parent)
        if pcls:
            return pcls + '@tag.a', pcls + '@tag.a'
    return 'a', 'a'


def _container_stats(doc):
    """统计可能承载书单的重复块。"""
    anchors = [el for el in doc.iter_desc() if el.tag == 'a' and _usable_link(el)]
    stats = {}
    for a in anchors:
        node = a.parent
        depth = 0
        while node is not None and depth < 4:
            key = (_sel_for(node), node.tag)
            stats[key] = stats.get(key, 0) + 1
            node = node.parent
            depth += 1
    return stats


def propose_candidates(doc, max_items=60, allow_loose=False):
    """从页面结构反推候选规则，按置信度从高到低。

    ``allow_loose`` 打开后，允许"链接不像书籍详情、但路径结构一致"的容器
    也参与候选。**只在页面确实是搜索结果页时才该打开**——否则导航栏、
    筛选条这类结构也会被当成书单，反推出错误的规则。
    """
    if doc is None:
        return []
    stats = _container_stats(doc)
    if not stats:
        return []
    cands = []
    seen = set()
    for (sel, _tag), count in sorted(stats.items(), key=lambda kv: -kv[1])[:80]:
        if count < 2:
            continue
        try:
            items = rule_items(sel, doc=doc)
        except Exception:
            continue
        if not items or len(items) > max_items:
            continue
        # 容器内要能找到书籍详情链接
        per_item = []
        for it in items[:8]:
            links = [el for el in _anchors_of(it)
                     if _good_book_url(el.attrs.get('href') or '')]
            per_item.append(links)
        good = sum(1 for l in per_item if l)
        loose = False
        if good < max(1, len(per_item) // 2):
            if not allow_loose:
                continue
            # 放宽：链接不像"书籍详情"，但只要**路径结构一致**，
            # 同样说明这是一个书单（很多站的书籍链接是 /1234.html 这类）
            relaxed = []
            for it in items[:8]:
                anchors = _anchors_of(it)
                relaxed.append([anchors[0]] if anchors else [])
            hrefs = [l[0].attrs.get('href') for l in relaxed if l]
            if len(hrefs) < 3 or not _plausible_prefix(_common_prefix(hrefs)):
                continue
            # 链接得指向**不同**的书，不能都是一个栏目页
            if len(set(_path_of(h) for h in hrefs)) < 3:
                continue
            # 书单一般不止三五本，筛选条那种通常很少
            if len(items) < 5:
                continue
            per_item = relaxed
            good = sum(1 for l in per_item if l)
            loose = True
            if good < max(1, len(per_item) // 2):
                continue
        if not any(per_item):
            continue
        # 书名链接对应的选择器（取出现最多的那种）
        rules = []
        for links in per_item:
            if links:
                rules.append(_anchor_rule(links[0]))
        if not rules:
            continue
        best_rule = Counter(r[0] for r in rules).most_common(1)[0][0]
        best_text = Counter(r[1] for r in rules).most_common(1)[0][0]
        key = (sel, best_rule)
        if key in seen:
            continue
        seen.add(key)
        name_options = [best_text + '@text']
        for alt in ('h1', 'h2', 'h3', 'h4', 'h5', 'dt', '.title', '.name',
                    '.bookname', '.booktitle', '.txt', 'span'):
            opt = alt + '@text'
            if opt not in name_options:
                name_options.append(opt)
        author = _find_author(per_item)
        cands.append({
            'bookList': sel,
            'name': best_text + '@text',
            'name_options': name_options,
            'author': (author + '@text') if author else None,
            'bookUrl': best_rule + '@href',
            'count': count,
            'items': len(items),
            'loose': loose,
            'note': '容器=%s(%d) 锚点=%s' % (sel, len(items), best_rule),
        })
    # 优先用 class/id 圈容器（比裸标签名精确得多），其次条目多的
    cands.sort(key=lambda c: (0 if c['bookList'][:1] in '.#' else 1,
                              -c['items'], -c['count']))
    return cands


def _find_author(per_item):
    """在容器里找作者字段（class/id 里带 author/writer/zuozhe）。"""
    for links in per_item:
        if not links:
            continue
        scope = links[0].parent
        if scope is None:
            continue
        for el in scope.iter_desc():
            c = _css_class(el)
            ident = (el.attrs.get('id') or '').lower()
            if c and any(w in c.lower() or w in ident
                         for w in ('author', 'writer', 'zuozhe')):
                return c
    return None


def evaluate(cand, doc):
    """验证候选规则，返回 (条目数, 书名, 链接, 好链占比, 书名是否像样)。"""
    try:
        items = rule_items(cand['bookList'], doc=doc)
    except Exception:
        return 0, '', '', 0.0, False
    if not items:
        return 0, '', '', 0.0, False
    urls = []
    for it in items[:8]:
        try:
            u = eval_rule(cand['bookUrl'], doc=doc, item=it)
        except Exception:
            u = []
        urls.append(next((v for v in u if isinstance(v, str) and v.strip()), ''))
    if cand.get('loose'):
        # 放宽模式：只要链接非空、且路径结构一致就算好链
        filled = [u for u in urls if u]
        if not filled:
            return 0, '', '', 0.0, False
        if not _plausible_prefix(_common_prefix(filled)):
            return 0, '', '', 0.0, False
        ratio = float(len(filled)) / len(urls) if urls else 0.0
        good = filled
    else:
        good = [u for u in urls if _good_book_url(u)]
        ratio = float(len(good)) / len(urls) if urls else 0.0
    # 挑一个像样的书名规则
    best_name, best_ok = cand['name'], False
    best_score = -1.0
    for opt in cand.get('name_options') or [cand['name']]:
        vals = []
        for it in items[:6]:
            try:
                n = eval_rule(opt, doc=doc, item=it)
            except Exception:
                n = []
            vals.append(clean_name(next(
                (v for v in n if isinstance(v, str) and v.strip()), '')))
        filled = [v for v in vals if v]
        if not filled:
            continue
        uniq = len(set(filled)) / float(len(filled))
        ok = name_ok(filled[0]) and uniq >= 0.5
        score = (1.0 if ok else 0.0) + uniq
        if score > best_score:
            best_score, best_name, best_ok = score, opt, ok
    name_val = ''
    try:
        nv = eval_rule(best_name, doc=doc, item=items[0])
        name_val = clean_name(next(
            (v for v in nv if isinstance(v, str) and v.strip()), ''))
    except Exception:
        pass
    return len(items), name_val, (good[0] if good else (urls[0] if urls else '')), ratio, best_ok


def build_rule(cand, doc, min_items=MIN_ITEMS):
    """把候选变成最终规则字典；质量不达标返回 (None, 诊断)。"""
    n, name, url, ratio, ok = evaluate(cand, doc)
    diag = {'items': n, 'name': name, 'url': url, 'ratio': round(ratio, 2),
            'name_ok': ok, 'note': cand.get('note', '')}
    if n < min_items or not url or ratio < 0.6 or not ok:
        diag['reason'] = 'quality_gate'
        return None, diag
    rule = {
        'bookList': cand['bookList'],
        'name': cand['name'],
        'bookUrl': cand['bookUrl'],
    }
    if cand.get('author'):
        rule['author'] = cand['author']
    return rule, diag


def from_search_rule(src):
    """把已有的 ruleSearch 转成一个候选（发现页与搜索页常同构）。"""
    rules = src.get('ruleSearch') or {}
    bl = rules.get('bookList')
    name = rules.get('name')
    book_url = rules.get('bookUrl')
    if not bl or not name or not book_url:
        return None
    return {
        'bookList': bl,
        'name': name,
        'name_options': [name],
        'author': rules.get('author'),
        'bookUrl': book_url,
        'count': 0,
        'items': 0,
        'note': '沿用 ruleSearch',
    }
