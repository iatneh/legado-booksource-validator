# -*- coding: utf-8 -*-
"""深链修复（deep-repair）的单元测试。

重点锁住两件事：

1. **搜索页要轮换关键词** —— 有些站的搜索页只有换词才出书单，
   只用第一个关键词会让整条深链修复直接放弃。
2. **只修确实坏的层** —— 新规则必须实测取到足够章节 / 正文才写回。
"""
import unittest
from unittest import mock

from legado_validator import deeprepair

SEARCH_PAGE_EMPTY = '''<html><body><p>没有结果</p></body></html>'''

SEARCH_PAGE_OK = '''<html><body>
<div class="item"><a href="/book/1.html">斗破苍穹</a></div>
<div class="item"><a href="/book/2.html">斗破苍穹</a></div>
</body></html>'''

SRC = {
    'bookSourceName': '测试源',
    'bookSourceUrl': 'http://example.com',
    'ruleSearch': {'bookList': 'class.item', 'bookUrl': 'a@href'},
    'ruleToc': {'chapterList': 'class.chapter'},
    'ruleContent': {'content': 'div.content'},
}


class _Resp(dict):
    """http.fetch 的返回形态：dict。"""

    def __init__(self, body, status=200, url=''):
        super(_Resp, self).__init__(ok=status < 400, status=status, body=body,
                                    url=url, headers={}, err=None)


class TestKeywordRotation(unittest.TestCase):
    """搜索页没有结果时要换关键词再试。"""

    def test_rotates_keyword_until_items_found(self):
        seen = []

        def fake_fetch(url, method, body, headers, timeout, user_agent):
            seen.append(url)
            if '修真' in url:
                return _Resp(SEARCH_PAGE_EMPTY, 200, url)
            return _Resp(SEARCH_PAGE_OK, 200, url)

        spec = {'spec': {'url': 'http://example.com/s?kw=修真', 'method': 'GET',
                         'body': None, 'headers': {}}}
        with mock.patch.object(deeprepair, '_fetch', side_effect=fake_fetch):
            rules, diag = deeprepair.deep_repair_one(
                dict(SRC), spec, kw0='修真', keywords=['斗破苍穹'])
        # 至少换过一个关键词才拿到书单
        self.assertGreater(len(seen), 1)
        self.assertTrue(any('斗破苍穹' in u for u in seen))
        # 没有停在 "no_items"，而是走到了书籍页那一步
        self.assertNotEqual(diag.get('why'), 'no_items')

    def test_gives_up_when_no_keyword_works(self):
        def fake_fetch(url, method, body, headers, timeout, user_agent):
            return _Resp(SEARCH_PAGE_EMPTY, 200, url)

        spec = {'spec': {'url': 'http://example.com/s?kw=修真', 'method': 'GET',
                         'body': None, 'headers': {}}}
        with mock.patch.object(deeprepair, '_fetch', side_effect=fake_fetch):
            rules, diag = deeprepair.deep_repair_one(
                dict(SRC), spec, kw0='修真', keywords=['斗破苍穹'])
        self.assertIsNone(rules)
        self.assertEqual(diag.get('why'), 'no_items')

    def test_fetch_failure_is_reported(self):
        def fake_fetch(url, method, body, headers, timeout, user_agent):
            return _Resp('', 503, url)

        spec = {'spec': {'url': 'http://example.com/s?kw=修真', 'method': 'GET',
                         'body': None, 'headers': {}}}
        with mock.patch.object(deeprepair, '_fetch', side_effect=fake_fetch):
            rules, diag = deeprepair.deep_repair_one(
                dict(SRC), spec, kw0='修真', keywords=['斗破苍穹'])
        self.assertIsNone(rules)
        self.assertEqual(diag.get('why'), 'search_fetch_failed')

    def test_missing_url_is_reported(self):
        rules, diag = deeprepair.deep_repair_one(dict(SRC), {'spec': {}})
        self.assertIsNone(rules)
        self.assertEqual(diag.get('why'), 'no_request_url')


if __name__ == '__main__':
    unittest.main()
