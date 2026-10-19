# -*- coding: utf-8 -*-
"""运行配置：校验节点、关键词、超时、并发。"""
import json
import os

DEFAULT_USER_AGENT = (
    'Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 (KHTML, like Gecko) '
    'Chrome/120.0.0.0 Mobile Safari/537.36'
)

DEFAULT_CONFIG = {
    'servers': [
        {'name': 'aliyun', 'host': 'aliyun', 'region': 'cn', 'label': '国内线路'},
        {'name': 'rack-nerd', 'host': 'rack-nerd', 'region': 'overseas', 'label': '海外线路'},
    ],
    'keywords': ['修真', '剑', '都市', '斗破苍穹'],
    'timeout': 25,
    'threads': 10,
    'user_agent': DEFAULT_USER_AGENT,
    'js_runtime': 'node',
}


def load_config(path=None):
    """读取配置；未提供路径时返回内置默认值。"""
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))
    if not path:
        return cfg
    if not os.path.exists(path):
        raise FileNotFoundError('配置文件不存在: %s' % path)
    with open(path, 'r', encoding='utf-8') as fh:
        user = json.load(fh)
    for key, value in user.items():
        if key == 'servers' and value:
            cfg['servers'] = value
        else:
            cfg[key] = value
    return cfg


def config_path(name):
    """在仓库 config/ 目录下找配置文件。"""
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(here, 'config', name)
