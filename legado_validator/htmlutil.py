# -*- coding: utf-8 -*-
"""HTML 解析结果上的通用小工具。

规则反推（``proposer``）、搜索规则修复（``repair``）、发现页补全
（``explore``）都要判断"这个链接像不像书籍详情""这个 class 怎么写成选择器"，
这些判断放一处，避免三处各写一遍慢慢跑偏。
"""
import re

SKIP_HREF = ('javascript:', 'mailto:', 'tel:', '#')

TITLE_WORDS = ('author', 'writer', 'zuozhe', 'author_name', 'authorname')

# 目录/分类页链接特征（用于排除"不是书"的链接）
CATEGORY_HREF = re.compile(
    r'/(tag|tags|sort|category|cat|list|type|class|search|so)(/|\?|$)', re.I)

# 像书籍详情链接的路径特征
BOOKISH_RE = re.compile(
    r'/(book|read|novel|info|detail|x[s_]?shuo|work|comic|manga|album|series|chapter)', re.I)


def href_of(el):
    return (el.attrs.get('href') or '').strip()


def usable_link(el):
    """链接是否可作为"书名/详情页"候选。"""
    h = href_of(el)
    if not h or h.lower().startswith(SKIP_HREF):
        return False
    return True


def text_of(el):
    return re.sub(r'\s+', ' ', el.text()).strip()


def css_class(el):
    """给元素取一个可用的 class 选择器（优先第一个非框架类）。"""
    for c in sorted(el.classes()):
        if c and not c.startswith('ng-') and not c.startswith('js-'):
            return '.' + c
    return None


def css_id(el):
    i = (el.attrs.get('id') or '').strip()
    if i and re.match(r'^[A-Za-z][\w-]*$', i):
        return '#' + i
    return None


def sel_for(el):
    """给元素生成尽量精确的 CSS 选择器。"""
    return css_class(el) or css_id(el) or el.tag


def looks_like_book(href):
    """链接路径像不像书籍详情。"""
    if not href:
        return False
    low = href.lower()
    if BOOKISH_RE.search(low):
        return True
    return bool(re.search(r'/\d{3,}', low))


def good_book_url(href):
    """排除首页/栏目/搜索这类"不是书"的链接。"""
    if not href:
        return False
    low = href.split('#')[0].split('?')[0]
    if not low or low == '/':
        return False
    if CATEGORY_HREF.search(low) and not re.search(r'/\d{3,}', low):
        return False
    return looks_like_book(href)


def good_name(name):
    """书名应当非空、长度合理、不是乱码。"""
    if not name:
        return False
    name = name.strip()
    if len(name) < 1 or len(name) > 60:
        return False
    if '\ufffd' in name:
        return False
    cjk = len(re.findall(r'[\u4e00-\u9fff]', name))
    latin = len(re.findall(r'[A-Za-z0-9]', name))
    return cjk + latin >= 1
