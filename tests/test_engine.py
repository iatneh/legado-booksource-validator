# -*- coding: utf-8 -*-
"""规则引擎（HTML 解析 + 规则求值）单元测试。"""
import unittest

from legado_validator.engine import (eval_rule, json_items, json_path, parse_html,
                                      rule_items, split_hash)

HTML = (
    '<html><body>'
    '<div class="bookbox"><h3 class="t"><a href="/b/1">书名一</a></h3>'
    '<span class="a">作者一</span></div>'
    '<div class="bookbox"><h3 class="t"><a href="/b/2">书名二</a></h3>'
    '<span class="a">作者二</span></div>'
    '<ul class="other_s"><li>甲</li><li>乙</li></ul>'
    '</body></html>'
)


class TestParseHtml(unittest.TestCase):
    def setUp(self):
        self.doc = parse_html(HTML)

    def test_tags_and_attrs(self):
        tags = [e.tag for e in self.doc.iter_desc()]
        self.assertIn('div', tags)
        self.assertIn('a', tags)

    def test_classes(self):
        divs = [e for e in self.doc.iter_desc() if e.tag == 'div']
        self.assertTrue(divs[0].classes() & {'bookbox'})

    def test_text(self):
        spans = [e for e in self.doc.iter_desc() if e.tag == 'span']
        self.assertEqual(spans[0].text().strip(), '作者一')

    def test_script_content_not_parsed_as_tags(self):
        doc = parse_html('<div><script>var a = "<b>";</script></div>')
        self.assertNotIn('b', [e.tag for e in doc.iter_desc()])

    def test_unclosed_tags(self):
        doc = parse_html('<ul><li>a<li>b</ul>')
        self.assertEqual(len([e for e in doc.iter_desc() if e.tag == 'li']), 2)


class TestRuleItems(unittest.TestCase):
    def setUp(self):
        self.doc = parse_html(HTML)

    def test_css_list(self):
        items = rule_items('@css:.bookbox', self.doc)
        self.assertEqual(len(items), 2)

    def test_space_css_list(self):
        items = rule_items('.other_s li', self.doc)
        self.assertEqual(len(items), 2)

    def test_legacy_chain_list(self):
        items = rule_items('ul@li', self.doc)
        self.assertEqual(len(items), 2)

    def test_class_index_list(self):
        items = rule_items('class.bookbox', self.doc)
        self.assertEqual(len(items), 2)

    def test_empty_rule(self):
        self.assertEqual(rule_items('', self.doc), [])


class TestEvalRule(unittest.TestCase):
    def setUp(self):
        self.doc = parse_html(HTML)
        self.item = rule_items('@css:.bookbox', self.doc)[0]

    def test_relative_text(self):
        self.assertEqual(eval_rule('class.a@text', self.doc, item=self.item),
                         ['作者一'])

    def test_relative_href(self):
        self.assertEqual(eval_rule('class.t@tag.a@href', self.doc, item=self.item),
                         ['/b/1'])

    def test_css_attr(self):
        self.assertEqual(
            eval_rule('@css:.t a@href', self.doc, item=self.item), ['/b/1'])

    def test_index_selection(self):
        self.assertEqual(eval_rule('class.bookbox.1@class.t@tag.a@text', self.doc),
                         ['书名二'])

    def test_hash_regex_cleanup(self):
        doc = parse_html('<div class="x">作者：张三</div>')
        self.assertEqual(eval_rule('class.x@text##作者：##', doc), ['张三'])

    def test_json_path(self):
        payload = {'data': {'books': [{'id': 1}, {'id': 2}]}}
        items = rule_items('$.data.books[*]', js=payload)
        self.assertEqual(len(items), 2)

    def test_json_and_expression(self):
        payload = {'data': [{'x': 1}]}
        self.assertEqual(len(rule_items('$..book[0]&&$.data[*]', js=payload)), 1)

    def test_json_path_missing(self):
        self.assertIsNone(json_path({'a': 1}, '$.b.c'))

    def test_json_items_fallback(self):
        self.assertEqual(json_items({'list': [1, 2]}), [1, 2])

    def test_split_hash(self):
        self.assertEqual(split_hash('a@text##x##y'), ('a@text', 'x', 'y'))


if __name__ == '__main__':
    unittest.main()
