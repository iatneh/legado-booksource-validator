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
| 深链验证 | 搜索 → 书籍详情 → 目录 → 章节正文，逐级确认 |
| 反爬识别 | Cloudflare 挑战、验证码、人机验证、403/404 页面 |
| 出口 IP 正确 | 请求在目标节点本机发出，国内外可达性结论可信 |
| 自动打标 | 需外网的源分组名追加 🌍需外网，备注首行写入原因；仅国内的标 🇨🇳仅国内 |

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

# 3. 合并多节点结果，取合集并打标签
python3 -m legado_validator merge --src bookSource.json \
    --result aliyun=dist/res_aliyun.json \
    --result rack-nerd=dist/res_rack-nerd.json --out-dir dist
```

## 产出

| 文件 | 含义 |
| --- | --- |
| `final_union.json` | 合集书源，可直接导入阅读；每条带 `_validation` 校验元数据 |
| `final_verified.json` | 严格子集：搜索接口真实返回过书单条目的源 |
| `needs_overseas.json` | 仅海外可访问（需外网）的源，已打 🌍需外网 标签 |
| `removed_invalid.json` | 被剔除的源及每个节点上的失败原因 |
| `report.md` | Markdown 报告：质量分布 / 访问范围分布 / 各类清单 |

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
  merger.py      # 多节点合并、取合集、打标签
  reporter.py    # Markdown 报告
  cli.py         # 命令行入口
  js/resolve.js  # Node 沙箱：执行 `js:` 规则
tests/           # 单元测试（unittest，57 条）
```

## 开发

```bash
make test     # 单元测试
make lint     # 语法检查
```

## License

MIT
