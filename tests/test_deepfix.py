# -*- coding: utf-8 -*-
"""深链修复（ruleToc / ruleContent 反推）单元测试。"""
import unittest

from legado_validator import deepfix
from legado_validator.engine import parse_html, rule_items, eval_rule


TOC_HTML = '''<html><body>
<div class="nav"><a href="/">首页</a><a href="/sort/">分类</a></div>
<div class="chapter-list">
  <ul>
    <li><a href="/book/1/1001.html">第一章 起风</a></li>
    <li><a href="/book/1/1002.html">第二章 落雨</a></li>
    <li><a href="/book/1/1003.html">第三章 长夜</a></li>
    <li><a href="/book/1/1004.html">第四章 破晓</a></li>
  </ul>
</div>
</body></html>'''

CONTENT_HTML = '''<html><body>
<div class="header">书名：测试</div>
<div id="content">
  这是正文的第一段，讲述主角在雨夜里穿过长廊，遇到守夜人问询来历，
  他只答了一句不必深究，便继续朝灯火通明的方向走去，靴子踩在积水里，
  溅起的水花在路灯下像一把碎掉的星子，很快又被夜色吞没。
  这是正文的第二段，风从窗缝挤进来，吹得纸页哗哗作响，屋外的猫叫了两声，
  随即沿着屋檐跑远。他没有抬头，只是把手里的信又看了一遍，纸上只有
  短短两行字，字迹很淡，像是写字的人当时手抖得厉害。
  这是正文的第三段，天亮之前最难熬，屋子里安静得能听见钟摆的声响，
  他把灯芯挑亮了一点，重新翻开那本卷了边角的旧书，从昨天停下的地方
  接着往下读。窗外的天色由深灰变成浅灰，最后泛出一点鱼肚白。
  这是正文的第四段，也不知过了多久，楼下终于有了动静，脚步声由远及近，
  有人在楼道里低声说话，钥匙碰撞的声音清脆地响了一下，门被推开了。
</div>
<div class="footer">上一章 下一章</div>
</body></html>'''


class TestProposeTocRules(unittest.TestCase):
    """从目录页反推章节规则。"""

    def setUp(self):
        self.doc = parse_html(TOC_HTML)

    def test_finds_chapter_container(self):
        rules, diag = deepfix.propose_toc_rules(self.doc, 'example.com')
        self.assertTrue(rules, diag)
        self.assertIn('chapterList', rules)
        self.assertIn('chapterName', rules)
        self.assertIn('chapterUrl', rules)

    def test_chapter_list_matches_chapters(self):
        rules, _ = deepfix.propose_toc_rules(self.doc, 'example.com')
        items = rule_items(rules['chapterList'], doc=self.doc)
        self.assertGreaterEqual(len(items), 3)

    def test_chapter_url_resolves_relative_to_item(self):
        rules, _ = deepfix.propose_toc_rules(self.doc, 'example.com')
        items = rule_items(rules['chapterList'], doc=self.doc)
        url = eval_rule(rules['chapterUrl'], doc=self.doc, item=items[0])
        self.assertTrue(url)
        self.assertIn('/book/1/', str(url[0]))

    def test_no_chapters_returns_none(self):
        doc = parse_html('<html><body><div><a href="/">首页</a></div></body></html>')
        rules, diag = deepfix.propose_toc_rules(doc, 'example.com')
        self.assertIsNone(rules)
        self.assertFalse(diag['ok'])


class TestProposeContentRule(unittest.TestCase):
    """从章节页反推正文规则。"""

    def test_finds_content_container(self):
        doc = parse_html(CONTENT_HTML)
        rule, diag = deepfix.propose_content_rule(doc)
        self.assertTrue(rule, diag)
        text = ' '.join(eval_rule(rule, doc=doc))
        self.assertGreaterEqual(len(text.strip()), deepfix.MIN_CONTENT_CHARS)

    def test_short_page_returns_none(self):
        doc = parse_html('<html><body><p>太短了</p></body></html>')
        rule, diag = deepfix.propose_content_rule(doc)
        self.assertIsNone(rule)
        self.assertFalse(diag['ok'])


if __name__ == '__main__':
    unittest.main()
