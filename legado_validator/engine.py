# -*- coding: utf-8 -*-
"""Minimal legado rule engine."""
import re

VOID_TAGS = {'area','base','br','col','embed','hr','img','input','link','meta',
             'param','source','track','wbr','basefont','frame','isindex'}
TAG_RE = re.compile(r'<(/?)([a-zA-Z][\w:-]*)((?:"[^"]*"|\'[^\']*\'|[^>"\'])*?)(/?)>', re.S)
ATTR_RE = re.compile(r'([\w:.-]+)(?:\s*=\s*(?:"([^"]*)"|\'([^\']*)\'|([^\s"\'>]+)))?')
SIMPLE_RE = re.compile(r'^([a-zA-Z][\w-]*)?((?:[.#][\w-]+)*)$')
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
    parts = rule.split('##')
    if len(parts) == 1:
        return parts[0], None, None
    if len(parts) == 2:
        return parts[0], parts[1], ''
    return parts[0], parts[1], '##'.join(parts[2:])


def apply_hash(value, rx, repl):
    if rx is None:
        return value
    try:
        return re.sub(rx, repl if repl is not None else '', value)
    except re.error:
        return value


def simple_match(el, sel):
    m = SIMPLE_RE.match(sel.strip())
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
    return True


def css_find(root, selector):
    parts = [p for p in re.split(r'\s+', selector.strip()) if p]
    if not parts:
        return []
    cur = [root]
    for pi, p in enumerate(parts):
        nxt = []
        for scope in cur:
            cands = [scope] if pi == 0 else []
            cands.extend(scope.iter_desc())
            for el in cands:
                if simple_match(el, p):
                    nxt.append(el)
        cur = nxt
        if not cur:
            break
    return cur


class Step(object):
    __slots__ = ('kind', 'name', 'index', 'neg')

    def __init__(self, kind, name=None, index=None, neg=False):
        self.kind = kind
        self.name = name
        self.index = index
        self.neg = neg


def _split_index(rest):
    neg = False
    idx = None
    if rest.startswith('!'):
        neg = True
        rest = rest[1:]
    if '.' in rest:
        head, tail = rest.rsplit('.', 1)
        if head:
            rest = head
        if tail.isdigit():
            idx = int(tail)
    return rest, idx, neg


def parse_step(tok):
    tok = tok.strip()
    if not tok:
        return None
    low = tok.lower()
    if low in ('text', 'textnodes'):
        return Step('text')
    if low == 'html':
        return Step('html')
    if low.startswith('class.'):
        name, idx, neg = _split_index(tok[6:])
        return Step('class', name, idx, neg)
    if low.startswith('id.'):
        name, idx, neg = _split_index(tok[3:])
        return Step('id', name, idx, neg)
    if low.startswith('tag.'):
        name, idx, neg = _split_index(tok[4:])
        return Step('tag', name, idx, neg)
    if tok.startswith('.'):
        name, idx, neg = _split_index(tok[1:])
        return Step('class', name, idx, neg)
    if tok.startswith('#'):
        name, idx, neg = _split_index(tok[1:])
        return Step('id', name, idx, neg)
    if tok.startswith('!'):
        try:
            return Step('index', None, int(tok[1:]), True)
        except ValueError:
            return None
    if tok.isdigit():
        return Step('index', None, int(tok), False)
    if re.match(r'^[a-zA-Z][\w-]*$', tok):
        return Step('tag', tok.lower(), None, False)
    return None


def chain_find(scopes, steps):
    cur = list(scopes)
    for st in steps:
        if st.kind == 'index':
            nxt = []
            for scope in cur:
                cands = list(scope.iter_desc())
                if st.neg:
                    if len(cands) > st.index:
                        cands = cands[:st.index] + cands[st.index + 1:]
                else:
                    cands = cands[st.index:st.index + 1]
                nxt.extend(cands)
            cur = nxt
            continue
        nxt = []
        for scope in cur:
            cands = []
            for el in scope.iter_desc():
                if st.kind == 'class' and st.name in el.classes():
                    cands.append(el)
                elif st.kind == 'id' and (el.attrs.get('id') or '') == st.name:
                    cands.append(el)
                elif st.kind == 'tag' and el.tag == st.name:
                    cands.append(el)
            if st.neg:
                if len(cands) > st.index:
                    cands = cands[:st.index] + cands[st.index + 1:]
            elif st.index is not None:
                cands = cands[st.index:st.index + 1]
            nxt.extend(cands)
        cur = nxt
        if not cur:
            break
    return cur


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
    if not base:
        return []
    out = []
    if js is not None:
        path = base
        if path.startswith('@json:'):
            path = path[6:]
        val = json_path(js, path)
        if isinstance(val, list):
            out = list(val)
        elif isinstance(val, dict):
            items = json_items(val)
            out = items if items else [val]
        elif val is not None:
            out = [val]
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
        if ' ' in first and not first.startswith('<'):
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
            return [apply_hash(v, rx, repl) if isinstance(v, str) else v for v in out]
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
    res = []
    for v in out:
        if isinstance(v, str):
            res.append(apply_hash(v, rx, repl))
        elif isinstance(v, (int, float, bool)):
            res.append(apply_hash(str(v), rx, repl))
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
        val = json_path(js, path)
        if isinstance(val, list):
            return val
        return json_items(val)
    if base.startswith('@css:'):
        sel = base[5:].strip()
        if '@' in sel:
            head, tail = sel.rsplit('@', 1)
            if re.match(r'^[a-zA-Z_][\w-]*$', tail.strip()):
                sel = head
        return css_find(doc, sel) if doc is not None else []
    raw_steps = base.split('@')
    first = raw_steps[0].strip()
    if ' ' in first and not first.startswith('<'):
        sel = first
        if len(raw_steps) > 1 and re.match(r'^[a-zA-Z_][\w-]*$', raw_steps[-1].strip()):
            sel = first
        return css_find(doc, sel) if doc is not None else []
    steps = [parse_step(s) for s in raw_steps]
    if any(s is None for s in steps):
        return []
    if steps and steps[-1].kind in ('text', 'html'):
        steps = steps[:-1]
    if not steps:
        return []
    return chain_find([doc], steps) if doc is not None else []
