# -*- coding: utf-8 -*-
"""书源规则层：请求构造、响应解析、关键词替换。"""
import json
import re
from urllib.parse import quote, urljoin

from .engine import parse_html, rule_items


def parse_body(res):
    """把响应体拆成 (json_obj, html_doc)，二者最多一个非空。"""
    body = res.get('body') or ''
    ct = (res.get('ct') or '').lower()
    stripped = body.lstrip()
    if 'json' in ct or stripped[:1] in ('{', '['):
        try:
            return json.loads(body), None
        except Exception:
            pass
    return None, parse_html(body)


def src_headers(src):
    """书源自带的请求头（header 字段是 JSON 字符串）。"""
    out = {}
    raw = src.get('header')
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                out.update(parsed)
        except Exception:
            pass
    elif isinstance(raw, dict):
        out.update(raw)
    return out


def norm_base(url):
    """归一化 bookSourceUrl，补全协议头。"""
    s = str(url or '').strip()
    if s.startswith('//'):
        return 'https:' + s
    if s.startswith('http'):
        return s
    if re.match(r'^[a-z0-9.-]+\.[a-z]{2,}', s, re.I):
        return 'https://' + s
    return ''


def abs_url(base, href):
    """把书源里的相对链接补成绝对链接。"""
    h = str(href or '').strip()
    if not h:
        return ''
    if h.startswith('http://') or h.startswith('https://'):
        return h
    if h.startswith('//'):
        return 'https:' + h
    try:
        return urljoin(base or '', h)
    except Exception:
        return h


def swap_kw(spec, old_kw, new_kw):
    """把已构造好的请求里的关键词换成另一个；没命中返回 None。"""
    o = quote(old_kw)
    n = quote(new_kw)
    out = dict(spec)
    hit = False
    if o in (out.get('url') or ''):
        out['url'] = out['url'].replace(o, n)
        hit = True
    if out.get('body') and o in str(out['body']):
        out['body'] = str(out['body']).replace(o, n)
        hit = True
    return out if hit else None


def keywords_for(src, extra=None):
    """关键词顺序：书源自带的 checkKeyWord 优先，其次是通用词。"""
    kws = []
    ck = (src.get('ruleSearch') or {}).get('checkKeyWord')
    if isinstance(ck, str) and ck.strip():
        kws.append(ck.strip())
    for k in (extra or ['斗破苍穹', '都市', '修真']):
        if k not in kws:
            kws.append(k)
    return kws[:4]


def book_items(src, doc=None, js=None):
    """按 ruleSearch.bookList 取出书单条目。"""
    bl = (src.get('ruleSearch') or {}).get('bookList')
    if not bl:
        return []
    try:
        return rule_items(bl, doc=doc, js=js) or []
    except Exception:
        return []
