# -*- coding: utf-8 -*-
"""快速对比两个节点的结果分布（开发辅助脚本）。"""
import json
import sys

DEAD = {'net_error', 'http_error', 'no_rule'}
ALIVE = {'ok', 'weak', 'nores', 'blocked', 'api_quirk'}


def load(path):
    with open(path, 'r', encoding='utf-8') as fh:
        return dict((x['i'], x) for x in json.load(fh))


def main():
    a = load(sys.argv[1])
    b = load(sys.argv[2])
    src = json.load(open(sys.argv[3], encoding='utf-8'))
    both_bad, cn_ok, ov_ok, both_ok = [], [], [], []
    for i in sorted(a):
        sa, sb = a[i]['status'], b[i]['status']
        if sa in DEAD and sb in DEAD:
            both_bad.append(i)
        elif sa in ALIVE and sb in ALIVE:
            both_ok.append(i)
        elif sa in ALIVE:
            cn_ok.append(i)
        elif sb in ALIVE:
            ov_ok.append(i)
    print('A=%s  B=%s' % (sys.argv[1], sys.argv[2]))
    print('  两台都不可用 : %d' % len(both_bad))
    print('  两台都可用   : %d' % len(both_ok))
    print('  仅国内可用   : %d' % len(cn_ok))
    print('  仅海外可用   : %d' % len(ov_ok))
    print('  合计         : %d' % (len(both_bad) + len(both_ok) +
                                    len(cn_ok) + len(ov_ok)))
    if len(sys.argv) > 4 and sys.argv[4] == 'list':
        print('\n--- 仅海外可访问（需外网）---')
        for i in ov_ok:
            print('  %-28s %-40s A=%-12s B=%s' % (
                a[i].get('name'), a[i].get('url'), a[i]['status'], b[i]['status']))
        print('\n--- 仅国内可访问 ---')
        for i in cn_ok:
            print('  %-28s %-40s A=%-12s B=%s' % (
                a[i].get('name'), a[i].get('url'), a[i]['status'], b[i]['status']))
        print('\n--- 两台都不可用（将被剔除）---')
        for i in both_bad:
            print('  %-28s %-40s A=%-12s B=%s' % (
                a[i].get('name'), a[i].get('url'), a[i]['status'], b[i]['status']))


if __name__ == '__main__':
    main()
