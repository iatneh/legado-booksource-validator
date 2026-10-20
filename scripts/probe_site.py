# -*- coding: utf-8 -*-
"""探测某个站点在不同 UA / 请求头下能不能拿到正常页面（开发辅助脚本）。"""
import sys

sys.path.insert(0, '.')
from legado_validator.http import fetch  # noqa: E402

UAS = {
    '无 UA': {},
    '移动端(书源自带)': {
        'User-Agent': 'Mozilla/5.0 (Linux; Android 13; A3) AppleWebKit/537.36 '
                      '(KHTML, like Gecko) Chrome/120.0.1601.46 Mobile Safari/537.36'},
    '桌面 Chrome': {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                      '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'},
    '移动端+Referer': {
        'User-Agent': 'Mozilla/5.0 (Linux; Android 13; A3) AppleWebKit/537.36 '
                      '(KHTML, like Gecko) Chrome/120.0.1601.46 Mobile Safari/537.36',
        'Referer': 'https://www.qidian.com/'},
    '桌面+Referer+Accept': {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                      '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Referer': 'https://www.qidian.com/',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'zh-CN,zh;q=0.9'},
}

URLS = [
    'https://www.qidian.com/rank/yuepiao/page1/',
    'https://www.qidian.com/all?chanId=21&siteid=1&page=1',
    'https://m.qidian.com/majax/rank/yuepiaolist?gender=male&pageNum=1',
]

for url in URLS:
    print('===', url)
    for name, h in UAS.items():
        res = fetch(url, 'GET', None, h, 25, None)
        body = res.get('body') or ''
        challenge = 'probe.js' in body or 'C2WF946J0' in body
        print('  %-22s http=%-4s len=%-7s %s' % (
            name, res.get('status'), len(body),
            '【反爬挑战页】' if challenge else ''))
    print()
