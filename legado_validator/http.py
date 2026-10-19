# -*- coding: utf-8 -*-
"""HTTP 抓取层：超时控制、每主机限速、反爬识别、编码猜测。"""
import re
import threading
import time

import requests

from .config import DEFAULT_USER_AGENT

BLOCK_PATTERNS = (
    (r'just a moment', 'cf_challenge'),
    (r'checking your browser', 'cf_challenge'),
    (r'attention required.{0,40}cloudflare', 'cf_block'),
    (r'error 1020', 'cf_1020'),
    (r'access denied', 'access_denied'),
    (r'access to this page has been denied', 'access_denied'),
    (r'403 forbidden', 'forbidden_page'),
    (r'请输入验证码|输入验证码|滑动验证|人机验证|安全验证|访问验证', 'captcha_zh'),
    (r'访问拒绝|禁止访问|无权访问|访问过于频繁|请求过于频繁', 'access_denied_zh'),
    (r'do not run this software', 'bot_block'),
)

_HOST_LOCK = threading.Lock()
_HOST_LAST = {}


def host_throttle(url, gap=0.12):
    """同一主机的请求最小间隔，避免把站点打挂。"""
    try:
        host = re.sub(r'^https?://', '', str(url)).split('/')[0].lower()
    except Exception:
        return
    with _HOST_LOCK:
        last = _HOST_LAST.get(host, 0)
        wait = gap - (time.time() - last)
        if wait > 0:
            time.sleep(wait)
        _HOST_LAST[host] = time.time()


def _decode(raw, content_type):
    enc = 'utf-8'
    m = re.search(r'charset=([\w-]+)', content_type or '', re.I)
    if m:
        enc = m.group(1).lower()
    if enc in ('gb2312', 'gbk', 'gb18030'):
        try:
            return raw.decode('gb18030')
        except Exception:
            pass
    try:
        return raw.decode('utf-8')
    except Exception:
        return raw.decode('latin-1', 'replace')


def fetch(url, method='GET', body=None, headers=None, timeout=25, user_agent=None):
    """发起一次请求，返回统一结构；网络异常不抛异常，只标记 err。"""
    h = {'User-Agent': user_agent or DEFAULT_USER_AGENT,
         'Accept': '*/*',
         'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8'}
    h.update(headers or {})
    if method.upper() == 'POST' and body is not None:
        if not any(k.lower() == 'content-type' for k in h):
            raw = str(body).strip()
            if raw.startswith('{') or raw.startswith('['):
                h['Content-Type'] = 'application/json'
            else:
                h['Content-Type'] = 'application/x-www-form-urlencoded'
    host_throttle(url)
    t0 = time.time()
    try:
        r = requests.request(method, url, data=body, headers=h,
                             timeout=(10, timeout), allow_redirects=True)
        return {'ok': True, 'status': r.status_code, 'url': r.url,
                'body': _decode(r.content, r.headers.get('Content-Type', '')),
                'ms': int((time.time() - t0) * 1000),
                'ct': r.headers.get('Content-Type', '') or ''}
    except requests.exceptions.SSLError as exc:
        return {'ok': False, 'err': 'ssl', 'detail': str(exc)[:140],
                'ms': int((time.time() - t0) * 1000)}
    except requests.exceptions.ConnectTimeout:
        return {'ok': False, 'err': 'conn_timeout', 'ms': int((time.time() - t0) * 1000)}
    except requests.exceptions.ReadTimeout:
        return {'ok': False, 'err': 'read_timeout', 'ms': int((time.time() - t0) * 1000)}
    except requests.exceptions.ConnectionError as exc:
        return {'ok': False, 'err': 'conn_error', 'detail': str(exc)[:140],
                'ms': int((time.time() - t0) * 1000)}
    except Exception as exc:
        return {'ok': False, 'err': 'error', 'detail': str(exc)[:140],
                'ms': int((time.time() - t0) * 1000)}


def detect_block(status, body):
    """识别反爬 / 挑战页 / 错误页，返回命中的类型名。"""
    head = (body or '')[:4000]
    low = head.lower()
    for pat, name in BLOCK_PATTERNS:
        if re.search(pat, low, re.I) or re.search(pat, head, re.I):
            return name
    tm = re.search(r'<title[^>]*>(.*?)</title>', head, re.S | re.I)
    title = tm.group(1).strip().lower() if tm else ''
    if title.startswith('403') or title.startswith('404 not found') or title.startswith('访问'):
        return 'forbidden_page'
    if 'captcha' in title:
        return 'captcha'
    if status in (401, 403, 451):
        return 'http_%d' % status
    if status == 404:
        return 'http_404'
    if status >= 500:
        return 'http_%d' % status
    return None
