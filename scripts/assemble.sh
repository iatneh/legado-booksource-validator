#!/usr/bin/env bash
# 汇总两台节点的产出 -> 打补丁 -> 重测修复项 -> 合并 -> 出报告
set -euo pipefail

cd "$(dirname "$0")/.."
DIST=${1:-dist}
SRC=$DIST/bookSource.json

echo "== 拉取两台节点产出 =="
for h in aliyun rack-nerd; do
  scp -q $h:/tmp/legado-v7/res_$h.json $DIST/ 2>/dev/null || true
done
scp -q aliyun:/tmp/legado-v7/fixed_aliyun.json $DIST/ 2>/dev/null || true
scp -q aliyun:/tmp/legado-v7/explore_aliyun.json $DIST/ 2>/dev/null || true
scp -q rack-nerd:/tmp/legado-v7/fixed_rn.json $DIST/ 2>/dev/null || true
scp -q rack-nerd:/tmp/legado-v7/explore_rn.json $DIST/ 2>/dev/null || true
ls -la $DIST/*.json | grep -v bookSource

echo "== 合并修复 + 发现页补丁 =="
python3 -m legado_validator patch --src $SRC \
  --repair aliyun=$DIST/fixed_aliyun.json \
  --repair rack-nerd=$DIST/fixed_rn.json \
  --explore aliyun=$DIST/explore_aliyun.json \
  --explore rack-nerd=$DIST/explore_rn.json \
  --out $DIST/patched.json

echo "== 上传补丁后的书源，准备重测修复项 =="
for h in aliyun rack-nerd; do
  scp -q $DIST/patched.json $h:/tmp/legado-v8/ && echo "  -> $h"
done
