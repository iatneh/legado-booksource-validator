# legado-booksource-validator

Legado 书源校验器。**在多个网络节点上真实实测**每一条书源的搜索接口，产出：

- 剔除两台机器都连不通的无效书源
- 区分「仅国内可访问」和「仅海外可访问（需外网）」
- 可直接导入阅读（Legado）的合集书源 JSON，并给需要外网的源打标签

普通书源规则没法用正则判断死活，必须真的把搜索请求打出去。本项目自带一个
Legado 规则引擎（HTML 解析 + CSS / JSONPath 求值）和一个 Node 沙箱来执行
`js:` 规则，因此**校验结果反映的是真实可用性**，而不是「域名还在不在」。

## 能力

| 能力 | 说明 |
| --- | --- |
| 规则求值 | 支持 `@css:` 选择器、Legacy `class.x@tag.y@text` 链式规则、`##正则##` 清洗、JSONPath（`$.data[*]`、`a && b`） |
| JS 规则 | Node 沙箱执行 `@js:` / `<js>` 规则，垫片覆盖 `java.ajax/get/post`、`cookie`、`cache`、`source`、`Packages`、md5/base64 |
| 深链验证 | 搜索 → 书籍详情 → 目录 → 章节正文，逐级确认；JSON 接口源按条目展开 `{{$.id}}` URL 模板 |
| 反爬识别 | Cloudflare 挑战、验证码、人机验证、403/404 页面 |
| 出口 IP 正确 | 请求在目标节点本机发出，国内外可达性结论可信 |
| 自动打标 | 重组为「内容分类 + 访问范围 + 质量状态」三层标签：🌐全球可用 / 🇨🇳仅国内 / 🌍需外网 + ✅实测可用 / ⚠️搜索失效 / 🔧接口异常 / 🚫人机验证 |
| 规则修复 | 站点存活但选择器过时（改版）时，从真实页面结构反推新的 bookList/bookUrl/name/author；书单能取到但**书名规则已失效**（阅读里书名为空）的源同样纳入修复 |
| 发现页补全 | 缺 `ruleExplore` 的源自动补规则；连 `exploreUrl` 都缺的，从首页导航合成分类入口 |

## 安装

```bash
python3 -m pip install -r requirements.txt   # 只依赖 requests
```

Node 仅在需要执行 `@js:` 规则时使用（node >= 18）。

## 使用

### 一键跑多节点（推荐）

```bash
cp config/servers.example.json config/servers.json   # 按需改 host
python3 -m legado_validator --config config/servers.json \
    run-nodes --src bookSource.json --out-dir dist
```

`run-nodes` 会自动：把校验器打包投放到每个节点 → 在节点本机跑
`resolve` + `validate` → 把结果拉回本地 → 合并并出报告。

### 分步执行

```bash
# 1. 解析搜索规则 -> 请求规格（需要 node）
python3 -m legado_validator resolve --src bookSource.json --out dist/spec.json

# 2. 在目标节点上做真实校验
python3 -m legado_validator validate --src bookSource.json \
    --spec dist/spec.json --out dist/res_aliyun.json --server aliyun

# 3. 修复"站点活着但选择器过时"的书源
python3 -m legado_validator repair --src bookSource.json \
    --spec dist/spec.json --result dist/res_aliyun.json \
    --out dist/fixed.json --report dist/repair_report.json --server aliyun

# 4. 补全缺失的发现页规则
python3 -m legado_validator explore --src bookSource.json \
    --out dist/explore_fixed.json --report dist/explore_report.json
# 只处理指定下标（不会覆盖已有 ruleExplore 的源；确实要重做就加 --force）
python3 -m legado_validator explore --src bookSource.json --only 12,45,88 \
    --out dist/explore_fixed.json --report dist/explore_report.json

# 5. 把修复/补全结果合并回书源
python3 -m legado_validator patch --src bookSource.json \
    --repair aliyun=dist/fixed.json --explore aliyun=dist/explore_fixed.json \
    --out dist/patched.json

# 6. 合并多节点结果，取合集并打标签
python3 -m legado_validator merge --src dist/patched.json \
    --result aliyun=dist/res_aliyun.json \
    --result rack-nerd=dist/res_rack-nerd.json --out-dir dist
```

`merge` 支持 `--override aliyun=dist/res_fixed.json`：修复后重测的结果按
下标覆盖原结果，保证最终书源里的规则和校验结论出自同一份规则。

## 产出

| 文件 | 含义 |
| --- | --- |
| `final_union.json` | 合集书源，可直接导入阅读；每条带 `_validation` 校验元数据 |
| `final_verified.json` | 严格子集：搜索接口真实返回过书单条目的源 |
| `needs_overseas.json` | 仅海外可访问（需外网）的源，已打 🌍需外网 标签 |
| `cn_only.json` | 仅国内可访问的源，已打 🇨🇳仅国内 标签 |
| `removed_invalid.json` | 被剔除的源及每个节点上的失败原因 |
| `tag_distribution.json` | 重组后的标签组合分布 |
| `report.md` | Markdown 报告：质量分布 / 访问范围分布 / 标签分布 / 各类清单 |

## 标签体系

原始 `bookSourceGroup` 把「内容分类」「站点状态」「访问通道」混在一起，
且存在重复写法（`正版` / `正版书源 🏷`）。合并后按三层重新组织，
顺序固定为 **内容分类 → 访问范围 → 质量状态**：

| 层 | 标签 | 来源 |
| --- | --- | --- |
| 内容分类 | 快速书源 ⚡ / 通常书源 📂 / 文本书源 📚 / 漫画书源 🎨 / 图片书源 📷 / 有声书源 🔊 / 影视频源 🎬 / 轻文书源 📘 / 出版书源 🏛 / 正版书源 🏷 / 同人书源 🎭 / 特殊书源 🔞 / 下载书源 📥 / 文件书源 📦 / 聚合书源 🗂 / 代理书源 🪜 / API 书源 🔌 | 原始标签归一；缺失时按 `bookSourceType` 兜底 |
| 访问范围 | 🌐全球可用 / 🇨🇳仅国内 / 🌍需外网 / ❓访问范围未知 | 两台节点实测 |
| 质量状态 | ✅实测可用 / ⚠️搜索失效 / 🔧接口异常 / 🚫人机验证 / ❓未验证 | 两台节点实测 |

原始的 `人机验证-搜索`、`暂不可用`、`搜索暂不可用` 属于**站点状态**，
一律丢弃并由实测结果重新推导——校验通过的书源不该再挂着「暂不可用」。
`梯子` 会被保留为 `🪜需代理` 标记。

## 判定规则

每个节点上每条书源会被打上以下状态之一：

| 状态 | 含义 |
| --- | --- |
| `ok` | 搜索接口真实返回书单条目（并做深链验证） |
| `weak` | 站点存活、页面可读，但规则含 JS/特殊语法没解析出条目 |
| `nores` | 站点存活返回 200，但搜索无结果（软封禁或规则失效） |
| `api_quirk` | 接口返回 4xx（签名/参数类错误），站点存活 |
| `blocked` | 站点存活但触发反爬（403 / 验证码 / 挑战页） |
| `net_error` | DNS 解析失败、连接被拒、超时、SSL 失败 |
| `http_error` | 404 / 410 |
| `no_rule` | 书源本身没有搜索规则 |
| `unsupported` | 规则无法静态解析（JS 聚合型），未作判定 |

合并时的取舍：

- **两台都 `net_error` / `http_error` / `no_rule`** → 判定为无效，剔除
- **任一台活着**（含 `weak` / `blocked` / `api_quirk`）→ 保留
- 一台死、另一台规则无法解析 → 保留但标为 `unverified`（站点可能被地域屏蔽，不武断剔除）

## 项目结构

```text
legado_validator/
  engine.py      # 规则引擎：HTML 解析 + CSS/JSONPath 求值
  rules.py       # 请求构造、响应解析、关键词替换
  http.py        # 抓取、限速、反爬识别
  validator.py   # 校验主流程 + 深链验证
  repair.py      # 从真实结果页反推搜索规则
  explore.py     # 发现页规则补全 + 首页合成分类入口
  tags.py        # 标签体系重构（分类 / 访问范围 / 质量状态）
  patcher.py     # 把修复与发现页结果合并回书源
  merger.py      # 多节点合并、取合集、打标签
  reporter.py    # Markdown 报告
  cli.py         # 命令行入口
  js/resolve.js  # Node 沙箱：执行 `js:` 规则
  js/legado_js.js # 沙箱底座：HTML 解析 + CSS 选择器 + Jsoup 风格 API
tests/           # 单元测试（unittest，151 条）
```

## 规则引擎与 Legado 的语义对齐

引擎的行为按 Legado 官方源码（`AnalyzeRule.kt` / `AnalyzeByJSoup.kt` /
`JsExtensions.kt`）逐条核实，几处容易踩坑的地方：

| 场景 | Legado 行为 | 本项目 |
| --- | --- | --- |
| `bookList` / `chapterList` 末段 | `getElements` → `ElementsSingle`，末段是**选择器**（tag/class/id/`children`） | 同左；`children` 取直接子元素 |
| `name` / `author` / `bookUrl` 末段 | `getStringList` → `getResultLast`，末段是**属性名** | 同左 |
| `:nth-child(n)` | 父节点下第 n 个**子元素**（不分标签） | 同左 |
| `:nth-of-type(n)` | 父节点下第 n 个**同标签**子元素 | 同左 |
| `:eq(n)` | 整个匹配集合里的第 n 个 | 同左（集合层处理） |
| `A + B` / `A ~ B` | 兄弟关系 | 同左（原先被当后代） |
| `##正则##替换##` | 第四段非空时只取第一个匹配做替换，匹配不到返回空串 | 同左 |
| `java.ajax` / `java.get` | `ajax` 返回 String，`get/post` 返回 Jsoup Response | 同左 |

## 开发

```bash
make test     # 单元测试
make lint     # 语法检查
```

## License

MIT
