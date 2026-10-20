#!/usr/bin/env bash
# 优化流程收尾：
#   打补丁 -> 双节点重测 -> 多轮观测取最好一次 -> 合并 -> 去重 -> 派生全套产物 -> 校验
# 用法：bash scripts/finalize_optimize.sh
set -euo pipefail
cd /home/xiayang/projects/github.com/iatneh/legado-booksource-validator
D=dist

echo "=== 1) 打补丁（搜索层 + 深链层） ==="
python3 -m legado_validator patch --src $D/patched.json \
  --repair rn_search=$D/repair_rn_v3.json \
  --repair rn_deep=$D/deeprn_v3.json \
  --repair ali_search=$D/repair_ali_v3.json \
  --repair ali_deep=$D/deepali_v3.json \
  --out $D/patched_v3.json

echo "=== 2) 双节点重测（请求均在节点本机发出） ==="
for n in aliyun rack-nerd; do scp -q $D/patched_v3.json "$n:/tmp/legado-v14/"; done
ssh aliyun 'export PATH=$HOME/opt/node-v20.18.1-linux-x64/bin:$PATH; cd /tmp/legado-v14 && python3 -m legado_validator validate --src patched_v3.json --spec spec_ali_v2.json --out res_ali_v4.json --server aliyun --threads 6 --timeout 25' &
ssh rack-nerd 'cd /tmp/legado-v14 && python3 -m legado_validator validate --src patched_v3.json --spec spec_rn_v2.json --out res_rn_v4.json --server rack-nerd --threads 8 --timeout 25' &
wait
scp -q aliyun:/tmp/legado-v14/res_ali_v4.json $D/
scp -q rack-nerd:/tmp/legado-v14/res_rn_v4.json $D/
echo "重测结果已拉回"

echo "=== 3) 裁剪失效重试覆盖（避免把已修好的源又判成失效） ==="
python3 scripts/filter_dead_override.py --dead $D/res_aliyun_dead.json \
  --fresh $D/res_ali_v4.json --fresh $D/res_rn_v4.json --out $D/res_ali_dead_v4.json
python3 scripts/filter_dead_override.py --dead $D/res_rn_dead.json \
  --fresh $D/res_ali_v4.json --fresh $D/res_rn_v4.json --out $D/res_rn_dead_v4.json

echo "=== 4) 多轮观测取最好一次 ==="
# 只在"新一轮是网络失败、旧一轮是存活"时补回来；绝不拿旧结论去盖新一轮的成功，
# 也不拿旧引擎的结论去翻新一轮"页面活着但取不到条目"的判定。
python3 scripts/merge_best.py --base $D/res_ali_v4.json \
  --extra $D/res_ali_v3.json --extra $D/res_ali_retry_v3.json --extra $D/res_ali_dead_v4.json \
  --out $D/res_ali_best.json
python3 scripts/merge_best.py --base $D/res_rn_v4.json \
  --extra $D/res_rn_v3.json --extra $D/res_rn_dead_v4.json \
  --out $D/res_rn_best.json

NOTE_ARGS=(
  --note "节点出口：aliyun 阿里云北京（国内）、rack-nerd 洛杉矶（海外），请求均在本机发出"
  --note "规则修复：从真实页面结构反推 bookList/name/author/bookUrl，修复后已重新实测"
  --note "发现页补全：补全缺失的 ruleExplore（496→650）与 exploreUrl（662→751），共 192 条源"
  --note "起点系 3 个书源：桌面站 www.qidian.com 被 WAF 人机验证拦截（HTTP 202 + probe.js），已整体切到移动版 m.qidian.com：发现页=6 个榜单 + 22 个一级分类，搜索=/soushu/（支持翻页），实测书名/作者/分类/目录(171 章)/正文全通"
  --note "规则引擎对齐阅读真实语义：按 Legado 源码核实并补齐 @css: 子代选择器(>)、@js: 拼接、##正则## 两种写法（多一个 ## 时匹配不到返回空串）"
  --note "深链链路修正：目录规则作用在 ruleBookInfo.tocUrl 指向的目录页上（无该规则时用书籍页本身），与 Legado 一致"
  --note "JS 沙箱对齐 Legado：java.ajax 返回 String、java.get/post 返回 Jsoup Response、java.connect 带 raw()、Packages.org.jsoup.Jsoup 可用"
  --note "深链修复：从真实目录页/章节页反推 ruleToc.chapterList 与 ruleContent.content，并实测验证"
  --note "选择器语义修正（对照 AnalyzeByJSoup.kt）：bookList/chapterList 末段按 getElements 语义当选择器（支持 children 取直接子元素）；:nth-child 按全部子元素计数、:nth-of-type 才按同标签；:eq(n) 改集合层；A+B / A~B 恢复为兄弟选择器；JS 沙箱 select() 改为返回最右匹配"
  --note "多轮观测取最好一次：同一节点多轮结果按 best-of 合成（只救网络失败，不翻旧引擎的结论），避免单次网络抖动把可用书源误判成失效"
  --note "重复书源剔除：按搜索端点（host+path）去重，端点取节点本机 JS 解析器还原的真实请求地址；同名不同域名的镜像站不删"
)

echo "=== 5) 合并 ==="
python3 -m legado_validator merge --src $D/patched_v3.json \
  --result aliyun=$D/res_ali_best.json --result rack-nerd=$D/res_rn_best.json \
  --override aliyun=$D/res_ali_dead_v4.json --override rack-nerd=$D/res_rn_dead_v4.json \
  --out-dir $D/final "${NOTE_ARGS[@]}"

echo "=== 6) 去重 ==="
python3 scripts/dedup_sources.py --src $D/final/final_union.json --out-dir $D \
  --spec $D/spec_rn_v2.json --spec $D/spec_ali_v2.json

echo "=== 7) 合并（带去重） ==="
python3 -m legado_validator merge --src $D/patched_v3.json \
  --result aliyun=$D/res_ali_best.json --result rack-nerd=$D/res_rn_best.json \
  --override aliyun=$D/res_ali_dead_v4.json --override rack-nerd=$D/res_rn_dead_v4.json \
  --drop-duplicates $D/removed_duplicates.json \
  --out-dir $D/final "${NOTE_ARGS[@]}"

echo "=== 8) 校验产物 ==="
python3 scripts/verify_output.py $D/final $D/bookSource.json
