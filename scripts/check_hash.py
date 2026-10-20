# -*- coding: utf-8 -*-
"""单独验证 ## 清洗里的正则替换行为（开发辅助脚本）。"""
import re
import sys
sys.path.insert(0, ".")

from legado_validator.engine import apply_hash, split_hash

V = '辰东 · 玄幻 · 417.61万字'
RULE = 'tag.p.1@text##^([^·]+)·.*$##$1'

print('rule       :', RULE)
base, rx, repl = split_hash(RULE)
print('base       :', repr(base))
print('rx         :', repr(rx))
print('repl       :', repr(repl))
print('re.sub 直算 :', repr(re.sub(rx, repl, V)))
print('apply_hash  :', repr(apply_hash(V, rx, repl)))
print()
print('替换串是不是被当成字面量？', repr(re.sub(rx, 'X', V)))
print('带 group 的替换          :', repr(re.sub(r'(.*)', r'\1', V)))
print('带 $ 的替换               :', repr(re.sub(r'(.*)', '$1', V)))
