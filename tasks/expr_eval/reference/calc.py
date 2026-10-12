"""Reference solution (never shown to the model; used by `run_bench.py selftest`)."""

_DIGITS = "0123456789"
_PUNCT = "+-*/%^(),"


def _is_name_start(c):
    return c == "_" or ("a" <= c <= "z") or ("A" <= c <= "Z")


def _tokenize(s):
    tokens, i = [], 0
    while i < len(s):
        c = s[i]
        if c in " \t":
            i += 1
        elif c in _DIGITS:
            j = i
            while j < len(s) and s[j] in _DIGITS:
                j += 1
            tokens.append(("num", int(s[i:j])))
            i = j
        elif _is_name_start(c):
            j = i
            while j < len(s) and (_is_name_start(s[j]) or s[j] in _DIGITS):
                j += 1
            tokens.append(("name", s[i:j]))
            i = j
        elif c in _PUNCT:
            tokens.append(("op", c))
            i += 1
        else:
            raise SyntaxError(f"invalid character {c!r}")
    tokens.append(("end", None))
    return tokens


class _Parser:
    def __init__(self, tokens):
        self.tokens = tokens
        self.i = 0

    def peek(self):
        return self.tokens[self.i]

    def take(self):
        tok = self.tokens[self.i]
        self.i += 1
        return tok

    def expect(self, op):
        if self.take() != ("op", op):
            raise SyntaxError(f"expected {op!r}")

    def parse(self):
        node = self.expr()
        if self.peek()[0] != "end":
            raise SyntaxError("unexpected token")
        return node

    def expr(self):
        node = self.term()
        while self.peek() in (("op", "+"), ("op", "-")):
            node = ("bin", self.take()[1], node, self.term())
        return node

    def term(self):
        node = self.unary()
        while self.peek() in (("op", "*"), ("op", "/"), ("op", "%")):
            node = ("bin", self.take()[1], node, self.unary())
        return node

    def unary(self):
        if self.peek() == ("op", "-"):
            self.take()
            return ("neg", self.unary())
        return self.power()

    def power(self):
        base = self.atom()
        if self.peek() == ("op", "^"):
            self.take()
            return ("bin", "^", base, self.unary())
        return base

    def atom(self):
        kind, value = self.take()
        if kind == "num":
            return ("num", value)
        if kind == "name":
            if self.peek() == ("op", "("):
                self.take()
                args = [self.expr()]
                while self.peek() == ("op", ","):
                    self.take()
                    args.append(self.expr())
                self.expect(")")
                return ("call", value, args)
            return ("var", value)
        if (kind, value) == ("op", "("):
            node = self.expr()
            self.expect(")")
            return node
        raise SyntaxError("expected a number, a name or '('")


def _div(a, b):
    if b == 0:
        raise ZeroDivisionError("division by zero")
    q = abs(a) // abs(b)
    return q if (a >= 0) == (b >= 0) else -q


def _run(node, env):
    kind = node[0]
    if kind == "num":
        return node[1]
    if kind == "var":
        if node[1] not in env:
            raise NameError(node[1])
        value = env[node[1]]
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError(f"variable {node[1]!r} is not an int")
        return value
    if kind == "neg":
        return -_run(node[1], env)
    if kind == "call":
        name, args = node[1], [_run(a, env) for a in node[2]]
        if name == "abs":
            if len(args) != 1:
                raise TypeError("abs takes exactly 1 argument")
            return abs(args[0])
        if name == "min":
            return min(args)
        if name == "max":
            return max(args)
        raise NameError(name)
    op, a, b = node[1], _run(node[2], env), _run(node[3], env)
    if op == "+":
        return a + b
    if op == "-":
        return a - b
    if op == "*":
        return a * b
    if op == "/":
        return _div(a, b)
    if op == "%":
        return a - b * _div(a, b)
    if b < 0:
        raise ValueError("negative exponent")
    return a ** b


def evaluate(expr, variables=None):
    if not isinstance(expr, str):
        raise TypeError("expr must be str")
    tree = _Parser(_tokenize(expr)).parse()
    return _run(tree, {} if variables is None else variables)
