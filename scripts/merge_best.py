# -*- coding: utf-8 -*-
"""把同一节点的多轮结果合成"最好的一次"观测。

背景：同一个站点在两轮里可能给出完全相反的结论——一轮 net_error（网络
抖动 / 被 WAF 弹了），下一轮 ok（站点其实一直活着）。判断"这个书源能不能
用"时，应该取**所有观测里最好的一次**，而不是被某一次抖动误杀。

规则（刻意保守，只加不减）：

- 以 ``--base`` 为准；
- ``--extra`` 里的记录只有在 base 处于**失败**状态（net_error / http_error）
  且 extra 是**存活**状态时才覆盖 base；
- 反过来绝不用旧的失败结果去盖掉新一轮的成功结果。
"""
import argparse
import json
import os

FAILED = {'net_error', 'http_error'}
ALIVE = {'ok', 'weak', 'nores', 'blocked', 'api_quirk'}


def load(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding='utf-8') as fh:
        return json.load(fh)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--base', required=True, help='基准结果文件（新一轮）')
    ap.add_argument('--extra', action='append', default=[],
                    help='补充结果文件（更早轮次的重测），可重复')
    ap.add_argument('--out', required=True)
    args = ap.parse_args()

    base = {e.get('i'): e for e in load(args.base)}
    order = [e.get('i') for e in load(args.base)]
    changed = 0
    for p in args.extra:
        for e in load(p):
            i = e.get('i')
            if i is None:
                continue
            cur = base.get(i)
            if cur is None:
                base[i] = e
                order.append(i)
                continue
            if cur.get('status') in FAILED and e.get('status') in ALIVE:
                base[i] = e
                changed += 1
    out = [base[i] for i in order if i in base]
    with open(args.out, 'w', encoding='utf-8') as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1)
    print('%s: %d 条，补充观测覆盖 %d 条 -> %s'
          % (os.path.basename(args.base), len(out), changed, args.out))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
