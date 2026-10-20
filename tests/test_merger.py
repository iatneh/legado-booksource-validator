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
        # 重算时访问范围标签整体替换，不会叠加出两个
        for s in again['kept']:
            self.assertEqual(s['bookSourceGroup'].count('🌍需外网'), 0)
            self.assertEqual(s['bookSourceGroup'].count('🌐全球可用'), 1)

    def test_group_rebuilt_from_taxonomy(self):
        # 原始 group 里的"暂不可用"等状态标签要被实测结果替换
        out = merge(self.sources, self.results)
        for s in out['kept']:
            self.assertNotIn('暂不可用', s['bookSourceGroup'])
            self.assertNotIn('人机验证', s['bookSourceGroup'])
            self.assertIn('✅实测可用', s['bookSourceGroup'])

    def test_verified_subset(self):
        out = merge(self.sources, self.results)
        self.assertEqual(len(out['verified']), 3)

    def test_validation_metadata_present(self):
        out = merge(self.sources, self.results)
        v = out['kept'][0]['_validation']
        self.assertIn('servers', v)
        self.assertIn('access', v)
        self.assertIn('quality', v)


class TestDropDuplicates(unittest.TestCase):
    """重复书源剔除：被剔除的源不进入任何产出。"""

    def setUp(self):
        self.sources = [src('A', 'https://a.com'), src('B', 'https://b.com'),
                        src('C', 'https://c.com')]
        self.results = {
            'aliyun': [res(0, 'ok'), res(1, 'ok'), res(2, 'ok')],
            'rack-nerd': [res(0, 'ok'), res(1, 'ok'), res(2, 'ok')],
        }

    def test_dropped_source_leaves_every_output(self):
        key = ('B', 'https://b.com')
        out = merge(self.sources, self.results,
                    drop_keys={key: {'searchEndpoint': 'b.com/s',
                                      'keptAs': 'A'}})
        self.assertEqual([s['bookSourceName'] for s in out['kept']], ['A', 'C'])
        self.assertEqual(len(out['verified']), 2)
        self.assertEqual(len(out['overseas']), 0)
        self.assertEqual(len(out['cn_only']), 0)

    def test_dropped_record_keeps_explanation(self):
        key = ('B', 'https://b.com')
        out = merge(self.sources, self.results,
                    drop_keys={key: {'searchEndpoint': 'b.com/s',
                                      'keptAs': 'A'}})
        self.assertEqual(len(out['dropped']), 1)
        d = out['dropped'][0]
        self.assertEqual(d['bookSourceName'], 'B')
        self.assertEqual(d['bookSourceUrl'], 'https://b.com')
        self.assertEqual(d['searchEndpoint'], 'b.com/s')
        self.assertEqual(d['keptAs'], 'A')

    def test_drop_is_not_counted_as_invalid(self):
        out = merge(self.sources, self.results,
                    drop_keys={('B', 'https://b.com'): None})
        self.assertEqual(len(out['removed']), 0)
        self.assertEqual(out['stats']['verdict_keep'], 2)
        self.assertEqual(out['stats']['verdict_invalid'], 0)

    def test_drop_accepts_plain_key_set(self):
        out = merge(self.sources, self.results,
                    drop_keys={('B', 'https://b.com')})
        self.assertEqual(len(out['dropped']), 1)
        self.assertEqual(len(out['kept']), 2)


if __name__ == '__main__':
    unittest.main()
