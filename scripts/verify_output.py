# -*- coding: utf-8 -*-
"""校验产出文件的基本完整性（开发辅助脚本）。

检查：JSON 可解析、条数、必填字段、标签是否符合三层结构、剔除清单与
保留清单是否互斥且并集等于原始书源数。
"""
import json
import os
import sys

REQUIRED = ('bookSourceName', 'bookSourceUrl', 'bookSourceGroup', 'ruleSearch')


def load(path):
    with open(path, encoding='utf-8') as fh:
        return json.load(fh)


def main():
    out_dir = sys.argv[1]
    src = load(sys.argv[2])
    union = load('%s/final_union.json' % out_dir)
    removed = load('%s/removed_invalid.json' % out_dir)
    overseas = load('%s/needs_overseas.json' % out_dir)
    cn_only = load('%s/cn_only.json' % out_dir)
    verified = load('%s/final_verified.json' % out_dir)
    dup_path = '%s/removed_duplicates.json' % out_dir
    duplicates = load(dup_path) if os.path.exists(dup_path) else []

    problems = []
    print('原始书源        : %d' % len(src))
    print('保留            : %d' % len(union))
    print('剔除（双端不通）: %d' % len(removed))
    print('剔除（重复）    : %d' % len(duplicates))
    print('需外网          : %d' % len(overseas))
    print('仅国内          : %d' % len(cn_only))
    print('实测可用        : %d' % len(verified))

    if len(union) + len(removed) + len(duplicates) != len(src):
        problems.append('保留+剔除无效+剔除重复 (%d) != 原始 (%d)'
                        % (len(union) + len(removed) + len(duplicates), len(src)))

    kept_urls = set(s.get('bookSourceUrl') for s in union)
    rm_urls = set(s.get('bookSourceUrl') for s in removed)
    if kept_urls & rm_urls:
        problems.append('保留与剔除存在重叠: %d' % len(kept_urls & rm_urls))
    for d in duplicates:
        if d.get('bookSourceUrl') in kept_urls:
            problems.append('重复剔除项仍在保留清单中: %s' % d.get('bookSourceName'))
            break

    for i, s in enumerate(union):
        for f in REQUIRED:
            if f not in s:
                problems.append('#%d 缺字段 %s' % (i, f))
        g = s.get('bookSourceGroup') or ''
        if not g:
            problems.append('#%d 分组为空' % i)
        elif ',' not in g:
            problems.append('#%d 分组缺少访问范围/质量标签: %s' % (i, g))
        if not (s.get('ruleSearch') or {}).get('bookList'):
            problems.append('#%d 没有 bookList 规则: %s'
                            % (i, s.get('bookSourceName')))

    ov = set(s.get('bookSourceUrl') for s in overseas)
    cn = set(s.get('bookSourceUrl') for s in cn_only)
    if ov & cn:
        problems.append('需外网与仅国内存在重叠: %d' % len(ov & cn))

    for name, data in (('需外网', overseas), ('仅国内', cn_only)):
        for s in data:
            tag = '🌍需外网' if name == '需外网' else '🇨🇳仅国内'
            if tag not in (s.get('bookSourceGroup') or ''):
                problems.append('%s 缺标签 %s: %s'
                                % (name, tag, s.get('bookSourceName')))
                break

    print()
    if problems:
        print('发现 %d 个问题：' % len(problems))
        for p in problems[:30]:
            print('  - %s' % p)
        return 1
    print('全部检查通过 ✓')
    return 0


if __name__ == '__main__':
    sys.exit(main())
