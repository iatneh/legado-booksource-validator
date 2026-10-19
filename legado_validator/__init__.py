# -*- coding: utf-8 -*-
"""legado 书源校验器。

对 legado 书源 JSON 里的每条规则做真实网络校验，区分"仅国内可访问"与
"仅海外可访问"，输出可直接导入阅读的合集书源文件。

典型流程::

    python -m legado_validator resolve  --src bookSource.json --out spec.json
    python -m legado_validator validate --src bookSource.json --spec spec.json --out res.json
    python -m legado_validator merge    --src bookSource.json \
        --result aliyun=res_aliyun.json --result rack-nerd=res_rack.json --out-dir dist
"""

__version__ = "1.0.0"

__all__ = ["__version__"]
