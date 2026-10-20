# -*- coding: utf-8 -*-
"""Minimal legado rule engine."""
import re

VOID_TAGS = {'area','base','br','col','embed','hr','img','input','link','meta',
             'param','source','track','wbr','basefont','frame','isindex'}
TAG_RE = re.compile(r'<(/?)([a-zA-Z][\w:-]*)((?:"[^"]*"|\'[^\']*\'|[^>"\'])*?)(/?)>', re.S)
ATTR_RE = re.compile(r'([\w:.-]+)(?:\s*=\s*(?:"([^"]*)"|\'([^\']*)\'|([^\s"\'>]+)))?')
SIMPLE_RE = re.compile(r'^([a-zA-Z][\w-]*)?((?:[.#][\w-]+)*)$')
PSEUDO_RE = re.compile(
    r'^(.*?):(nth-child|nth-of-type|first-child|last-child|eq|not)'
    r'(?:\(\s*(-?\d+)\s*\))?$')
# :not(...) 的参数可以不是数字，单独用一个正则拆出来
NOT_RE = re.compile(r'^(.*?):not\(([^()]*)\)$')
# 属性选择器：[attr] [attr=v] [attr*=v] [attr^=v] [attr$=v] [attr!=v]
ATTR_SEL_RE = re.compile(
    r'\[\s*([\w-]+)\s*(?:(\*=|\^=|\$=|!=|=)\s*(?:"([^"]*)"|\'([^\']*)\'|([^\]]*?))\s*)?\]')
IMPLICIT_PARENT = {
    'li': {'li'}, 'p': {'p'}, 'tr': {'tr','td','th'}, 'td': {'td','th'},
    'th': {'td','th'}, 'option': {'option'}, 'dd': {'dd','dt'}, 'dt': {'dt','dd'},
    'tbody': {'tbody','thead','tfoot','tr','td','th'},
}
COMMON_TAGS = set(('a div span p li ul ol tr td th h1 h2 h3 h4 h5 h6 img table tbody '
                   'thead body dd dt dl section article label form input button em strong '
                   'i b br hr pre code').split())


class El(object):
    __slots__ = ('tag', 'attrs', 'children', 'parent')

    def __init__(self, tag, attrs=None, children=None):
        self.tag = tag
        self.attrs = attrs or {}
        self.children = children if children is not None else []
        self.parent = None

    def classes(self):
        return set(c for c in (self.attrs.get('class') or '').split() if c)

    def text(self):
        out = []

        def walk(n):
            for c in n.children:
                if isinstance(c, El):
                    if c.tag in ('script', 'style'):
                        continue
                    walk(c)
                else:
                    out.append(c)
        walk(self)
        return ''.join(out)

    def iter_desc(self):
        for c in self.children:
            if isinstance(c, El):
                yield c
                for d in c.iter_desc():
                    yield d

    def __repr__(self):
        return '<%s %r>' % (self.tag, self.attrs.get('class') or self.attrs.get('id') or '')


def parse_attrs(txt):
    attrs = {}
    for m in ATTR_RE.finditer(txt or ''):
        k = m.group(1).lower()
        v = m.group(2)
        if v is None:
            v = m.group(3)
        if v is None:
            v = m.group(4)
        attrs[k] = '' if v is None else v
    return attrs


def parse_html(html):
    root = El('#root')
    stack = [root]
    i = 0
    n = len(html)
    lower = html.lower()
    while i < n:
        lt = html.find('<', i)
        if lt < 0:
            stack[-1].children.append(html[i:])
            break
        if lt > i:
            stack[-1].children.append(html[i:lt])
        if html.startswith('<!--', lt):
            end = html.find('-->', lt)
            i = end + 3 if end >= 0 else n
            continue
        if html.startswith('<!', lt) or html.startswith('<?', lt):
            end = html.find('>', lt)
            i = end + 1 if end >= 0 else n
            continue
        m = TAG_RE.match(html, lt)
        if not m:
            stack[-1].children.append('<')
            i = lt + 1
            continue
        closing, tag, attrtext, selfclose = m.group(1), m.group(2).lower(), m.group(3) or '', m.group(4)
        i = m.end()
        if closing:
            for idx in range(len(stack) - 1, 0, -1):
                if stack[idx].tag == tag:
                    del stack[idx:]
                    break
            continue
        el = El(tag, parse_attrs(attrtext))
        el.parent = stack[-1]
        stack[-1].children.append(el)
        if tag in ('script', 'style'):
            end = lower.find('</' + tag, i)
            if end < 0:
                end = n
            el.children.append(html[i:end])
            i = end
            continue
        if tag in VOID_TAGS or selfclose == '/':
            continue
        parents = IMPLICIT_PARENT.get(tag)
        if parents:
            while len(stack) > 1 and stack[-1].tag in parents:
                stack.pop()
        stack.append(el)
    return root


def split_hash(rule):
    """拆 ``规则##正则##替换`` 三段。

    Legado（Kotlin）里是 ``rule.split("##")`` 后取 ``[0] [1] [2]``，
    多出来的 ``##`` 只是结束符（例如 ``##href="..."##xxx/###``）。
    早期这里用 ``'##'.join(parts[2:])``，会把结尾的 ``##`` 带进替换文本，
    结果就是书籍链接后面多出一截 ``##``。
    """
    parts = rule.split('##')
    if len(parts) == 1:
        return parts[0], None, None
    if len(parts) == 2:
        return parts[0], parts[1], ''
    return parts[0], parts[1], parts[2]


def _normalize_replacement(repl):
    """把 Legado 风格的 ``$1`` 捕获组引用转成 Python 的 ``\\1``。

    阅读（Java/Kotlin）用 ``$1`` / ``${1}`` 引用捕获组，而 Python 的
    ``re.sub`` 只认 ``\\1``，不转换的话 ``$1`` 会被当成字面量，替换结果
    直接变成字符串 "$1"。书源里这种写法很常见（225/905 条用到）。
    """
    if not repl:
        return repl
    out = []
    i, n = 0, len(repl)
    while i < n:
        c = repl[i]
        if c == '$' and i + 1 < n:
            nxt = repl[i + 1]
            if nxt == '$':
                out.append('$')
                i += 2
                continue
            m = re.match(r'\$\{(\d+)\}', repl[i:])
            if m:
                out.append('\\%s' % m.group(1))
                i += m.end()
                continue
            m = re.match(r'\$(\d+)', repl[i:])
            if m:
                out.append('\\%s' % m.group(1))
                i += m.end()
                continue
        out.append(c)
        i += 1
    return ''.join(out)


def apply_hash(value, rx, repl, first=False):
    """按 Legado 的 ``##正则##替换`` 语义替换。

    Legado（AnalyzeRule.replaceRegex）分两种：

    * ``规则##正则##替换``    —— 整体 replace，匹配不到就原样返回
    * ``规则##正则##替换##``  —— 只取第一个匹配（group(0)）做替换，
      **匹配不到返回空串**（不是原文），这是它和整体 replace 的关键差别。
    """
    if rx is None:
        return value
    try:
        if first:
            m = re.search(rx, value)
            if not m:
                return ''
            return re.sub(rx, _normalize_replacement(repl), m.group(0), count=1)
        return re.sub(rx, _normalize_replacement(repl), value)
    except re.error:
        return value


_JS_CONCAT_RE = re.compile(
    r"""^\s*(?:'[^']*'|"[^"]*"|result)\s*(?:\+\s*(?:'[^']*'|"[^"]*"|result)\s*)*$""")
_JS_PART_RE = re.compile(r"""'[^']*'|"[^"]*"|result""")


def _split_js_suffix(rule):
    """拆出规则尾部的 ``@js:`` 段。

    Legado 的 ``splitSourceRule`` 会用 JS_PATTERN 把规则按 ``@js:`` 切开，
    后面那段交给 Rhino 执行，前面的结果作为 ``result`` 传进去。
    """
    if '@js:' in rule:
        head, expr = rule.rsplit('@js:', 1)
        return head, expr
    return rule, None


def _eval_js_concat(expr, values):
    """极简 JS 求值：只认「字符串字面量 / result」的 ``+`` 拼接。

    Legado 里 ``@js:`` 可以写任意 JS；本引擎不跑完整 JS，只支持起点书源
    这种 ``'https://m.qidian.com/book/'+result+'/'`` 的拼接形式，
    其它一律返回空串，保持「未解析」状态而不误判成可用。
    """
    expr = (expr or '').strip()
    if not expr or not _JS_CONCAT_RE.match(expr):
        return ''
    val = ''
    for v in values or []:
        if isinstance(v, str) and v.strip():
            val = v
            break
    out = []
    for part in _JS_PART_RE.findall(expr):
        out.append(val if part == 'result' else part[1:-1])
    return ''.join(out)


def _attr_match(el, attr, op, want):
    """按属性选择器判断元素是否匹配。"""
    val = el.attrs.get(attr)
    if val is None:
        return False
    if op is None:
        return True
    if op == '=':
        return val == want
    if op == '*=':
        return want in val
    if op == '^=':
        return val.startswith(want)
    if op == '$=':
        return val.endswith(want)
    if op == '!=':
        return val != want
    return False


def _match_attrs(el, sel):
    """匹配选择器里的属性条件（可出现多个）。"""
    for m in ATTR_SEL_RE.finditer(sel):
        want = m.group(3)
        if want is None:
            want = m.group(4)
        if want is None:
            want = m.group(5)
        if want is None:
            want = ''
        want = want.strip()
        if not _attr_match(el, m.group(1), m.group(2), want):
            return False
    return True


def _match_pseudo(el, kind, arg):
    """匹配 CSS 伪类。

    兄弟计数严格按 CSS 语义：

    - ``:nth-of-type(n)``   —— 父节点下**同标签**的第 n 个
    - ``:nth-child(n)``     —— 父节点下第 n 个**子元素**（不分标签）
    - ``:first-child`` / ``:last-child`` —— 父节点下的第一个 / 最后一个子元素

    早期版本一律按同标签兄弟计数，等于把 ``:nth-child`` 写成了
    ``:nth-of-type``，像 ``p:nth-child(3)`` 这种会选错元素。
    """
    parent = el.parent
    if parent is None:
        return False
    if kind == 'nth-of-type':
        sibs = [c for c in parent.children if isinstance(c, El) and c.tag == el.tag]
    else:
        sibs = [c for c in parent.children if isinstance(c, El)]
    try:
        idx = sibs.index(el)
    except ValueError:
        return False
    if kind == 'first-child':
        return idx == 0
    if kind == 'last-child':
        return idx == len(sibs) - 1
    if kind in ('nth-child', 'nth-of-type'):
        n = int(arg) if arg else 1
        return idx + 1 == n
    if kind == 'eq':
        # :eq(n) 是"整个匹配集合里的第 n 个"，属于集合层语义，
        # 由 css_find / chain_find 在收集完候选后再取。
        return True
    if kind == 'not':
        return not _match_not_arg(el, arg)
    return False


def _match_not_arg(el, arg):
    """元素是否命中 ``:not(...)`` 里的选择器（命中则被排除）。"""
    arg = str(arg or '').strip()
    if not arg:
        return False
    if arg.startswith('['):
        # 纯属性条件，如 :not([href="#bottom"])
        return _match_attrs(el, arg)
    return simple_match(el, arg)


def _split_pseudo(sel):
    """拆出选择器尾部的伪类：``'p:nth-child(2)'`` -> ``('p', 'nth-child', '2')``。"""
    sel = str(sel or '').strip()
    m = PSEUDO_RE.match(sel)
    if not m:
        return sel, None, None
    return m.group(1).strip(), m.group(2), m.group(3)


def simple_match(el, sel):
    sel = sel.strip()
    not_arg = None
    m = NOT_RE.match(sel)
    if m:
        not_arg = m.group(2).strip()
        sel = m.group(1).strip()
    pseudo = None
    m = PSEUDO_RE.match(sel)
    if m:
        sel = m.group(1).strip()
        pseudo = (m.group(2), m.group(3))
    # 属性条件单独处理，剩下的部分再按 tag/class/id 匹配
    if '[' in sel:
        if not _match_attrs(el, sel):
            return False
        sel = ATTR_SEL_RE.sub('', sel).strip()
    m = SIMPLE_RE.match(sel)
    if not m:
        return False
    tag = m.group(1)
    if tag and el.tag != tag.lower():
        return False
    for tok in re.findall(r'[.#][\w-]+', m.group(2) or ''):
        if tok[0] == '.':
            if tok[1:] not in el.classes():
                return False
        else:
            if (el.attrs.get('id') or '') != tok[1:]:
                return False
    if pseudo and not _match_pseudo(el, pseudo[0], pseudo[1]):
        return False
    if not_arg is not None and _match_not_arg(el, not_arg):
        return False
    return True


def split_css(selector):
    """按空白和子代选择器 ``>`` 拆 CSS 选择器。

    返回 ``[(关系, 简单选择器), ...]``，关系为 ``' '``（后代）或 ``'>'``（直接子代）。
    ``[attr="带 空格"]`` 内部不会被拆开。
    """
    parts = []
    buf = []
    depth = 0
    quote = None
    comb = ' '

    def flush():
        if buf:
            parts.append((comb, ''.join(buf)))
            del buf[:]

    for ch in selector:
        if quote:
            buf.append(ch)
            if ch == quote:
                quote = None
            continue
        if ch in ('"', "'"):
            quote = ch
            buf.append(ch)
            continue
        if ch == '[':
            depth += 1
        elif ch == ']':
            depth = max(0, depth - 1)
        if depth == 0 and ch in '>+~':
            flush()
            comb = ch
            continue
        if ch.isspace() and depth == 0:
            if buf:
                flush()
                comb = ' '
            continue
        buf.append(ch)
    flush()
    return parts


def _element_siblings(el):
    parent = el.parent
    if parent is None:
        return []
    return [c for c in parent.children if isinstance(c, El)]


def _next_siblings(el):
    """紧邻的下一个兄弟元素（CSS ``+``）。"""
    sibs = _element_siblings(el)
    try:
        i = sibs.index(el)
    except ValueError:
        return []
    return sibs[i + 1:i + 2]


def _following_siblings(el):
    """后面所有的兄弟元素（CSS ``~``）。"""
    sibs = _element_siblings(el)
    try:
        i = sibs.index(el)
    except ValueError:
        return []
    return sibs[i + 1:]


def css_find(root, selector):
    parts = split_css(selector.strip())
    if not parts:
        return []
    cur = [root]
    for pi, (comb, p) in enumerate(parts):
        _, kind, arg = _split_pseudo(p)
        nxt = []
        for scope in cur:
            if pi == 0:
                cands = [scope]
                cands.extend(scope.iter_desc())
            elif comb == '>':
                # 直接子代：只看父元素的下一层
                cands = [c for c in scope.children if isinstance(c, El)]
            elif comb == '+':
                # 相邻兄弟：紧跟在后面的那个
                cands = _next_siblings(scope)
            elif comb == '~':
                # 通用兄弟：后面所有的
                cands = _following_siblings(scope)
            else:
                cands = list(scope.iter_desc())
            for el in cands:
                if simple_match(el, p):
                    nxt.append(el)
        if kind == 'eq':
            # :eq(n) 取整个匹配集合里的第 n 个
            n = int(arg) if arg else 0
            nxt = [nxt[n]] if 0 <= n < len(nxt) else []
        cur = nxt
        if not cur:
            break
    return cur


class Step(object):
    __slots__ = ('kind', 'name', 'index', 'neg', 'from_end', 'exclude', 'pseudo')

    def __init__(self, kind, name=None, index=None, neg=False, from_end=False,
                 exclude=None, pseudo=None):
        self.kind = kind
        self.name = name
        self.index = index
        self.neg = neg
        self.from_end = from_end
        self.exclude = exclude or []
        self.pseudo = pseudo


def _split_exclude(name):
    """拆出 Legado 的多下标排除写法：``dd!0:1:2`` -> ('dd', [0, 1, 2])。"""
    if '!' not in name:
        return name, []
    head, tail = name.split('!', 1)
    idxs = []
    for t in tail.split(':'):
        t = t.strip()
        if t.isdigit():
            idxs.append(int(t))
    return head, idxs


def _split_index(rest):
    neg = False
    idx = None
    from_end = False
    if rest.startswith('!'):
        neg = True
        rest = rest[1:]
    if '.' in rest:
        head, tail = rest.rsplit('.', 1)
        if head:
            rest = head
        if tail.isdigit():
            idx = int(tail)
        elif tail.startswith('-') and tail[1:].isdigit():
            # a.-2 表示"倒数第 2 个"
            from_end = True
            idx = int(tail[1:])
    return rest, idx, neg, from_end


def parse_step(tok):
    tok = tok.strip()
    if not tok:
        return None
    low = tok.lower()
    if low in ('text', 'textnodes'):
        return Step('text')
    if low == 'html':
        return Step('html')
    if low == 'children' or low.startswith('children.'):
        # Legado 的 ElementsSingle 支持 "children"（直接子元素），可带下标
        name, idx, neg, fe = _split_index(low)
        return Step('children', None, idx, neg, fe)
    if low.startswith('class.'):
        name, excl = _split_exclude(tok[6:])
        name, idx, neg, fe = _split_index(name)
        return Step('class', name, idx, neg, fe, excl)
    if low.startswith('id.'):
        name, excl = _split_exclude(tok[3:])
        name, idx, neg, fe = _split_index(name)
        return Step('id', name, idx, neg, fe, excl)
    if low.startswith('tag.'):
        name, excl = _split_exclude(tok[4:])
        name, idx, neg, fe = _split_index(name)
        return Step('tag', name, idx, neg, fe, excl)
    if tok.startswith('.'):
        name, excl = _split_exclude(tok[1:])
        name, idx, neg, fe = _split_index(name)
        return Step('class', name, idx, neg, fe, excl)
    if tok.startswith('#'):
        name, excl = _split_exclude(tok[1:])
        name, idx, neg, fe = _split_index(name)
        return Step('id', name, idx, neg, fe, excl)
    if tok.startswith('!'):
        try:
            return Step('index', None, int(tok[1:]), True)
        except ValueError:
            return None
    if tok.isdigit():
        return Step('index', None, int(tok), False)
    if re.match(r'^[a-zA-Z][\w-]*$', tok):
        return Step('tag', tok.lower(), None, False)
    # Legado 允许 "a.0"（第 n 个 a）、"span.-2"（倒数第 2 个）这种带下标的写法
    if re.match(r'^[a-zA-Z][\w-]*\.\-?\d+$', tok):
        name, idx, neg, fe = _split_index(tok)
        return Step('tag', name.lower(), idx, neg, fe)
    # 带伪类的写法：li:nth-child(2) / li:last-child
    pm = PSEUDO_RE.match(tok)
    if pm and pm.group(1):
        head = pm.group(1).strip()
        pseudo = (pm.group(2), pm.group(3))
        if re.match(r'^[a-zA-Z][\w-]*$', head):
            return Step('tag', head.lower(), None, False, False, None, pseudo)
        # 头部带 class/id（div.booklist:nth-child(2)），交给 CSS 选择器解析
        return Step('sel', tok)
    # :not(...) 写法：li:not(:first-child) / a:not([href="#bottom"])
    nm = NOT_RE.match(tok)
    if nm and nm.group(1):
        head = nm.group(1).strip()
        if re.match(r'^[a-zA-Z][\w-]*$', head):
            return Step('tag', head.lower(), None, False, False, None,
                        ('not', nm.group(2)))
        return Step('sel', tok)
    return None


def _pick_index(cands, st):
    """按 Step 的下标语义取出目标元素。"""
    if st.exclude:
        # Legado 的 "!0:1:2" 表示排除这些下标（如"排除前 N 个"）
        drop = set(st.exclude)
        return [c for i, c in enumerate(cands) if i not in drop]
    if st.index is None:
        return cands
    if st.neg:
        if len(cands) > st.index:
            return cands[:st.index] + cands[st.index + 1:]
        return cands
    if st.from_end:
        # a.-1 = 倒数第 1 个（即最后一个）
        pos = len(cands) - st.index
        if 0 <= pos < len(cands):
            return cands[pos:pos + 1]
        return []
    return cands[st.index:st.index + 1]


def chain_find(scopes, steps):
    cur = list(scopes)
    for st in steps:
        if st.kind == 'index':
            nxt = []
            for scope in cur:
                cands = list(scope.iter_desc())
                nxt.extend(_pick_index(cands, st))
            cur = nxt
            continue
        if st.kind == 'children':
            # Legado 的 "children" 取直接子元素
            nxt = []
            for scope in cur:
                cands = [c for c in scope.children if isinstance(c, El)]
                nxt.extend(_pick_index(cands, st))
            cur = nxt
            if not cur:
                break
            continue
        if st.kind == 'sel':
            # 整段交给 CSS 选择器（头部带 class/id 的伪类写法）
            nxt = []
            for scope in cur:
                cands = [el for el in css_find(scope, st.name) if el is not scope]
                nxt.extend(_pick_index(cands, st))
            cur = nxt
            if not cur:
                break
            continue
        nxt = []
        matched = []
        for scope in cur:
            cands = []
            for el in scope.iter_desc():
                if st.kind == 'class' and st.name in el.classes():
                    cands.append(el)
                elif st.kind == 'id' and (el.attrs.get('id') or '') == st.name:
                    cands.append(el)
                elif st.kind == 'tag' and el.tag == st.name:
                    cands.append(el)
            if st.pseudo and st.pseudo[0] != 'eq':
                kind, arg = st.pseudo
                cands = [el for el in cands if _match_pseudo(el, kind, arg)]
            matched.extend(cands)
        if st.pseudo and st.pseudo[0] == 'eq':
            # :eq(n) 取整个匹配集合里的第 n 个
            n = int(st.pseudo[1]) if st.pseudo[1] else 0
            matched = [matched[n]] if 0 <= n < len(matched) else []
        nxt.extend(_pick_index(matched, st))
        cur = nxt
        if not cur:
            break
    return cur


def json_path_multi(obj, path):
    """返回路径匹配到的所有值，支持 list/dict 上的 ``*`` 通配。

    ``$.data[*].book`` 这类路径在逐段求值时会被卡住（列表里再取字段），
    这里按"逐层展开"的语义处理：``*`` 作用在 list 上就展开每个元素。
    """
    p = path.strip()
    if '&&' in p:
        p = p.split('&&')[-1].strip()
    if p.startswith('{{') and p.endswith('}}'):
        p = p[2:-2].strip()
    if p.startswith('$'):
        p = p[1:]
        if p.startswith('.'):
            p = p[1:]
    p = p.replace('[', '.').replace(']', '')
    segs = [s for s in p.split('.') if s]
    cur = [obj]
    for seg in segs:
        nxt = []
        for c in cur:
            if seg == '*':
                if isinstance(c, list):
                    nxt.extend(c)
                elif isinstance(c, dict):
                    nxt.extend(c.values())
            elif isinstance(c, dict):
                if seg in c:
                    nxt.append(c[seg])
            elif isinstance(c, list):
                if seg.isdigit():
                    i = int(seg)
                    if i < len(c):
                        nxt.append(c[i])
                else:
                    for e in c:
                        if isinstance(e, dict) and seg in e:
                            nxt.append(e[seg])
        cur = nxt
        if not cur:
            break
    return cur


def json_collect(values):
    """把 json_path_multi 的结果摊平成条目列表。"""
    out = []
    for v in values:
        if isinstance(v, list):
            out.extend(v)
        elif isinstance(v, dict):
            sub = json_items(v)
            if sub:
                out.extend(sub)
            else:
                out.append(v)
        else:
            out.append(v)
    return out


def json_path(obj, path):
    p = path.strip()
    if '&&' in p:
        p = p.split('&&')[-1].strip()
    if p.startswith('{{') and p.endswith('}}'):
        p = p[2:-2].strip()
    if p.startswith('$'):
        p = p[1:]
        if p.startswith('.'):
            p = p[1:]
    p = p.replace('[', '.').replace(']', '')
    cur = obj
    for seg in [s for s in p.split('.') if s]:
        if seg == '*':
            continue
        if isinstance(cur, dict):
            if seg in cur:
                cur = cur[seg]
            else:
                return None
        elif isinstance(cur, list):
            if seg.isdigit() and int(seg) < len(cur):
                cur = cur[int(seg)]
            else:
                return None
        else:
            return None
    return cur


def json_items(value):
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        for k in ('list', 'data', 'book', 'books', 'items', 'result', 'rows'):
            v = value.get(k)
            if isinstance(v, list):
                return v
            if isinstance(v, dict):
                for k2 in ('list', 'data', 'books', 'items'):
                    v2 = v.get(k2)
                    if isinstance(v2, list):
                        return v2
    return []


def eval_rule(rule, doc=None, js=None, item=None):
    """Evaluate a legado rule against an HTML document (doc) or JSON payload (js)."""
    if rule is None:
        return []
    base, rx, repl = split_hash(str(rule))
    base = base.strip()
    hash_first = len(str(rule).split('##')) > 3
    base, js_expr = _split_js_suffix(base)
    base = base.strip()
    if not base and not js_expr:
        return []
    out = []
    if js is not None:
        path = base
        if path.startswith('@json:'):
            path = path[6:]
        out = json_collect(json_path_multi(js, path))
    elif base.startswith('@css:'):
        sel = base[5:].strip()
        attr = None
        if '@' in sel:
            head, tail = sel.rsplit('@', 1)
            if re.match(r'^[a-zA-Z_][\w-]*$', tail.strip()):
                attr = tail.strip().lower()
                sel = head
        root = item if item is not None else doc
        els = css_find(root, sel) if root is not None else []
        if attr is None:
            out = list(els)
        elif attr in ('text', 'textnodes'):
            out = [e.text() for e in els]
        else:
            out = [e.attrs.get(attr, '') for e in els]
    else:
        raw_steps = base.split('@')
        first = raw_steps[0].strip()
        if (' ' in first or '[' in first) and not first.startswith('<'):
            sel = first
            attr = None
            if len(raw_steps) > 1 and re.match(r'^[a-zA-Z_][\w-]*$', raw_steps[-1].strip()):
                attr = raw_steps[-1].strip().lower()
            root = item if item is not None else doc
            els = css_find(root, sel) if root is not None else []
            if attr is None:
                out = list(els)
            elif attr in ('text', 'textnodes'):
                out = [e.text() for e in els]
            else:
                out = [e.attrs.get(attr, '') for e in els]
            if js_expr:
                return [_eval_js_concat(js_expr, out)]
            return [apply_hash(v, rx, repl, hash_first) if isinstance(v, str) else v
                    for v in out]
        steps = [parse_step(s) for s in raw_steps]
        if any(s is None for s in steps):
            return []
        terminal = None
        last = raw_steps[-1].strip()
        if steps and steps[-1].kind == 'text':
            terminal = steps.pop()
        elif steps and steps[-1].kind == 'html':
            terminal = steps.pop()
        elif last.lower() not in COMMON_TAGS and re.match(r'^[a-zA-Z_][\w-]*$', last):
            terminal = Step('attr', last.lower())
            steps.pop()
        root = item if item is not None else doc
        if not isinstance(root, El):
            return []
        els = chain_find([root], steps) if steps else [root]
        if terminal is None:
            out = list(els)
        elif terminal.kind == 'text':
            out = [e.text() for e in els]
        elif terminal.kind == 'html':
            out = [''.join(c if isinstance(c, str) else '' for c in e.children) for e in els]
        else:
            out = [e.attrs.get(terminal.name, '') for e in els]
    if js_expr:
        return [_eval_js_concat(js_expr, out)]
    res = []
    for v in out:
        if isinstance(v, str):
            res.append(apply_hash(v, rx, repl, hash_first))
        elif isinstance(v, (int, float, bool)):
            res.append(apply_hash(str(v), rx, repl, hash_first))
        else:
            res.append(v)
    return res


def rule_items(rule, doc=None, js=None):
    """Return the list of book entries matched by a bookList rule."""
    base, rx, repl = split_hash(str(rule or ''))
    base = base.strip()
    if not base:
        return []
    if js is not None:
        path = base
        if path.startswith('@json:'):
            path = path[6:]
        return json_collect(json_path_multi(js, path))
    if base.startswith('@css:'):
        sel = base[5:].strip()
        if '@' in sel:
            head, tail = sel.rsplit('@', 1)
            if re.match(r'^[a-zA-Z_][\w-]*$', tail.strip()):
                sel = head
        return css_find(doc, sel) if doc is not None else []
    raw_steps = base.split('@')
    first = raw_steps[0].strip()
    if (' ' in first or '[' in first) and not first.startswith('<'):
        return css_find(doc, first) if doc is not None else []
    steps = [parse_step(s) for s in raw_steps]
    if any(s is None for s in steps):
        return []
    if steps and steps[-1].kind in ('text', 'html'):
        # Legado 的 getElements 对这两段没有对应语义，这里退化成"取父元素本身"
        steps = steps[:-1]
    if not steps:
        return []
    # 末段按 Legado getElements 的语义当"选择器"处理（tag/class/id/children），
    # 而不是像 eval_rule（getStringList）那样当属性名。
    return chain_find([doc], steps) if doc is not None else []
