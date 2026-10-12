"""Reference solution (never shown to the model; used by `run_bench.py selftest`)."""
import re

_CELL = re.compile(r"[A-Z][1-9][0-9]{0,2}")
_INT = re.compile(r"-?[0-9]+")
_FUNCS = {"SUM", "MIN", "MAX", "COUNT", "IF"}
_CMP = {"=", "<>", "<", ">", "<=", ">="}


class _Err:
    __slots__ = ("code",)

    def __init__(self, code):
        self.code = code


PARSE, NAME, REF = _Err("#PARSE!"), _Err("#NAME?"), _Err("#REF!")
VALUE, DIV0, CYCLE = _Err("#VALUE!"), _Err("#DIV/0!"), _Err("#CYCLE!")
_EMPTY = object()


class _ParseError(Exception):
    pass


def _cell_name(name):
    if not isinstance(name, str) or not _CELL.fullmatch(name.upper()):
        raise ValueError(f"invalid cell name {name!r}")
    return name.upper()


def _tokenize(text):
    tokens, i = [], 0
    while i < len(text):
        c = text[i]
        if c == " ":
            i += 1
        elif c.isascii() and c.isdigit():
            j = i
            while j < len(text) and text[j].isascii() and text[j].isdigit():
                j += 1
            tokens.append(("num", int(text[i:j])))
            i = j
        elif c.isascii() and c.isalpha():
            j = i
            while j < len(text) and text[j].isascii() and text[j].isalpha():
                j += 1
            k = j
            while k < len(text) and text[k].isascii() and text[k].isdigit():
                k += 1
            word = text[i:k].upper()
            if k > j:
                tokens.append(("ref", word) if _CELL.fullmatch(word) else ("badref", word))
            else:
                tokens.append(("word", word))
            i = k
        elif text[i:i + 2] in ("<=", ">=", "<>"):
            tokens.append(("op", text[i:i + 2]))
            i += 2
        elif c in "=<>+-*/(),:":
            tokens.append(("op", c))
            i += 1
        else:
            raise _ParseError(f"bad character {c!r}")
    tokens.append(("end", None))
    return tokens


class _Parser:
    def __init__(self, tokens):
        self.tokens, self.i = tokens, 0

    def peek(self):
        return self.tokens[self.i]

    def take(self):
        tok = self.tokens[self.i]
        self.i += 1
        return tok

    def expect(self, op):
        if self.take() != ("op", op):
            raise _ParseError(f"expected {op}")

    def parse(self):
        node = self.comparison()
        if self.peek()[0] != "end":
            raise _ParseError("trailing tokens")
        return node

    def comparison(self):
        node = self.additive()
        if self.peek()[0] == "op" and self.peek()[1] in _CMP:
            op = self.take()[1]
            node = ("cmp", op, node, self.additive())
            if self.peek()[0] == "op" and self.peek()[1] in _CMP:
                raise _ParseError("comparisons are non-associative")
        return node

    def additive(self):
        node = self.term()
        while self.peek() in (("op", "+"), ("op", "-")):
            node = ("bin", self.take()[1], node, self.term())
        return node

    def term(self):
        node = self.unary()
        while self.peek() in (("op", "*"), ("op", "/")):
            node = ("bin", self.take()[1], node, self.unary())
        return node

    def unary(self):
        if self.peek() == ("op", "-"):
            self.take()
            return ("neg", self.unary())
        return self.primary()

    def primary(self):
        kind, value = self.take()
        if kind == "num":
            return ("num", value)
        if kind in ("ref", "badref"):
            if self.peek() == ("op", ":"):
                self.take()
                kind2, value2 = self.take()
                if kind2 not in ("ref", "badref"):
                    raise _ParseError("bad range")
                return ("range", (kind, value), (kind2, value2))
            return (kind, value)
        if kind == "word":
            if self.peek() != ("op", "("):
                return ("name", value)
            self.take()
            args = [self.comparison()]
            while self.peek() == ("op", ","):
                self.take()
                args.append(self.comparison())
            self.expect(")")
            if value == "IF" and len(args) != 3:
                raise _ParseError("IF takes 3 arguments")
            return ("call", value, args)
        if (kind, value) == ("op", "("):
            node = self.comparison()
            self.expect(")")
            return node
        raise _ParseError("unexpected token")


def _walk(node):
    yield node
    kind = node[0]
    if kind == "neg":
        yield from _walk(node[1])
    elif kind in ("bin", "cmp"):
        yield from _walk(node[2])
        yield from _walk(node[3])
    elif kind == "call":
        for arg in node[2]:
            yield from _walk(arg)


def _range_cells(a, b):
    c1, c2 = sorted((a[0], b[0]))
    r1, r2 = sorted((int(a[1:]), int(b[1:])))
    return [f"{chr(c)}{r}" for r in range(r1, r2 + 1) for c in range(ord(c1), ord(c2) + 1)]


def _compile(text):
    """-> (static_error_or_None, ast_or_None, deps)"""
    try:
        ast = _Parser(_tokenize(text)).parse()
    except _ParseError:
        return PARSE, None, set()
    nodes = list(_walk(ast))
    deps = set()
    for n in nodes:
        if n[0] == "ref":
            deps.add(n[1])
        elif n[0] == "range" and n[1][0] == "ref" and n[2][0] == "ref":
            deps.update(_range_cells(n[1][1], n[2][1]))
    if any(n[0] == "name" or (n[0] == "call" and n[1] not in _FUNCS) for n in nodes):
        return NAME, None, deps
    if any(n[0] == "badref" or (n[0] == "range" and "badref" in (n[1][0], n[2][0])) for n in nodes):
        return REF, None, deps
    return None, ast, deps


def _trunc_div(a, b):
    q = abs(a) // abs(b)
    return q if (a >= 0) == (b >= 0) else -q


class Sheet:
    def __init__(self):
        self._cells = {}     # name -> ("int", v) | ("str", s) | ("formula", static_err, ast, deps)
        self._values = None  # name -> value, recomputed after any change

    def set(self, name, raw):
        if not isinstance(raw, str):
            raise TypeError("raw must be str")
        name = _cell_name(name)
        self._values = None
        if raw == "":
            self._cells.pop(name, None)
        elif raw.startswith("="):
            self._cells[name] = ("formula",) + _compile(raw[1:])
        elif _INT.fullmatch(raw):
            self._cells[name] = ("int", int(raw))
        else:
            self._cells[name] = ("str", raw)

    def get(self, name):
        name = _cell_name(name)
        if self._values is None:
            self._recompute()
        value = self._values.get(name, _EMPTY)
        if value is _EMPTY:
            return None
        return value.code if isinstance(value, _Err) else value

    # ------------------------------------------------------------ evaluation

    def _deps(self, name):
        cell = self._cells.get(name)
        return cell[3] if cell and cell[0] == "formula" else ()

    def _cycle_cells(self):
        """Tarjan SCC, iterative. Cells in an SCC of size > 1 or with a self-loop."""
        index, low, on_stack, stack, result, counter = {}, {}, set(), [], set(), [0]
        for root in self._cells:
            if root in index:
                continue
            work = [(root, iter(sorted(self._deps(root))))]
            index[root] = low[root] = counter[0]
            counter[0] += 1
            stack.append(root)
            on_stack.add(root)
            while work:
                node, children = work[-1]
                advanced = False
                for child in children:
                    if child not in index:
                        index[child] = low[child] = counter[0]
                        counter[0] += 1
                        stack.append(child)
                        on_stack.add(child)
                        work.append((child, iter(sorted(self._deps(child)))))
                        advanced = True
                        break
                    if child in on_stack:
                        low[node] = min(low[node], index[child])
                if advanced:
                    continue
                work.pop()
                if work:
                    parent = work[-1][0]
                    low[parent] = min(low[parent], low[node])
                if low[node] == index[node]:
                    comp = []
                    while True:
                        top = stack.pop()
                        on_stack.discard(top)
                        comp.append(top)
                        if top == node:
                            break
                    if len(comp) > 1 or node in self._deps(node):
                        result.update(comp)
        return result

    def _recompute(self):
        cycles = self._cycle_cells()
        values = {}
        for name in cycles:
            values[name] = CYCLE
        # post-order DFS so every dependency is computed before the cell that reads it
        for root in self._cells:
            if root in values:
                continue
            work = [(root, False)]
            while work:
                name, ready = work.pop()
                if name in values:
                    continue
                if ready:
                    values[name] = self._evaluate_cell(name, values)
                    continue
                work.append((name, True))
                for dep in self._deps(name):
                    if dep not in values and dep in self._cells:
                        work.append((dep, False))
        self._values = values

    def _evaluate_cell(self, name, values):
        cell = self._cells[name]
        if cell[0] != "formula":
            return cell[1]
        if cell[1] is not None:
            return cell[1]
        return self._eval(cell[2], values)

    def _read(self, name, values):
        return values.get(name, _EMPTY) if name in self._cells else _EMPTY

    def _eval(self, node, values):
        kind = node[0]
        if kind == "num":
            return node[1]
        if kind == "ref":
            v = self._read(node[1], values)
            return 0 if v is _EMPTY else v
        if kind == "range":
            return VALUE
        if kind == "neg":
            v = self._eval(node[1], values)
            if isinstance(v, _Err):
                return v
            return VALUE if isinstance(v, str) else -v
        if kind == "bin":
            a, b = self._eval(node[2], values), self._eval(node[3], values)
            for v in (a, b):
                if isinstance(v, _Err):
                    return v
            if isinstance(a, str) or isinstance(b, str):
                return VALUE
            op = node[1]
            if op == "+":
                return a + b
            if op == "-":
                return a - b
            if op == "*":
                return a * b
            return DIV0 if b == 0 else _trunc_div(a, b)
        if kind == "cmp":
            a, b = self._eval(node[2], values), self._eval(node[3], values)
            for v in (a, b):
                if isinstance(v, _Err):
                    return v
            op = node[1]
            if op in ("=", "<>"):
                same = type(a) is type(b) and a == b
                return int(same if op == "=" else not same)
            if type(a) is not type(b):
                return VALUE
            return int({"<": a < b, ">": a > b, "<=": a <= b, ">=": a >= b}[op])
        # call
        fn, args = node[1], node[2]
        if fn == "IF":
            cond = self._eval(args[0], values)
            if isinstance(cond, _Err):
                return cond
            if isinstance(cond, str):
                return VALUE
            return self._eval(args[1] if cond != 0 else args[2], values)
        numbers = []
        for arg in args:
            if arg[0] == "range":
                items = [self._read(c, values) for c in _range_cells(arg[1][1], arg[2][1])]
                items = [v for v in items if v is not _EMPTY and not isinstance(v, str)]
            else:
                v = self._eval(arg, values)
                if isinstance(v, str):
                    v = VALUE
                items = [v]
            for v in items:
                if isinstance(v, _Err):
                    if fn == "COUNT":
                        continue
                    return v
                numbers.append(v)
        if fn == "COUNT":
            return len(numbers)
        if fn == "SUM":
            return sum(numbers)
        if not numbers:
            return 0
        return min(numbers) if fn == "MIN" else max(numbers)
