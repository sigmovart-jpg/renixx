"""Pretty-printer for Renixx source code."""
from .ast import *
from .parser import parse

class Formatter:
    def __init__(self, indent=2):
        self.indent = indent
        self.level = 0

    def pad(self):
        return " " * (self.level * self.indent)

    def format(self, program):
        out = []
        for i, s in enumerate(program.statements):
            out.append(self.stmt(s))
            out.append("\n")
        return "".join(out)

    def stmt(self, s):
        if isinstance(s, Block):
            return self.block(s)
        if isinstance(s, LetStmt):
            r = "let %s" % s.name
            if getattr(s, "type_annot", None):
                r += ": " + s.type_annot
            if s.value is not None:
                r += " = " + self.expr(s.value)
            return self.pad() + r
        if isinstance(s, ConstStmt):
            # ConstStmt subclass of LetStmt
            r = "const %s" % s.name
            if s.value is not None:
                r += " = " + self.expr(s.value)
            return self.pad() + r
        if isinstance(s, DestructureStmt):
            if s.kind == "list":
                names = "[" + ", ".join(s.names) + "]"
            else:
                names = "{" + ", ".join(s.names) + "}"
            r = ("let " if s.mutable else "const ") + names + " = " + self.expr(s.value)
            return self.pad() + r
        if isinstance(s, ExprStmt):
            return self.pad() + self.expr(s.expr)
        if isinstance(s, FnDecl):
            r = "fn"
            if s.name:
                r += " " + s.name
            r += self.params(s.params)
            if getattr(s, "return_type", None):
                r += " -> " + s.return_type
            r += " " + self.block(s.body)
            return self.pad() + r
        if isinstance(s, ClassDecl):
            r = "class " + s.name
            if s.superclass:
                r += " extends " + s.superclass
            r += " " + self.block_from_stmts(s.methods + s.fields)
            return self.pad() + r
        if isinstance(s, IfStmt):
            r = "if " + self.expr(s.cond) + " " + self.block(s.then_branch)
            if s.else_branch is not None:
                if isinstance(s.else_branch, IfStmt):
                    r += " else " + self.stmt(s.else_branch).strip()
                else:
                    r += " else " + self.block(s.else_branch)
            return self.pad() + r
        if isinstance(s, WhileStmt):
            return self.pad() + "while " + self.expr(s.cond) + " " + self.block(s.body)
        if isinstance(s, ForStmt):
            if s.var is not None:
                return self.pad() + "for %s in %s %s" % (s.var, self.expr(s.iterable), self.block(s.body))
            parts = []
            if s.init is not None:
                parts.append(self.stmt(s.init).strip())
            parts.append(self.expr(s.cond) if s.cond else "")
            parts.append(self.expr(s.step) if s.step else "")
            return self.pad() + "for (%s; %s; %s) %s" % (parts[0], parts[1], parts[2], self.block(s.body))
        if isinstance(s, MatchStmt):
            r = "match " + self.expr(s.expr) + " {\n"
            self.level += 1
            for pat, guard, body in s.cases:
                if pat is None:
                    r += self.pad() + "default"
                else:
                    r += self.pad() + self.expr(pat)
                    if guard is not None:
                        r += " if " + self.expr(guard)
                formatted_body = (
                    self.block(body)
                    if isinstance(body, Block)
                    else self.block_inline(body)
                )
                r += " => " + formatted_body + "\n"
            self.level -= 1
            r += self.pad() + "}"
            return self.pad() + r
        if isinstance(s, TryStmt):
            r = "try " + self.block(s.try_block)
            if s.catch_block is not None:
                r += " catch"
                if s.catch_var:
                    r += " " + s.catch_var
                r += " " + self.block(s.catch_block)
            if s.finally_block is not None:
                r += " finally " + self.block(s.finally_block)
            return self.pad() + r
        if isinstance(s, ReturnStmt):
            if s.value is not None:
                return self.pad() + "return " + self.expr(s.value)
            return self.pad() + "return"
        if isinstance(s, ThrowStmt):
            return self.pad() + "throw " + self.expr(s.value)
        if isinstance(s, BreakStmt):
            return self.pad() + "break"
        if isinstance(s, ContinueStmt):
            return self.pad() + "continue"
        if isinstance(s, ImportStmt):
            if s.names is not None:
                names = ", ".join(s.names) if s.names else "*"
                return self.pad() + 'from "%s" import %s' % (s.path, names)
            if s.alias:
                return self.pad() + 'import "%s" as %s' % (s.path, s.alias)
            return self.pad() + 'import "%s"' % s.path
        return self.pad() + self.expr(s.expr) if hasattr(s, "expr") else self.pad() + str(s)

    def block(self, b):
        if not isinstance(b, Block):
            return self.stmt(b)
        self.level += 1
        lines = []
        for s in b.statements:
            lines.append(self.stmt(s))
        self.level -= 1
        if not lines:
            return "{}"
        return "{\n" + "\n".join(lines) + "\n" + self.pad() + "}"

    def block_from_stmts(self, stmts):
        b = Block(statements=stmts)
        return self.block(b)

    def block_inline(self, b):
        if isinstance(b, Block):
            if len(b.statements) == 1:
                return self.stmt(b.statements[0]).strip()
            return self.block(b)
        return self.stmt(b).strip()

    def params(self, params):
        parts = []
        for p in params:
            name = p[0]
            default = p[1] if len(p) > 1 else None
            rest = p[2] if len(p) > 2 else False
            annot = p[3] if len(p) > 3 else None
            # annot_col = p[4] if len(p) > 4 else 0  (not used in formatting)
            seg = name
            if annot:
                seg += ": " + annot
            if rest:
                seg = "..." + seg
            if default is not None:
                seg += " = " + self.expr(default)
            parts.append(seg)
        return "(" + ", ".join(parts) + ")"

    def expr(self, e):
        if isinstance(e, Literal):
            if isinstance(e.value, str):
                return repr(e.value)
            if e.value is None:
                return "nil"
            if e.value is True:
                return "true"
            if e.value is False:
                return "false"
            return str(e.value)
        if isinstance(e, InterpolatedString):
            parts = []
            for kind, data in e.parts:
                if kind == "text":
                    parts.append(data.replace("{", "{{").replace("}", "}}"))
                else:
                    parts.append("{" + self.expr(data) + "}")
            return '"' + "".join(parts) + '"'
        if isinstance(e, Identifier):
            return e.name
        if isinstance(e, UnaryOp):
            if e.op == "not":
                return "not " + self.expr(e.operand)
            return e.op + self.expr(e.operand)
        if isinstance(e, BinaryOp):
            return "%s %s %s" % (self.expr(e.left), e.op, self.expr(e.right))
        if isinstance(e, Assign):
            if e.op == "=":
                return "%s = %s" % (self.expr(e.target), self.expr(e.value))
            return "%s %s %s" % (self.expr(e.target), e.op, self.expr(e.value))
        if isinstance(e, Call):
            args = [self.expr(a) for a in e.args]
            for name, val in e.kwargs:
                args.append("%s = %s" % (name, self.expr(val)))
            return "%s(%s)" % (self.expr(e.callee), ", ".join(args))
        if isinstance(e, Index):
            return "%s[%s]" % (self.expr(e.obj), self.expr(e.index))
        if isinstance(e, Slice):
            s = self.expr(e.obj) + "["
            s += self.expr(e.start) if e.start else ""
            s += ":"
            if e.stop:
                s += self.expr(e.stop)
            if e.step:
                s += ":" + self.expr(e.step)
            s += "]"
            return s
        if isinstance(e, Member):
            return "%s.%s" % (self.expr(e.obj), e.name)
        if isinstance(e, ListLiteral):
            return "[" + ", ".join(self.expr(x) for x in e.elements) + "]"
        if isinstance(e, ListComp):
            r = "[" + self.expr(e.expr) + " for " + e.var + " in " + self.expr(e.iterable)
            if e.cond is not None:
                r += " if " + self.expr(e.cond)
            r += "]"
            return r
        if isinstance(e, DictLiteral):
            pairs = ", ".join("%s: %s" % (self.expr(k), self.expr(v)) for k, v in e.pairs)
            return "{" + pairs + "}"
        if isinstance(e, DictComp):
            r = "{" + self.expr(e.key) + ": " + self.expr(e.val) + " for " + e.var + " in " + self.expr(e.iterable)
            if e.cond is not None:
                r += " if " + self.expr(e.cond)
            r += "}"
            return r
        if isinstance(e, FunctionExpr):
            return "fn" + ("" if e.name is None else " " + e.name) + self.params(e.params) + " " + self.block(e.body)
        if isinstance(e, Lambda):
            if len(e.params) == 1 and e.params[0][1] is None and not e.params[0][2]:
                return "%s => %s" % (e.params[0][0], self.expr(e.body))
            return self.params(e.params) + " => " + self.expr(e.body)
        if isinstance(e, NewExpr):
            args = ", ".join(self.expr(a) for a in e.args)
            return "new %s(%s)" % (e.class_name, args)
        if isinstance(e, Ternary):
            return "%s ? %s : %s" % (self.expr(e.cond), self.expr(e.then_expr), self.expr(e.else_expr))
        if isinstance(e, Spread):
            return "..." + self.expr(e.value)
        if isinstance(e, RangeExpr):
            r = self.expr(e.start) + ".." + self.expr(e.stop)
            if e.step is not None:
                r += " step " + self.expr(e.step)
            return r
        return str(e)

def format_source(source):
    program = parse(source)
    return Formatter().format(program)
