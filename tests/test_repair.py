# -*- coding: utf-8 -*-
"""搜索规则修复 + 规则反推的单元测试。"""
import unittest

from legado_validator.engine import parse_html
from legado_validator.proposer import (build_rule, clean_name, name_ok,
                                       propose_candidates)
from legado_validator.repair import repair_source
from legado_validator.validator import name_filled

HTML = """
<html><body>
  <ul class="book-list">
    <li class="item"><h3 class="title"><a href="/book/101">斗破苍穹</a></h3>
      <span class="author">天蚕土豆</span></li>
    <li class="item"><h3 class="title"><a href="/book/102">神印王座</a></h3>
      <span class="author">幻尘</span></li>
    <li class="item"><h3 class="title"><a href="/book/103">斗罗大陆</a></h3>
      <span class="author">唐家三少</span></li>
  </ul>
</body></html>
"""


class TestProposer(unittest.TestCase):
    def setUp(self):
        self.doc = parse_html(HTML)

    def test_finds_item_container(self):
        cands = propose_candidates(self.doc)
        self.assertTrue(cands)
        self.assertTrue(any(c['bookList'] == '.item' for c in cands))

    def test_rules_are_relative(self):
        """name / bookUrl 必须是相对书单元素的写法。"""
        for c in propose_candidates(self.doc):
            self.assertFalse(c['name'].startswith('@css:'))
            self.assertFalse(c['bookUrl'].startswith('@css:'))
            self.assertNotIn(' ', c['bookList'])

    def test_build_rule_roundtrip(self):
        cands = propose_candidates(self.doc)
        for c in cands:
            rule, diag = build_rule(c, self.doc)
            if rule:
                self.assertIn('bookList', rule)
                self.assertIn('name', rule)
                self.assertIn('bookUrl', rule)
                self.assertGreaterEqual(diag['items'], 3)
                return
        self.fail('没有候选规则通过质量门')

    def test_clean_name(self):
        self.assertEqual(clean_name('  斗破\n  苍穹 '), '斗破 苍穹')

    def test_name_ok_rejects_nav_text(self):
        self.assertTrue(name_ok('斗破苍穹'))
        self.assertFalse(name_ok('书友推荐'))
        self.assertFalse(name_ok(''))


class TestRepairSource(unittest.TestCase):
    def test_repairs_with_relative_rules(self):
        doc = parse_html(HTML)
        src = {'bookSourceName': '测试', 'bookSourceUrl': 'https://example.com',
               'ruleSearch': {'bookList': '.old-broken', 'name': '.x@text',
                              'bookUrl': '.y@href'}}
        rules, diag = repair_source(src, doc, 'https://example.com')
        self.assertTrue(diag.get('ok'), diag)
        self.assertNotIn('@css:', rules['bookUrl'])
        self.assertNotIn('@css:', rules['name'])

    def test_returns_none_when_no_structure(self):
        doc = parse_html('<html><body><p>hi</p></body></html>')
        src = {'bookSourceName': 'x', 'bookSourceUrl': 'https://example.com',
               'ruleSearch': {'bookList': '.nope'}}
        rules, diag = repair_source(src, doc, 'https://example.com')
        self.assertIsNone(rules)
        self.assertFalse(diag.get('ok'))


class TestNameFilled(unittest.TestCase):
    """书单能取到、但书名规则已过时（站点改版）的情况要能识别出来。"""

    def setUp(self):
        self.doc = parse_html(HTML)

    def test_good_name_rule(self):
        src = {'ruleSearch': {'name': '.title@text'}}
        items = propose_candidates(self.doc)
        from legado_validator.engine import rule_items
        its = rule_items('.item', doc=self.doc)
        filled, tried = name_filled(src, its, self.doc, None)
        self.assertEqual(filled, tried)
        self.assertGreater(filled, 0)

    def test_stale_name_rule_detected(self):
        src = {'ruleSearch': {'name': '.gone-class@text'}}
        from legado_validator.engine import rule_items
        its = rule_items('.item', doc=self.doc)
        filled, tried = name_filled(src, its, self.doc, None)
        self.assertEqual(filled, 0)
        self.assertGreater(tried, 0)

    def test_no_name_rule(self):
        src = {'ruleSearch': {}}
        from legado_validator.engine import rule_items
        its = rule_items('.item', doc=self.doc)
        self.assertEqual(name_filled(src, its, self.doc, None), (0, 0))


if __name__ == '__main__':
    unittest.main()
