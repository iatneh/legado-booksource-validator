# -*- coding: utf-8 -*-
"""深链校验（deep_check）的链路语义单元测试。

重点：Legado 的真实链路是

    书籍页 --ruleBookInfo.tocUrl--> 目录页 --ruleToc--> 章节页 --ruleContent--> 正文

早期实现把目录规则直接套在书籍页上判，导致"目录页独立"的站点被误判成
目录规则失效。这里用假的服务端把几种页面分开，锁住正确行为。
"""
import unittest
from unittest import mock

from legado_validator import validator

SEARCH_PAGE = '''<html><body>
<div class="item"><a href="/book/1010868264/">诡秘之主</a></div>
</body></html>'''

BOOK_PAGE = '''<html><head><title>诡秘之主</title></head><body>
<a id="details-menu" href="/book/1010868264/catalog/">目录</a>
</body></html>'''

TOC_PAGE = '''<html><body>
<div class="list">
  <a class="_chapterItem_" href="/chapter/1010868264/1.html"><h2>第一章 绯红</h2></a>
  <a class="_chapterItem_" href="/chapter/1010868264/2.html"><h2>第二章 情况</h2></a>
  <a class="_chapterItem_" href="/chapter/1010868264/3.html"><h2>第三章 梅丽莎</h2></a>
</div>
</body></html>'''

CHAPTER_PAGE = '''<html><body>
<div id="reader-content">这是正文内容，足够长的一段中文文字，用来通过正文长度门槛的校验。</div>
</body></html>'''


def _resp(url, body, status=200):
    return {'ok': True, 'status': status, 'body': body, 'text': body,
            'url': url, 'headers': {}, 'ms': 10, 'err': None}


def _fake_fetch(url, method='GET', body=None, headers=None, timeout=25,
                user_agent=None):
    if '/catalog/' in url:
        return _resp(url, TOC_PAGE)
    if '/chapter/' in url:
        return _resp(url, CHAPTER_PAGE)
    if '/book/' in url:
        return _resp(url, BOOK_PAGE)
    return _resp(url, '<html><body><a href="/book/1/x.html">书</a></body></html>')


def _items(src):
    from legado_validator.engine import rule_items
    js, doc = validator.parse_body({'body': SEARCH_PAGE, 'ct': 'text/html'})
    return rule_items(src['ruleSearch']['bookList'], doc=doc) or []


class TestDeepCheck(unittest.TestCase):
    """deep_check 的链路判定。"""

    def _src(self, **kw):
        src = {
            'bookSourceUrl': 'https://example.com',
            'ruleSearch': {'bookList': '.item', 'bookUrl': 'a@href'},
            'ruleBookInfo': {'name': 'h1@text'},
            'ruleToc': {'chapterList': 'a[class^=_chapterItem_]',
                        'chapterName': 'h2@text', 'chapterUrl': 'href'},
            'ruleContent': {'content': 'id.reader-content@text'},
        }
        src.update(kw)
        return src

    def _run(self, src, fetch=None):
        js, doc = validator.parse_body({'body': SEARCH_PAGE, 'ct': 'text/html'})
        with mock.patch.object(validator, 'fetch', side_effect=fetch or _fake_fetch):
            return validator.deep_check(src, _items(src), doc, js,
                                        'https://example.com', {}, 25)

    def test_toc_url_rule_leads_to_separate_toc_page(self):
        """有 tocUrl 规则时，目录规则要作用在目录页上。"""
        src = self._src(ruleBookInfo={'name': 'h1@text',
                                      'tocUrl': 'id.details-menu@href'})
        out = self._run(src)
        self.assertTrue(out['book'], out)
        self.assertTrue(out['toc'], out)
        self.assertTrue(out['content'], out)
        self.assertEqual(out['reason'], '')

    def test_without_toc_url_rule_chapters_may_live_on_book_page(self):
        """没有 tocUrl 规则时，目录规则直接作用在书籍页上（Legado 的退路）。"""
        src = self._src()
        out = self._run(src)
        # 书籍页里没有章节 -> 判为目录规则失效
        self.assertTrue(out['book'], out)
        self.assertFalse(out['toc'], out)
        self.assertEqual(out['reason'], 'no_toc_items')

    def test_toc_fetch_failure_is_reported(self):
        src = self._src(ruleBookInfo={'name': 'h1@text',
                                      'tocUrl': 'id.details-menu@href'})

        def fetch_toc_fail(url, *a, **kw):
            if '/catalog/' in url:
                return _resp(url, '', status=500)
            return _fake_fetch(url, *a, **kw)

        out = self._run(src, fetch_toc_fail)
        self.assertTrue(out['book'], out)
        self.assertFalse(out['toc'], out)
        self.assertEqual(out['reason'], 'toc_fetch_failed')

    def test_chapters_on_book_page_still_work(self):
        """书籍页自带章节列表时（无 tocUrl 规则），链路同样要通。"""
        page = '''<html><body>
        <a class="_chapterItem_" href="/chapter/1/1.html"><h2>第一章</h2></a>
        <a class="_chapterItem_" href="/chapter/1/2.html"><h2>第二章</h2></a>
        <a class="_chapterItem_" href="/chapter/1/3.html"><h2>第三章</h2></a>
        </body></html>'''

        def fetch_with_chapters(url, *a, **kw):
            if '/catalog/' in url:
                return _resp(url, TOC_PAGE)
            if '/chapter/' in url:
                return _resp(url, CHAPTER_PAGE)
            if '/book/' in url:
                return _resp(url, page)
            return _fake_fetch(url, *a, **kw)

        src = self._src()
        out = self._run(src, fetch_with_chapters)
        self.assertTrue(out['toc'], out)
        self.assertTrue(out['content'], out)

    def test_missing_book_url_rule(self):
        src = self._src(ruleSearch={'bookList': '.item'})
        out = self._run(src)
        self.assertEqual(out['reason'], 'no_book_url_rule')
        self.assertFalse(out['book'])


if __name__ == '__main__':
    unittest.main()
