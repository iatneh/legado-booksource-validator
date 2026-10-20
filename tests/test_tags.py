# -*- coding: utf-8 -*-
"""标签重构 + 发现页规则补全的单元测试。"""
import unittest

from legado_validator import tags
from legado_validator.explore import (parse_explore_urls, propose_explore_candidates,
                                      synthesize_explore_urls)
from legado_validator.engine import parse_html


class TestSplitGroup(unittest.TestCase):
    def test_comma_and_chinese_comma(self):
        self.assertEqual(tags.split_group('A,B，C;D'),
                         ['A', 'B', 'C', 'D'])

    def test_dedupe_preserves_order(self):
        self.assertEqual(tags.split_group('B,A,B'), ['B', 'A'])

    def test_empty(self):
        self.assertEqual(tags.split_group(''), [])
        self.assertEqual(tags.split_group(None), [])


class TestCategories(unittest.TestCase):
    def test_alias_normalized(self):
        self.assertEqual(tags.original_categories('正版'), ['正版书源 🏷'])
        self.assertEqual(tags.original_categories('网络小说'), ['文本书源 📚'])

    def test_status_tags_dropped(self):
        self.assertEqual(tags.original_categories('人机验证-搜索,暂不可用'), [])

    def test_type_fallback(self):
        s = {'bookSourceGroup': '', 'bookSourceType': 2}
        self.assertEqual(tags.resolve_categories(s), ['漫画书源 🎨'])

    def test_fast_supersedes_normal(self):
        s = {'bookSourceGroup': '快速书源 ⚡,通常书源 📂', 'bookSourceType': 0}
        self.assertEqual(tags.resolve_categories(s), ['快速书源 ⚡'])

    def test_multiple_categories_kept(self):
        s = {'bookSourceGroup': '漫画书源 🎨,特殊书源 🔞', 'bookSourceType': 0}
        self.assertEqual(tags.resolve_categories(s),
                         ['漫画书源 🎨', '特殊书源 🔞'])


class TestBuildGroups(unittest.TestCase):
    def test_layered_order(self):
        s = {'bookSourceGroup': '通常书源 📂', 'bookSourceType': 0}
        g = tags.build_groups(s, 'overseas_only', 'verified')
        self.assertEqual(g, '通常书源 📂,🌍需外网,✅实测可用')

    def test_cn_only(self):
        s = {'bookSourceGroup': '漫画书源 🎨', 'bookSourceType': 0}
        g = tags.build_groups(s, 'cn_only', 'weak')
        self.assertEqual(g, '漫画书源 🎨,🇨🇳仅国内,⚠️搜索失效')

    def test_proxy_flag_preserved(self):
        s = {'bookSourceGroup': '梯子,通常书源 📂', 'bookSourceType': 0}
        g = tags.build_groups(s, 'both', 'verified')
        self.assertIn('🪜需代理', g)
        self.assertLess(g.index('🪜需代理'), g.index('🌐全球可用'))

    def test_no_duplicate_tags(self):
        s = {'bookSourceGroup': '通常书源 📂,通常书源 📂', 'bookSourceType': 0}
        g = tags.build_groups(s, 'both', 'verified')
        parts = g.split(',')
        self.assertEqual(len(parts), len(set(parts)))


class TestParseExploreUrls(unittest.TestCase):
    def test_newline_format(self):
        got = parse_explore_urls('分类::/cat/1\n榜单::/rank/1')
        self.assertEqual(got, [('分类', '/cat/1'), ('榜单', '/rank/1')])

    def test_json_format(self):
        got = parse_explore_urls('[{"title":"热榜","url":"/hot"}]')
        self.assertEqual(got, [('热榜', '/hot')])

    def test_js_skipped(self):
        self.assertEqual(parse_explore_urls('@js:let a=[];a'), [])

    def test_bare_url(self):
        self.assertEqual(parse_explore_urls('/cat/1'), [('', '/cat/1')])


HTML = """
<html><body>
  <div class="nav"><a href="/cat/1">玄幻</a><a href="/cat/2">都市</a>
    <a href="/login">登录</a></div>
  <ul class="book-list">
    <li class="book-item"><h2 class="title"><a href="/book/101">斗破苍穹</a></h2>
      <span class="author"> 天蚕土豆 </span></li>
    <li class="book-item"><h2 class="title"><a href="/book/102">神印王座</a></h2>
      <span class="author"> 幻尘 </span></li>
    <li class="book-item"><h2 class="title"><a href="/book/103">斗罗大陆</a></h2>
      <span class="author"> 唐家三少 </span></li>
  </ul>
</body></html>
"""


class TestExploreReverse(unittest.TestCase):
    def setUp(self):
        self.doc = parse_html(HTML)

    def test_candidates_found(self):
        cands = propose_explore_candidates(self.doc)
        self.assertTrue(cands)
        self.assertTrue(any(c['bookList'] == '.book-item' for c in cands))

    def test_rules_are_relative(self):
        cands = propose_explore_candidates(self.doc)
        for c in cands:
            # name/bookUrl 必须是相对书单元素的写法，不能带 @css: 前缀
            self.assertFalse(c['name'].startswith('@css:'))
            self.assertFalse(c['bookUrl'].startswith('@css:'))

    def test_synthesize_category_links(self):
        got = synthesize_explore_urls(self.doc, 'https://example.com')
        titles = [t for t, _ in got]
        self.assertIn('玄幻', titles)
        self.assertIn('都市', titles)
        # 登录页不该被当成分类
        self.assertNotIn('登录', titles)


if __name__ == '__main__':
    unittest.main()
