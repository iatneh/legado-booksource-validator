# -*- coding: utf-8 -*-
"""标签体系重构。

原始 ``bookSourceGroup`` 混了三类信息：内容分类（漫画/有声/正版）、
站点状态（人机验证、暂不可用）、访问通道（梯子/代理）。而且分类标签本身
还有重复写法（"正版" vs "正版书源 🏷"，"网络小说" 孤立存在）。

这里把它拆成三层规范标签，按固定顺序拼回 ``bookSourceGroup``：

1. **内容分类** —— 源本身是什么（来自原始标签，别名归一）
2. **访问范围** —— 实测可达性（🌐全球可用 / 🇨🇳仅国内 / 🌍需外网 / ❓未知）
3. **质量状态** —— 实测质量（✅实测可用 / ⚠️搜索失效 / 🔧接口异常 / 🚫人机验证）

原始的"人机验证-搜索""暂不可用""搜索暂不可用"是**站点状态**，一律丢弃，
改由实测结果重新推导——校验通过的书源不该再挂着"暂不可用"的标签。
"""
import re

# ---------------------------------------------------------------- 内容分类

# 规范分类标签（顺序即展示优先级）
CATEGORIES = [
    '快速书源 ⚡',
    '通常书源 📂',
    '文本书源 📚',
    '漫画书源 🎨',
    '图片书源 📷',
    '有声书源 🔊',
    '影视频源 🎬',
    '轻文书源 📘',
    '出版书源 🏛',
    '正版书源 🏷',
    '同人书源 🎭',
    '特殊书源 🔞',
    '下载书源 📥',
    '文件书源 📦',
    '聚合书源 🗂',
    '代理书源 🪜',
    'API 书源 🔌',
]

# 原始标签 -> 规范分类标签
CATEGORY_ALIAS = {
    '快速书源 ⚡': '快速书源 ⚡',
    '通常书源 📂': '通常书源 📂',
    '特殊书源 🔞': '特殊书源 🔞',
    '漫画书源 🎨': '漫画书源 🎨',
    '正版书源 🏷': '正版书源 🏷',
    '有声书源 🔊': '有声书源 🔊',
    '下载书源 📥': '下载书源 📥',
    '影视频源 🎬': '影视频源 🎬',
    '轻文书源 📘': '轻文书源 📘',
    '出版书源 🏛': '出版书源 🏛',
    '同人书源 🎭': '同人书源 🎭',
    '图片书源 📷': '图片书源 📷',
    '聚合书源 📚': '聚合书源 🗂',
    '代理书源 🌍': '代理书源 🪜',
    '网络小说': '文本书源 📚',
    'API': 'API 书源 🔌',
    '正版': '正版书源 🏷',
    '文本书源 📚': '文本书源 📚',
    '文件书源 📦': '文件书源 📦',
}

# 原始标签里表示"站点状态"的，校验后一律丢弃
STATUS_TAGS = {
    '人机验证-搜索', '人机验证-全站', '暂不可用', '搜索暂不可用',
    '不可用', '失效', '已失效',
}

# 原始标签里表示"需要代理通道"的，保留为独立标记
PROXY_TAGS = {'梯子', '代理书源 🌍', '代理书源 🪜', '需代理'}
PROXY_FLAG = '🪜需代理'

# 无分类标签时按 bookSourceType 兜底
TYPE_CATEGORY = {
    0: '文本书源 📚',
    1: '有声书源 🔊',
    2: '漫画书源 🎨',
    3: '文件书源 📦',
    4: '影视频源 🎬',
}

# ---------------------------------------------------------------- 访问范围

ACCESS_TAGS = {
    'both': '🌐全球可用',
    'cn_only': '🇨🇳仅国内',
    'overseas_only': '🌍需外网',
    'unverified': '❓访问范围未知',
    'none': '❓访问范围未知',
}

# ---------------------------------------------------------------- 质量状态

QUALITY_TAGS = {
    'verified': '✅实测可用',
    'weak': '⚠️搜索失效',
    'alive': '⚠️搜索失效',
    'api_quirk': '🔧接口异常',
    'antibot': '🚫人机验证',
    'unverified': '❓未验证',
}

# 同义分类：两者同时出现时保留信息量更大的那个
_CATEGORY_SUPERSEDE = {
    '通常书源 📂': '快速书源 ⚡',
    '文本书源 📚': '通常书源 📂',
}


def split_group(group):
    """把原始 group 字符串拆成标签列表。"""
    if not group:
        return []
    if isinstance(group, (list, tuple)):
        raw = []
        for g in group:
            raw.extend(split_group(g))
        return raw
    parts = re.split(r'[,，;；]', str(group))
    out = []
    for p in parts:
        p = p.strip()
        if p and p not in out:
            out.append(p)
    return out


def original_categories(group):
    """从原始 group 里提取规范后的内容分类标签。"""
    cats = []
    for tag in split_group(group):
        if tag in STATUS_TAGS:
            continue
        canon = CATEGORY_ALIAS.get(tag)
        if canon is None:
            # 容错：按前缀匹配，尽量归到已知分类
            for alias, c in CATEGORY_ALIAS.items():
                if tag and (tag.startswith(alias.split(' ')[0]) or alias.startswith(tag)):
                    canon = c
                    break
        if canon and canon not in cats:
            cats.append(canon)
    return cats


def has_proxy_flag(group):
    """原始 group 是否带"需要代理通道"标记。"""
    for tag in split_group(group):
        if tag in PROXY_TAGS:
            return True
    return False


def resolve_categories(source):
    """确定一条书源的内容分类标签（原始标签优先，类型兜底）。"""
    cats = original_categories(source.get('bookSourceGroup'))
    if not cats:
        cats = [TYPE_CATEGORY.get(source.get('bookSourceType'), '文本书源 📚')]
    # 去掉被更强分类覆盖的弱分类（例如同时有"快速"和"通常"时只留"快速"）
    out = []
    for c in cats:
        sup = _CATEGORY_SUPERSEDE.get(c)
        if sup and sup in cats:
            continue
        out.append(c)
    # 按规范顺序排序，未知的排在后面
    out.sort(key=lambda c: CATEGORIES.index(c) if c in CATEGORIES else len(CATEGORIES))
    return out


def build_groups(source, access, quality):
    """按「分类 -> 访问范围 -> 质量状态」拼出规范化的 group 字符串。"""
    cats = resolve_categories(source)
    tags = list(cats)
    if has_proxy_flag(source.get('bookSourceGroup')):
        tags.append(PROXY_FLAG)
    tags.append(ACCESS_TAGS.get(access, ACCESS_TAGS['unverified']))
    tags.append(QUALITY_TAGS.get(quality, QUALITY_TAGS['unverified']))
    # 去重保序
    seen, out = set(), []
    for t in tags:
        if t and t not in seen:
            seen.add(t)
            out.append(t)
    return ','.join(out)


def build_groups_legacy(source, access, quality):
    """兼容旧流程的返回形态：返回 (group 字符串, 标签列表)。"""
    group = build_groups(source, access, quality)
    return group, group.split(',')
