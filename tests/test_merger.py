# -*- coding: utf-8 -*-
"""合并 / 打标逻辑单元测试。"""
import unittest

from legado_validator.merger import classify, merge


def src(name, url='https://example.com'):
    return {'bookSourceName': name, 'bookSourceUrl': url,
            'bookSourceGroup': '测试分组', 'ruleSearch': {'bookList': '@css:.x'}}


def res(index, status, **kw):
    out = {'i': index, 'status': status, 'http': 200, 'ms': 10, 'items': 0,
           'err': None, 'block': None, 'deep': {'book': False, 'toc': False,
                                                'content': False, 'reason': ''}}
    out.update(kw)
    return out


class TestClassify(unittest.TestCase):
    def test_both_ok(self):
        self.assertEqual(classify('ok', 'ok'), ('keep', 'both', 'verified'))

    def test_cn_only(self):
        self.assertEqual(classify('ok', 'net_error'),
                         ('keep', 'cn_only', 'verified'))

    def test_overseas_only(self):
        self.assertEqual(classify('net_error', 'ok'),
                         ('keep', 'overseas_only', 'verified'))

    def test_both_dead_is_invalid(self):
        self.assertEqual(classify('net_error', 'net_error')[0], 'invalid')

    def test_one_dead_other_unresolved_is_kept(self):
        verdict, access, _ = classify('net_error', 'unsupported')
        self.assertEqual(verdict, 'keep')
        self.assertEqual(access, 'unverified')

    def test_both_unresolved_is_kept(self):
        verdict, access, quality = classify('unsupported', 'unsupported')
        self.assertEqual(verdict, 'keep')
        self.assertEqual(access, 'unverified')
        self.assertEqual(quality, 'unverified')

    def test_blocked_is_alive(self):
        verdict, access, quality = classify('blocked', 'blocked')
        self.assertEqual(verdict, 'keep')
        self.assertEqual(access, 'both')
        self.assertEqual(quality, 'antibot')

    def test_api_quirk_is_alive(self):
        self.assertEqual(classify('api_quirk', 'api_quirk')[1], 'both')


class TestMerge(unittest.TestCase):
    def setUp(self):
        self.sources = [src('A'), src('B'), src('C'), src('D')]
        self.results = {
            'aliyun': [res(0, 'ok'), res(1, 'net_error'), res(2, 'ok'),
                       res(3, 'net_error')],
            'rack-nerd': [res(0, 'ok'), res(1, 'ok'), res(2, 'net_error'),
                          res(3, 'net_error')],
        }

    def test_union_keeps_everything_reachable(self):
        out = merge(self.sources, self.results)
        names = sorted(s['bookSourceName'] for s in out['kept'])
        self.assertEqual(names, ['A', 'B', 'C'])

    def test_both_dead_removed(self):
        out = merge(self.sources, self.results)
        self.assertEqual(len(out['removed']), 1)
        self.assertEqual(out['removed'][0]['bookSourceName'], 'D')

    def test_overseas_tag_applied(self):
        # B: aliyun 失败 / rack-nerd 通 -> 需外网
        out = merge(self.sources, self.results)
        b = [s for s in out['kept'] if s['bookSourceName'] == 'B'][0]
        self.assertIn('🌍需外网', b['bookSourceGroup'])
        self.assertIn('需外网访问', b['bookSourceComment'])

    def test_cn_tag_applied(self):
        # C: aliyun 通 / rack-nerd 失败 -> 仅国内
        out = merge(self.sources, self.results)
        c = [s for s in out['kept'] if s['bookSourceName'] == 'C'][0]
        self.assertIn('🇨🇳仅国内', c['bookSourceGroup'])
        self.assertEqual(len(out['overseas']), 1)
        self.assertEqual(out['overseas'][0]['bookSourceName'], 'B')

    def test_tag_not_duplicated_on_remerge(self):
        out = merge(self.sources, self.results)
        again = merge(out['kept'], {
            'aliyun': [res(i, 'ok') for i in range(len(out['kept']))],
            'rack-nerd': [res(i, 'ok') for i in range(len(out['kept']))],
        })
        tagged = [s for s in again['kept'] if '🌍需外网' in s['bookSourceGroup']]
        self.assertEqual(len(tagged), 1)
        self.assertEqual(tagged[0]['bookSourceGroup'].count('🌍需外网'), 1)

    def test_verified_subset(self):
        out = merge(self.sources, self.results)
        self.assertEqual(len(out['verified']), 3)

    def test_validation_metadata_present(self):
        out = merge(self.sources, self.results)
        v = out['kept'][0]['_validation']
        self.assertIn('servers', v)
        self.assertIn('access', v)
        self.assertIn('quality', v)


if __name__ == '__main__':
    unittest.main()
