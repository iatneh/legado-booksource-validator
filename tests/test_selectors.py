# -*- coding: utf-8 -*-
"""选择器语义单元测试（锁住与 Legado 官方源码对齐的行为）。

覆盖三类容易跑偏的地方：

1. **bookList / chapterList 的末段语义** —— Legado 的 ``getElements`` 走
   ``AnalyzeByJSoup.ElementsSingle``，末段是**选择器**（tag/class/id/children）；
   而 ``getStringList``（name/author/bookUrl 走的那条）末段才是**属性名**。
   早期把两者混为一谈，导致 ``class.X@children`` 静默丢children，容器本身
   被当成一条书。

2. **CSS 伪类的兄弟计数** —— ``:nth-child(n)`` 数的是父节点下第 n 个
   **子元素**（不分标签）；``:nth-of-type(n)`` 才是同标签计数。

3. **相邻兄弟选择器** —— ``A + B`` / ``A ~ B`` 是兄弟关系，不是后代关系。
"""
import json
import os
import shutil
import subprocess
import tempfile
import unittest

from legado_validator import engine
from legado_validator.engine import css_find, eval_rule, parse_html, rule_items

HTML = '''<html><body>
<div class="w"><nav><a href="/b/1">甲</a></nav></div>
<div class="w"><nav><a href="/b/3">丙</a></nav></div>
<div class="librarylist">
  <p class="t"><a href="/x/1">书一</a></p>
  <p class="t"><a href="/x/2">书二</a></p>
</div>
<div class="m"><span>x</span><em>y</em><p>A</p><p>B</p></div>
<ul class="u"><li>1</li><li>2</li><li>3</li></ul>
<h1>标题</h1><span class="s"><a href="/a/1">作者</a></span>
</body></html>'''


class TestRuleItemsTerminal(unittest.TestCase):
    """bookList / chapterList 的末段按 Legado getElements 语义解析。"""

    def setUp(self):
        self.doc = parse_html(HTML)

    def test_last_segment_is_selector_not_attribute(self):
        # 末段是标签选择器：取 nav，而不是把 nav 当属性名丢掉
        items = rule_items('div@nav', doc=self.doc)
        self.assertEqual([e.tag for e in items], ['nav', 'nav'])

    def test_children_returns_direct_children(self):
        items = rule_items('class.librarylist@children', doc=self.doc)
        self.assertEqual([e.text() for e in items], ['书一', '书二'])

    def test_unknown_attribute_terminal_yields_nothing(self):
        # Legado 里 select('href') 匹配不到任何标签，结果为空
        self.assertEqual(rule_items('class.librarylist@href', doc=self.doc), [])

    def test_eval_rule_keeps_attribute_terminal(self):
        # getStringList 那条路（name/author/bookUrl）末段才是属性名
        vals = eval_rule('class.w@id', doc=self.doc)
        self.assertTrue(all(isinstance(v, str) for v in vals))


class TestPseudoClasses(unittest.TestCase):
    """CSS 伪类的兄弟计数严格按 CSS 语义。"""

    def setUp(self):
        self.doc = parse_html(HTML)

    def test_nth_child_counts_all_element_children(self):
        # <span/><em/><p>A</p><p>B</p>：第 3 个子元素是 <p>A</p>
        els = css_find(self.doc, 'p:nth-child(3)')
        self.assertEqual([e.text() for e in els], ['A'])

    def test_nth_of_type_counts_same_tag_siblings(self):
        els = css_find(self.doc, 'p:nth-of-type(2)')
        self.assertIn('B', [e.text() for e in els])

    def test_first_and_last_child(self):
        self.assertEqual([e.text() for e in css_find(self.doc, 'li:first-child')], ['1'])
        self.assertEqual([e.text() for e in css_find(self.doc, 'li:last-child')], ['3'])

    def test_not_pseudo(self):
        els = css_find(self.doc, 'li:not(:first-child)')
        self.assertEqual([e.text() for e in els], ['2', '3'])

    def test_eq_is_collection_level(self):
        # :eq(n) 取整个匹配集合里的第 n 个，而不是"第 n 个同标签兄弟"
        els = css_find(self.doc, 'a:eq(0)')
        self.assertEqual(len(els), 1)
        self.assertEqual(els[0].attrs.get('href'), '/b/1')


class TestSiblingCombinators(unittest.TestCase):
    """``+`` / ``~`` 是兄弟关系，不能当后代关系。"""

    def setUp(self):
        self.doc = parse_html(HTML)

    def test_adjacent_sibling(self):
        els = css_find(self.doc, 'h1+span>a')
        self.assertEqual([e.text() for e in els], ['作者'])

    def test_descendant_is_not_adjacent(self):
        self.assertEqual(css_find(self.doc, 'h1 span>a'), [])

    def test_general_sibling(self):
        els = css_find(self.doc, 'h1~span>a')
        self.assertEqual([e.text() for e in els], ['作者'])

    def test_child_combinator(self):
        els = css_find(self.doc, 'div.m > p')
        self.assertEqual([e.text() for e in els], ['A', 'B'])


class TestMergerRobustness(unittest.TestCase):
    """merger 不因 --cn-server / --overseas-server 写错而崩溃。"""

    def _res(self, status='ok'):
        return [{'i': 0, 'status': status, 'http': 200, 'items': 3,
                 'deep': {'book': True, 'toc': True, 'content': True, 'reason': ''}}]

    def test_unknown_cn_server_does_not_raise(self):
        from legado_validator import merger
        srcs = [{'bookSourceName': 'A', 'bookSourceUrl': 'http://a.com',
                 'ruleSearch': {'bookList': 'x'}}]
        res = {'aliyun': self._res(), 'rack-nerd': self._res()}
        out = merger.merge(srcs, res, cn_server='cn-box', overseas_server='rack-nerd')
        self.assertEqual(len(out['kept']), 1)
        # 写错的节点名要退回默认，不能把整轮书源误判成"两台都死"
        self.assertEqual(out['kept'][0]['_validation']['access'], 'both')

    def test_normal_merge_still_works(self):
        from legado_validator import merger
        srcs = [{'bookSourceName': 'A', 'bookSourceUrl': 'http://a.com',
                 'ruleSearch': {'bookList': 'x'}}]
        res = {'aliyun': self._res(), 'rack-nerd': self._res()}
        out = merger.merge(srcs, res, cn_server='aliyun', overseas_server='rack-nerd')
        self.assertEqual(out['kept'][0]['_validation']['access'], 'both')


class TestPatcherStats(unittest.TestCase):
    """深链修复不能被算进"搜索层修复"的计数里。"""

    def test_deep_only_row_not_counted_as_search_repair(self):
        from legado_validator import patcher
        srcs = [{'bookSourceName': 'A', 'bookSourceUrl': 'http://a.com',
                 'ruleSearch': {'bookList': 'x'}, 'ruleToc': {}}]
        rows = [{'_orig_index': 0, 'ruleToc': {'chapterList': 'div.row'},
                 '_deep_repaired': {'ok': True}}]
        with tempfile.NamedTemporaryFile('w', suffix='.json', delete=False,
                                         encoding='utf-8') as fh:
            json.dump(rows, fh, ensure_ascii=False)
            path = fh.name
        try:
            out, stats = patcher.patch_sources(srcs, repair_files=[path])
        finally:
            os.unlink(path)
        self.assertEqual(stats['repair_applied'], 0)
        self.assertEqual(stats['deep_sources'], 1)
        self.assertEqual(stats['deep_applied'], 1)
        # deep-repair 的行不该把 _repaired 写成 null
        self.assertIsNone(out[0].get('_repaired'))
        self.assertEqual(out[0]['ruleToc']['chapterList'], 'div.row')

    def test_search_row_counted(self):
        from legado_validator import patcher
        srcs = [{'bookSourceName': 'A', 'bookSourceUrl': 'http://a.com',
                 'ruleSearch': {'bookList': 'x'}}]
        rows = [{'_orig_index': 0, 'ruleSearch': {'bookList': 'div.new'},
                 '_repaired': {'ok': True}}]
        with tempfile.NamedTemporaryFile('w', suffix='.json', delete=False,
                                         encoding='utf-8') as fh:
            json.dump(rows, fh, ensure_ascii=False)
            path = fh.name
        try:
            out, stats = patcher.patch_sources(srcs, repair_files=[path])
        finally:
            os.unlink(path)
        self.assertEqual(stats['repair_applied'], 1)
        self.assertEqual(out[0]['ruleSearch']['bookList'], 'div.new')


class TestExploreOnlyKeepsExisting(unittest.TestCase):
    """explore --only 不能覆盖已经写好 ruleExplore 的书源。"""

    def test_existing_rule_explore_not_overwritten(self):
        from legado_validator import explore
        srcs = [{'bookSourceName': 'A', 'bookSourceUrl': 'http://a.com',
                 'ruleExplore': {'bookList': 'div.keep'}}]
        with mock_patch_http():
            fixed, report = explore.supplement_all(srcs, only=[0])
        # 连试都不该试：报告里不该出现这个下标
        self.assertEqual(fixed, [])
        self.assertEqual(report, {})

    def test_force_allows_overwrite(self):
        from legado_validator import explore
        srcs = [{'bookSourceName': 'A', 'bookSourceUrl': 'http://a.com',
                 'ruleExplore': {'bookList': 'div.keep'}}]
        with mock_patch_http():
            fixed, report = explore.supplement_all(srcs, only=[0], force=True)
        # force=True 时确实去试了这个源（网络失败所以没补成功）
        self.assertIn(0, report)


def mock_patch_http():
    """把 http.fetch 换成永远失败的桩，保证不会真的发请求。"""
    from unittest import mock
    from legado_validator import http

    class _Resp(object):
        ok = False
        status = 0
        body = ''
        url = ''
        headers = {}

    return mock.patch.object(http, 'fetch', return_value=_Resp())


class TestJsSandboxSelectors(unittest.TestCase):
    """JS 沙箱里的 select() 必须和 Jsoup 一样返回最右匹配。"""

    JS = r'''
const L = require(process.argv[2]);
const html = '<html><body>'
  + '<h1>书名</h1><span><a href="/oneauthor.php?novelid=12345">作者</a></span>'
  + '<h2>副标题</h2><a href="/other/999">别的</a>'
  + '<div class="m"><span>x</span><em>y</em><p>A</p><p>B</p></div>'
  + '<ul class="u"><li>1</li><li>2</li><li>3</li></ul>'
  + '</body></html>';
const root = L.parseHtml(html);
const out = {};
for (const sel of ['h1+span>a', 'div.x a', 'p:nth-child(3)', 'p:nth-of-type(2)',
                   'li:not(:first-child)', 'ul li:eq(1)', '.m > p']) {
  out[sel] = L.cssFind(root, sel).map(e => e.tag + ':' + e.text());
}
console.log(JSON.stringify(out));
'''

    @classmethod
    def setUpClass(cls):
        if not shutil.which('node'):
            raise unittest.SkipTest('没有 node，跳过 JS 沙箱测试')
        cls.path = os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), 'legado_validator', 'js', 'legado_js.js')
        with tempfile.NamedTemporaryFile('w', suffix='.js', delete=False,
                                         encoding='utf-8') as fh:
            fh.write(cls.JS)
            script = fh.name
        try:
            proc = subprocess.run(['node', script, cls.path],
                                  capture_output=True, text=True)
        finally:
            os.unlink(script)
        if proc.returncode != 0:
            raise unittest.SkipTest('node 执行失败: %s' % proc.stderr[:200])
        cls.data = json.loads(proc.stdout.strip().splitlines()[-1])

    def test_adjacent_sibling(self):
        self.assertEqual(self.data['h1+span>a'], ['a:作者'])

    def test_descendant_returns_rightmost_match(self):
        # 早期版本返回的是最左匹配（div 本身），Jsoup 返回最右匹配
        self.assertEqual(self.data['div.x a'], [])

    def test_nth_child(self):
        self.assertIn('p:A', self.data['p:nth-child(3)'])

    def test_nth_of_type(self):
        self.assertIn('p:B', self.data['p:nth-of-type(2)'])

    def test_not_pseudo(self):
        self.assertEqual(self.data['li:not(:first-child)'], ['li:2', 'li:3'])

    def test_eq_is_collection_level(self):
        self.assertEqual(self.data['ul li:eq(1)'], ['li:2'])

    def test_child_combinator(self):
        self.assertEqual(self.data['.m > p'], ['p:A', 'p:B'])


if __name__ == '__main__':
    unittest.main()
