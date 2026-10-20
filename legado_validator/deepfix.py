# -*- coding: utf-8 -*-
"""深链修复：从真实页面反推 ``ruleToc`` / ``ruleContent``。

已有的 ``repair`` 模块只修**搜索层**（``ruleSearch`` 的 bookList / name /
bookUrl）。但校验器报的 ``no_toc_items`` / ``empty_content`` 说明的是
**深链层**坏了：搜索能出书单，点进去看不到目录或正文。这个模块补上这块。

链路按 Legado 真实语义走：

    书籍页 --ruleBookInfo.tocUrl--> 目录页 --ruleToc--> 章节页 --ruleContent--> 正文

目录页
    目录页上找"重复出现、且每块里都有一个章节链接"的容器块，反推出新的
    ``chapterList``（文档级）+ ``chapterName`` / ``chapterUrl``（相对章节
    元素）。章节链接要像章节：同域、路径里带章节标识。

正文
    章节页上找正文容器。先试常见 id/class（``#content`` / ``.content`` /
    ``#chaptercontent`` 这类），都不中就取"文本最长且长度够"的块。

所有产出都要**实测验证**（目录能取到章节、正文能取到足够长的文字），
验证不通过就不改规则。
"""
import re

from .engine import eval_rule, rule_items
from .htmlutil import css_class, css_id, sel_for, text_of

# 章节链接里常见的标识
CHAPTER_HINT = re.compile(
    r'/(chapter|chap|read|text|content|page|no|vol|part|htm|html|)(\d+)|'
    r'\d+[-_]?\d*\.html|chapter_?\d|id=\d+', re.I)

# 常见的正文容器
CONTENT_IDS = ('content', 'chaptercontent', 'chapter-content', 'bookcontent',
               'nr1', 'nr2', 'txtnav', 'read-content', 'article', 'text',
               'htmlContent', 'bookContent', 'con', 'zw')
CONTENT_CLASSES = ('content', 'chapter-content', 'read-content', 'article-content',
                   'txtnav', 'txt', 'con', 'zw', 'neirong', 'nr', 'showtxt',
                   'book-content', 'mulu-txt', 'chapter_content', 'text-content')

MIN_CHAPTERS = 3
MIN_CONTENT_CHARS = 200

# 明显不是正文的容器（导航 / 侧栏 / 推荐 / 目录弹层 / 上下章）
# 按 **token** 判定：把 id / class 按 - _ 和驼峰切开，逐个比对，
# 避免用子串正则误杀 "content" / "read-content" 这类正常容器。
NOT_CONTENT_TOKENS = {
    'nav', 'navbar', 'navigation', 'menu', 'header', 'footer', 'side', 'sidebar',
    'banner', 'recommend', 'relate', 'related', 'comment', 'cmt', 'directory',
    'catalog', 'mulu', 'popup', 'tip', 'tips', 'crumb', 'toolbar', 'search',
    'rank', 'list', 'share', 'copyright', 'qrcode', 'prev', 'next', 'up', 'down',
}

# 正文里应当出现的句子特征
SENTENCE_RE = re.compile(r'[。！？；…\.\?!]')

# 站务公告 / 反盗版提示（"最新网址：xxx"这类），不是正文
NOTICE_RE = re.compile(
    r'最新网址|永久网址|手机版网址|请记住本站|本站网址|收藏本站|域名|'
    r'本站声明|版权声明|如果您觉得|本站小说|请支持正版|盗版必究', re.I)


def _strip_notice(txt):
    """去掉开头的站务公告，剩下的才算正文。"""
    out = txt
    for _ in range(3):
        m = NOTICE_RE.search(out[:200])
        if not m:
            break
        cut = out.find('。', m.end())
        out = out[cut + 1:] if 0 <= cut < 400 else out[m.end():]
    return out.strip()


def _tokens(ident):
    """把 id / class 拆成小写 token 集合。"""
    out = set()
    for part in re.split(r'[^0-9A-Za-z\u4e00-\u9fff]+', str(ident or '')):
        if not part:
            continue
        # 驼峰也切开
        for piece in re.findall(r'[A-Z]+(?![a-z])|[A-Z][a-z0-9]*|[a-z0-9]+|[\u4e00-\u9fff]+',
                                part):
            if piece:
                out.add(piece.lower())
    return out


# ------------------------------------------------------------------ 目录层

def _chapter_links(el):
    """块内的章节链接。"""
    out = []
    for a in el.iter_desc():
        if a.tag != 'a':
            continue
        h = (a.attrs.get('href') or '').strip()
        if not h or h.startswith('#') or h.lower().startswith('javascript:'):
            continue
        out.append((a, h))
    return out


def _looks_like_chapter(href, base_host):
    """链接像不像章节页。"""
    if not href:
        return False
    low = href.split('#')[0].split('?')[0]
    if not low or low == '/' or low.endswith('/'):
        return False
    if not CHAPTER_HINT.search(low):
        return False
    if base_host and base_host in low:
        return True
    return bool(re.search(r'\d', low))


def _container_candidates(doc, base_host, max_items=400):
    """统计可能承载章节列表的重复块。"""
    stats = {}
    for a in doc.iter_desc():
        if a.tag != 'a':
            continue
        href = (a.attrs.get('href') or '').strip()
        if not _looks_like_chapter(href, base_host):
            continue
        node = a.parent
        depth = 0
        while node is not None and depth < 4:
            key = (sel_for(node), node.tag)
            stats[key] = stats.get(key, 0) + 1
            node = node.parent
            depth += 1
    cands = []
    seen = set()
    for (sel, _tag), count in sorted(stats.items(), key=lambda kv: -kv[1])[:40]:
        if count < MIN_CHAPTERS:
            continue
        try:
            items = rule_items(sel, doc=doc)
        except Exception:
            continue
        if not items or len(items) > max_items:
            continue
        key = (sel, count)
        if key in seen:
            continue
        seen.add(key)
        # 每个块里要能取到一个章节链接
        good = 0
        link_rule = None
        for it in items[:6]:
            links = _chapter_links(it)
            if links:
                good += 1
                if link_rule is None:
                    link_rule = _link_rule(links[0][0])
        if good < max(1, len(items[:6]) // 2) or not link_rule:
            continue
        cands.append({'chapterList': sel, 'chapterUrl': link_rule, 'items': len(items),
                      'count': count})
    # 精确的 class/id 优先，其次条目多
    cands.sort(key=lambda c: (0 if c['chapterList'][:1] in '.#' else 1, -c['items']))
    return cands


def _link_rule(link):
    """给章节链接生成一条相对章节元素的选择器。"""
    cls = css_class(link)
    if cls:
        return cls + '@href'
    ident = css_id(link)
    if ident:
        return ident + '@href'
    parent = link.parent
    if parent is not None:
        pcls = css_class(parent)
        if pcls:
            return pcls + '@tag.a@href'
    return 'a@href'


def _chapter_name_rule(items, doc, link_rule):
    """给章节名挑一条相对规则。"""
    from .engine import eval_rule as _eval
    options = []
    # 先看链接自身的文本
    for it in items[:4]:
        try:
            vals = _eval(link_rule.replace('@href', '@text'), doc=doc, item=it)
        except Exception:
            vals = []
        v = next((x for x in vals if isinstance(x, str) and x.strip()), '')
        if v:
            options.append(('link', link_rule.replace('@href', '@text'), v))
            break
    for alt in ('h1', 'h2', 'h3', 'h4', 'a', 'span', 'p', 'div'):
        rule = alt + '@text'
        for it in items[:4]:
            try:
                vals = _eval(rule, doc=doc, item=it)
            except Exception:
                vals = []
            v = next((x for x in vals if isinstance(x, str) and x.strip()), '')
            if v:
                options.append(('tag', rule, v))
                break
    return options


def propose_toc_rules(doc, base_host, min_chapters=MIN_CHAPTERS):
    """从目录页反推章节规则，返回 (规则字典, 诊断)。"""
    cands = _container_candidates(doc, base_host)
    tried = []
    for c in cands:
        try:
            items = rule_items(c['chapterList'], doc=doc)
        except Exception:
            continue
        if not items or len(items) < min_chapters:
            tried.append((c['chapterList'], len(items)))
            continue
        # 章节链接必须能取到
        ok_urls = []
        for it in items[:5]:
            try:
                vals = eval_rule(c['chapterUrl'], doc=doc, item=it)
            except Exception:
                vals = []
            ok_urls.append(next((v for v in vals if isinstance(v, str) and v.strip()), ''))
        good = sum(1 for u in ok_urls if u)
        if good < max(1, len(ok_urls) // 2):
            tried.append((c['chapterList'], len(items)))
            continue
        names = _chapter_name_rule(items, doc, c['chapterUrl'])
        best = None
        for kind, rule, sample in names:
            score = 0
            if kind == 'link':
                score = 2
            elif re.search(r'\d', sample):
                score = 1
            if len(sample) > 1 and len(sample) <= 40:
                score += 1
            if best is None or score > best[0]:
                best = (score, rule, sample)
        chapter_name = best[1] if best else 'a@text'
        return {
            'chapterList': c['chapterList'],
            'chapterName': chapter_name,
            'chapterUrl': c['chapterUrl'],
        }, {'ok': True, 'items': len(items), 'nameSample': best[2] if best else '',
            'note': '容器=%s(%d) 链接=%s' % (c['chapterList'], len(items), c['chapterUrl'])}
    return None, {'ok': False, 'candidates': len(cands), 'tried': tried[:6]}


# ------------------------------------------------------------------ 正文层

def _content_blocks(doc):
    """页面里所有可能装正文的块。"""
    out = []
    for el in doc.iter_desc():
        if el.tag not in ('div', 'section', 'article', 'td', 'pre', 'span'):
            continue
        txt = text_of(el)
        if len(txt) < 40:
            continue
        out.append(el)
    return out


def _link_count(el):
    return sum(1 for d in el.iter_desc() if d.tag == 'a')


def _looks_like_body(el, txt, total_len, total_links=None):
    """这个块像不像真正的章节正文。

    章节正文的特征：**文字多、链接少**、带句子标点、class/id 不像导航或
    目录、开头没有站务公告。站点的导航栏、推荐位、目录弹层、反盗版提示
    文字往往也很多，但链接密度高、句子标点少、开头挂着"最新网址"，用
    这几条就能把它们挡掉。
    """
    links = _link_count(el)
    if txt and links and len(txt) / float(links) < 50:
        return False                      # 链接太密，是列表不是正文
    if links > 8 and len(txt) < 2000:
        return False
    if not SENTENCE_RE.search(txt) and len(txt) < 800:
        return False                      # 没有句子标点且不长，多半是目录/导航
    if total_links and links >= 5 and links > total_links * 0.6:
        return False                      # 包住了页面上大部分链接，是外壳
    if NOTICE_RE.search(txt[:200]):
        return False                      # 开头是站务公告，不是正文
    ident = (el.attrs.get('id') or '') + ' ' + ' '.join(el.classes())
    if _tokens(ident) & NOT_CONTENT_TOKENS:
        return False
    return True


def _innermost(cands):
    """同一块内容的外层/内层只保留最内层那个。

    站点常把正文套在 ``.wrapper`` 里，wrapper 文字几乎一样多，但会带上
    章节标题、作者、字数这些头部信息。取最内层更准。
    """
    if not cands:
        return []
    out = []
    for el, txt in cands:
        dominated = False
        for el2, txt2 in cands:
            if el2 is el:
                continue
            if len(txt2) < len(txt) * 0.9:
                continue
            # el2 是 el 的后代吗
            p = el2.parent
            while p is not None:
                if p is el:
                    dominated = True
                    break
                p = p.parent
            if dominated:
                break
        if not dominated:
            out.append((el, txt))
    return out or cands


def propose_content_rule(doc):
    """从章节页反推正文规则，返回 (规则, 诊断)。"""
    tried = []
    total_links = sum(1 for d in doc.iter_desc() if d.tag == 'a')
    # 1) 常见 id / class
    cands = []
    for ident in CONTENT_IDS:
        el = None
        for e in doc.iter_desc():
            if (e.attrs.get('id') or '').lower() == ident.lower():
                el = e
                break
        if el is not None:
            cands.append(('#' + ident, el))
    for cls in CONTENT_CLASSES:
        for e in doc.iter_desc():
            if cls in [c.lower() for c in e.classes()]:
                cands.append(('.' + cls, e))
                break
    for sel, el in cands:
        txt = text_of(el)
        if len(txt) < MIN_CONTENT_CHARS:
            tried.append((sel, len(txt)))
            continue
        if not _looks_like_body(el, txt, 0, total_links):
            tried.append((sel, 'not_body'))
            continue
        return sel + '@text', {'ok': True, 'chars': len(txt), 'sample': txt[:40],
                                'note': '命中常见容器 %s' % sel}
    # 2) 退而求其次：像正文的块里取最内层、文字最多的
    blocks = _content_blocks(doc)
    good = []
    for el in blocks:
        txt = text_of(el)
        if len(txt) < MIN_CONTENT_CHARS:
            continue
        if not _looks_like_body(el, txt, 0, total_links):
            continue
        sel = sel_for(el)
        if not sel or sel in ('div', 'body', 'html', '#root'):
            continue
        good.append((el, txt))
    good = _innermost(good)
    ranked = sorted(good, key=lambda it: len(it[1]), reverse=True)
    for el, txt in ranked[:5]:
        sel = sel_for(el)
        return sel + '@text', {'ok': True, 'chars': len(txt), 'sample': txt[:40],
                                'note': '正文块 %s' % sel}
    return None, {'ok': False, 'tried': tried[:6]}
