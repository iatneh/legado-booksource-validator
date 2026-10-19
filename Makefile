PY ?= python3
SRC ?= examples/sample_bookSource.json
CFG ?= config/servers.example.json
OUT ?= dist

.PHONY: help install test lint resolve validate merge report run clean

help:
	@echo "make install   安装依赖（requests）"
	@echo "make test     运行单元测试"
	@echo "make lint     语法检查"
	@echo "make resolve  本机解析搜索规则 -> OUT/spec.json"
	@echo "make validate 本机校验书源 -> OUT/res_local.json"
	@echo "make merge    合并多节点结果 -> OUT/"
	@echo "make run      一键：分发到多节点执行并合并（需 SSH）"

install:
	$(PY) -m pip install -r requirements.txt

test:
	$(PY) -m unittest discover -s tests -v

lint:
	$(PY) -m compileall -q legado_validator tests

resolve: | $(OUT)
	$(PY) -m legado_validator resolve --src $(SRC) --out $(OUT)/spec.json

validate: | $(OUT)
	$(PY) -m legado_validator validate --src $(SRC) --spec $(OUT)/spec.json \
		--out $(OUT)/res_local.json --server local

merge: | $(OUT)
	$(PY) -m legado_validator merge --src $(SRC) \
		--result aliyun=$(OUT)/res_aliyun.json \
		--result rack-nerd=$(OUT)/res_rack-nerd.json --out-dir $(OUT)

report: | $(OUT)
	$(PY) -m legado_validator report --src $(SRC) \
		--result aliyun=$(OUT)/res_aliyun.json \
		--result rack-nerd=$(OUT)/res_rack-nerd.json --out $(OUT)/report.md

run: | $(OUT)
	$(PY) -m legado_validator --config $(CFG) run-nodes --src $(SRC) --out-dir $(OUT)

$(OUT):
	mkdir -p $(OUT)

clean:
	rm -rf $(OUT) work build dist *.egg-info
	find . -name '__pycache__' -type d -prune -exec rm -rf {} +
