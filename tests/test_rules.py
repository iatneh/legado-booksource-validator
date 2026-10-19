# -*- coding: utf-8 -*-
"""请求构造 / 反爬识别单元测试。"""
import unittest

from legado_validator.http import detect_block
from legado_validator.rules import (abs_url, keywords_for, norm_base, parse_body,
                                    src_headers, swap_kw)


class TestNormalizeBase(unittest.TestCase):
    def test_scheme_prefix(self):
        self.assertEqual(norm_base('//example.com'), 'https://example.com')

    def test_https_kept(self):
        self.assertEqual(norm_base('https://a.com/x'), 'https://a.com/x')

    def test_bare_domain(self):
        self.assertEqual(norm_base('a.com'), 'https://a.com')

    def test_non_url(self):
        self.assertEqual(norm_base('苹果通用API接口聚合'), '')


class TestAbsUrl(unittest.TestCase):
    def test_relative(self):
        self.assertEqual(abs_url('https://a.com/book/', '1.html'),
                         'https://a.com/book/1.html')

    def test_root_relative(self):
        self.assertEqual(abs_url('https://a.com/x', '/y'), 'https://a.com/y')

    def test_absolute_kept(self):
        self.assertEqual(abs_url('https://a.com', 'https://b.com/z'),
                         'https://b.com/z')

    def test_empty(self):
        self.assertEqual(abs_url('https://a.com', ''), '')


class TestSwapKeyword(unittest.TestCase):
    def test_replaces_encoded(self):
        spec = {'url': 'https://a.com/s?k=%E4%BF%AE%E7%9C%9F'}
        out = swap_kw(spec, '修真', '都市')
        self.assertIn('%E9%83%BD%E5%B8%82', out['url'])

    def test_returns_none_when_absent(self):
        self.assertIsNone(swap_kw({'url': 'https://a.com/x'}, '修真', '都市'))


class TestKeywords(unittest.TestCase):
    def test_check_keyword_first(self):
        src = {'ruleSearch': {'checkKeyWord': '长生界'}}
        self.assertEqual(keywords_for(src)[0], '长生界')

    def test_fallback_keywords(self):
        kws = keywords_for({'ruleSearch': {}})
        self.assertIn('斗破苍穹', kws)
        self.assertLessEqual(len(kws), 4)


class TestSrcHeaders(unittest.TestCase):
    def test_json_string(self):
        out = src_headers({'header': '{"User-Agent": "x"}'})
        self.assertEqual(out['User-Agent'], 'x')

    def test_invalid_json_ignored(self):
        self.assertEqual(src_headers({'header': 'not json'}), {})

    def test_dict_form(self):
        self.assertEqual(src_headers({'header': {'A': 'b'}}), {'A': 'b'})


class TestParseBody(unittest.TestCase):
    def test_json(self):
        js, doc = parse_body({'body': '{"a": 1}', 'ct': 'application/json'})
        self.assertEqual(js, {'a': 1})
        self.assertIsNone(doc)

    def test_html(self):
        js, doc = parse_body({'body': '<div>x</div>', 'ct': 'text/html'})
        self.assertIsNone(js)
        self.assertIsNotNone(doc)


class TestDetectBlock(unittest.TestCase):
    def test_cloudflare_challenge(self):
        self.assertEqual(detect_block(200, '<title>Just a moment...</title>'),
                         'cf_challenge')

    def test_captcha_chinese(self):
        self.assertEqual(detect_block(200, '<div>请输入验证码</div>'),
                         'captcha_zh')

    def test_forbidden_title(self):
        self.assertEqual(detect_block(200, '<title>403 Forbidden</title>'),
                         'forbidden_page')

    def test_404(self):
        self.assertEqual(detect_block(404, 'gone'), 'http_404')

    def test_normal_page(self):
        self.assertIsNone(detect_block(200, '<html><body>ok</body></html>'))


if __name__ == '__main__':
    unittest.main()
