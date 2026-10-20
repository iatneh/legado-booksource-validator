# -*- coding: utf-8 -*-
"""把"双端都失败"的重试结果裁剪成只覆盖**现在仍然失败**的源。

背景：``res_*_dead.json`` 是上一轮对双端失败源的复测结果。修复之后，
有些源已经能用了，如果还按老结果覆盖，会把修好的源又判成失效。
所以覆盖前先按最新结果裁一遍。
"""
import argparse
import json
import os

ALIVE = {'ok', 'weak', 'nores', 'blocked', 'api_quirk'}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dead', required=True, help='要裁剪的 dead 覆盖文件')
    ap.add_argument('--fresh', action='append', required=True,
                    help='最新一轮的校验结果文件（可重复）')
    ap.add_argument('--out', required=True)
    args = ap.parse_args()

    fresh = {}
    for p in args.fresh:
        if not os.path.exists(p):
            continue
        with open(p, encoding='utf-8') as fh:
            for e in json.load(fh):
                fresh.setdefault(e.get('i'), []).append(e)
    with open(args.dead, encoding='utf-8') as fh:
        dead = json.load(fh)
    keep = []
    dropped = 0
    for r in dead:
        i = r.get('i')
        recs = fresh.get(i) or []
        if any((e.get('status') or '') in ALIVE for e in recs):
            dropped += 1
            continue
        keep.append(r)
    with open(args.out, 'w', encoding='utf-8') as fh:
        json.dump(keep, fh, ensure_ascii=False, indent=1)
    print('%s: 保留 %d 条，剔除（已恢复）%d 条 -> %s'
          % (os.path.basename(args.dead), len(keep), dropped, args.out))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
