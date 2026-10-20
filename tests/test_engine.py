# -*- coding: utf-8 -*-
"""规则引擎（HTML 解析 + 规则求值）单元测试。"""
import unittest

from legado_validator.engine import (css_find, eval_rule, json_items, json_path,
                                      parse_html, rule_items, split_hash)

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

    def test_json_wildcard_over_objects(self):
        payload = {'data': [{'id': 1, 'name': 'A'}, {'id': 2, 'name': 'B'}]}
        self.assertEqual(eval_rule('$.data[*].name', js=payload), ['A', 'B'])

    def test_indexed_tag_step(self):
        # Legado 允许 a.0 / a.1 取第 n 个同名元素
        html = ('<div class="it"><a href="/1">一</a><a href="/2">二</a></div>')
        doc = parse_html(html)
        item = rule_items('class.it', doc=doc)[0]
        self.assertEqual(eval_rule('a.0@href', doc=doc, item=item), ['/1'])
        self.assertEqual(eval_rule('a.1@href', doc=doc, item=item), ['/2'])

    def test_indexed_class_step(self):
        html = '<div><span class="t">x</span><span class="t">y</span></div>'
        doc = parse_html(html)
        item = rule_items('div', doc=doc)[0]
        self.assertEqual(eval_rule('class.t.1@text', doc=doc, item=item), ['y'])

    def test_negative_index_step(self):
        html = '<div><i>1</i><i>2</i><i>3</i></div>'
        doc = parse_html(html)
        item = rule_items('div', doc=doc)[0]
        self.assertEqual(eval_rule('i.-1@text', doc=doc, item=item), ['3'])

    def test_multi_index_exclusion(self):
        # Legado 的 !0:1:2 表示排除这些下标
        html = '<div class="c"><dd>a</dd><dd>b</dd><dd>c</dd></div>'
        doc = parse_html(html)
        item = rule_items('class.c', doc=doc)[0]
        self.assertEqual(eval_rule('tag.dd!0:1@text', doc=doc, item=item), ['c'])

    def test_css_pseudo_class(self):
        html = '<ul><li>1</li><li>2</li><li>3</li></ul>'
        doc = parse_html(html)
        self.assertEqual(eval_rule('li:nth-child(2)@text', doc=doc), ['2'])
        self.assertEqual(eval_rule('li:last-child@text', doc=doc), ['3'])

    def test_java_style_group_replacement(self):
        """Legado 的替换段用 $1 引用捕获组，Python 的 re.sub 只认 \\1。"""
        html = '<div><p>辰东 · 玄幻 · 417万字</p></div>'
        doc = parse_html(html)
        got = eval_rule('p@text##^([^·]+)·.*$##$1', doc=doc)
        self.assertEqual(got, ['辰东 '])

    def test_braced_group_replacement(self):
        html = '<div><p>abc-123</p></div>'
        doc = parse_html(html)
        self.assertEqual(eval_rule('p@text##(\\w+)-(\\d+)##${2}', doc=doc), ['123'])

    def test_dollar_escape(self):
        """Java 里 $$ 表示字面量 $，后面的 1 不再是捕获组引用。"""
        html = '<div><p>price 5</p></div>'
        doc = parse_html(html)
        self.assertEqual(eval_rule('p@text##(\\d+)##$$1', doc=doc), ['price $1'])

    def test_attribute_selectors(self):
        html = ('<ul><li><a href="/chapter/1" data-bid="9">x</a></li>'
                '<li><a href="/other/2" data-bid="8">y</a></li></ul>'
                '<meta property="og:novel:book_name" content="夜无疆">')
        doc = parse_html(html)
        self.assertEqual(len(rule_items('@css:a[data-bid]', doc=doc)), 2)
        self.assertEqual(len(rule_items('@css:a[href*="/chapter/"]', doc=doc)), 1)
        self.assertEqual(len(rule_items('@css:a[href^="/other/"]', doc=doc)), 1)
        self.assertEqual(len(rule_items('@css:a[data-bid="9"]', doc=doc)), 1)
        self.assertEqual(len(rule_items('@css:a[data-bid!="9"]', doc=doc)), 1)
        got = eval_rule('@css:meta[property="og:novel:book_name"]@content', doc=doc)
        self.assertEqual(got, ['夜无疆'])

    def test_attribute_selector_with_space_in_value(self):
        html = '<a href="/c/1" title="第一章 首发时间">x</a>'
        doc = parse_html(html)
        got = rule_items('@css:a[title*="首发时间"]', doc=doc)
        self.assertEqual(len(got), 1)

    def test_json_and_expression(self):
        payload = {'data': [{'x': 1}]}
        self.assertEqual(len(rule_items('$..book[0]&&$.data[*]', js=payload)), 1)

    def test_json_path_missing(self):
        self.assertIsNone(json_path({'a': 1}, '$.b.c'))

    def test_json_items_fallback(self):
        self.assertEqual(json_items({'list': [1, 2]}), [1, 2])

    def test_split_hash(self):
        self.assertEqual(split_hash('a@text##x##y'), ('a@text', 'x', 'y'))

    def test_split_hash_legado_terminator(self):
        """Legado 写 ``规则##正则##替换##`` 时多出的 ## 只是结束符。

        早期实现用 ``'##'.join(parts[2:])``，替换文本会多带一截 ``##``，
        拼出来的书籍链接就是坏的。
        """
        self.assertEqual(split_hash('##href="x"##http://a/b/###'),
                         ('', 'href="x"', 'http://a/b/'))

    def test_split_hash_regex_kept(self):
        self.assertEqual(split_hash('a@text##(\\d+)##$1'), ('a@text', '(\\d+)', '$1'))


class TestCssCombinator(unittest.TestCase):
    """CSS 子代选择器 ``>``：起点移动版列表就靠它定位。"""

    HTML = (
        '<div class="y-list__content">'
        '<div class="y-list__item"><h2>书一</h2></div>'
        '<div class="y-list__item"><h2>书二</h2></div>'
        '</div>'
        '<div class="other"><div class="y-list__item"><h2>不该被选中</h2></div></div>'
    )

    def setUp(self):
        self.doc = parse_html(self.HTML)

    def test_child_combinator(self):
        els = css_find(self.doc, 'div.y-list__content>div.y-list__item')
        self.assertEqual(len(els), 2)
        self.assertEqual([e.text() for e in els], ['书一', '书二'])

    def test_descendant_combinator(self):
        els = css_find(self.doc, 'div.y-list__content div.y-list__item')
        self.assertEqual(len(els), 2)

    def test_child_combinator_with_space(self):
        els = css_find(self.doc, 'div.y-list__content > div.y-list__item')
        self.assertEqual(len(els), 2)

    def test_attr_prefix_with_child_combinator(self):
        doc = parse_html(
            '<div class="item"><div class="_tags_abc_1"><p>玄幻</p><p>连载</p></div></div>')
        els = css_find(doc, 'div[class^=_tags_]>p:nth-child(1)')
        self.assertEqual([e.text() for e in els], ['玄幻'])


class TestLegadoJsSuffix(unittest.TestCase):
    """``@js:`` 尾段：Legado 用 Rhino 执行，前一段的结果是 ``result``。"""

    HTML = ('<div class="y-list__item">'
            '<a href="//m.qidian.com/chapter/1042022730/0/" data-bid="1042022730">书</a>'
            '</div>')

    def setUp(self):
        self.doc = parse_html(self.HTML)

    def test_js_concat_builds_url(self):
        item = css_find(self.doc, 'div.y-list__item')[0]
        rule = ("a[data-bid]@data-bid@js:'https://m.qidian.com/book/'+result+'/'")
        self.assertEqual(eval_rule(rule, doc=self.doc, item=item),
                         ['https://m.qidian.com/book/1042022730/'])

    def test_js_concat_rejects_arbitrary_js(self):
        item = css_find(self.doc, 'div.y-list__item')[0]
        rule = "a[data-bid]@data-bid@js:java.ajax('x')+result"
        self.assertEqual(eval_rule(rule, doc=self.doc, item=item), [''])

    def test_js_concat_empty_result(self):
        doc = parse_html('<div class="x"><a data-bid="">书</a></div>')
        item = css_find(doc, 'div.x')[0]
        rule = "a[data-bid]@data-bid@js:'https://x/'+result"
        self.assertEqual(eval_rule(rule, doc=doc, item=item), ['https://x/'])


class TestLegadoHashSemantics(unittest.TestCase):
    """``##正则##替换`` 与 ``##正则##替换##`` 两种写法的差别。"""

    def setUp(self):
        self.doc = parse_html('<span class="x">作者：张三</span>')

    def test_plain_replace(self):
        self.assertEqual(eval_rule('class.x@text##作者：##', doc=self.doc), ['张三'])

    def test_replace_first_miss_returns_empty(self):
        """Legado: 末尾多一个 ## 时匹配不到会返回空串，而不是原文。"""
        self.assertEqual(eval_rule('class.x@text##不存在####', doc=self.doc), [''])

    def test_replace_first_hit(self):
        got = eval_rule('class.x@text##(张)##$1先生##', doc=self.doc)
        self.assertEqual(got, ['张先生'])


if __name__ == '__main__':
    unittest.main()
