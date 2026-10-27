"""Semantic analysis for Renixx: scope resolution, undefined variables, type checks."""
from .ast import *
from .parser import parse
from .errors import RenixxError

BUILTINS = {"print","println","input","len","type","str","int","float","bool","range",
            "abs","min","max","sum","sorted","reversed","enumerate","zip","keys","values",
            "math","random","time","json","os","fs","re","http","collections",
            "true","false","nil","this"}

KEYWORDS = {"let","const","fn","return","if","else","while","for","in","break","continue",
            "match","case","default","class","new","extends","import","from","as","export",
            "try","catch","finally","throw","and","or","not","is"}

TYPE_NAMES = {"int","float","string","bool","list","dict","nil","any"}


class Scope:
    def __init__(self, parent=None):
        self.parent = parent
        self.names = {}  # name -> kind

    def define(self, name, kind="variable"):
        self.names[name] = kind

    def lookup(self, name):
        if name in self.names:
            return self.names[name]
        if self.parent is not None:
            return self.parent.lookup(name)
        return None

    def has(self, name):
        return self.lookup(name) is not None


class SemanticAnalyzer:
    def __init__(self, text):
        self.text = text
        self.lines = text.splitlines()
        self.diagnostics = []
        # hoisted names
        self.fn_names = set()
        self.class_names = set()


    def _col_of(self, line_no, name):
        # Fallback: find first word-boundary occurrence on the line.
        # Prefer real positions (node.col / stmt.name_col) when available.
        if line_no < 1 or line_no > len(self.lines):
            return 0
        line_text = self.lines[line_no - 1]
        idx = 0
        while True:
            j = line_text.find(name, idx)
            if j == -1:
                return 0
            left_ok = (j == 0) or not (line_text[j-1].isalnum() or line_text[j-1] == "_")
            right_ok = (j + len(name) >= len(line_text)) or not (line_text[j+len(name)].isalnum() or line_text[j+len(name)] == "_")
            if left_ok and right_ok:
                return j
            idx = j + 1

    def _add_diag(self, line, col, message, severity=1, end_col=None):
        if end_col is None:
            end_col = col + 1
        self.diagnostics.append({
            "line": line, "col": col, "end_col": end_col,
            "message": message, "severity": severity,
        })

    def analyze(self, program):
        if program is None:
            return self.diagnostics
        # pre-collect hoisted names
        for stmt in program.statements:
            if isinstance(stmt, FnDecl) and stmt.name:
                self.fn_names.add(stmt.name)
            if isinstance(stmt, ClassDecl):
                self.class_names.add(stmt.name)
        scope = Scope()
        for n in self.fn_names:
            scope.define(n, "function")
        for n in self.class_names:
            scope.define(n, "class")
        # builtins
        for b in BUILTINS:
            scope.define(b, "builtin")
        self._analyze_stmts(program.statements, scope)
        return self.diagnostics

    def _analyze_stmts(self, stmts, scope):
        for s in stmts:
            self._analyze_stmt(s, scope)

    def _analyze_stmt(self, s, scope):
        if s is None:
            return
        if isinstance(s, Block):
            new_scope = Scope(scope)
            self._analyze_stmts(s.statements, new_scope)
            return
        if isinstance(s, LetStmt):
            if s.value is not None:
                self._analyze_expr(s.value, scope)
            if s.name:
                name_col = getattr(s, "name_col", 0)
                if name_col:
                    name_col = max(0, name_col - 1)
                else:
                    name_col = self._col_of(s.line, s.name)
                if s.name in scope.names:
                    self._add_diag(s.line, name_col,
                                   "Variable '%s' already defined in this scope" % s.name, 2,
                                   name_col + len(s.name))
                scope.define(s.name, "variable")
            if getattr(s, "type_annot", None):
                ta_col = getattr(s, "type_annot_col", 0)
                if ta_col:
                    ta_col = max(0, ta_col - 1)
                else:
                    ta_col = self._col_of(s.line, s.type_annot)
                if s.type_annot not in TYPE_NAMES:
                    self._add_diag(s.line, ta_col,
                                   "Unknown type '%s'" % s.type_annot, 2,
                                   ta_col + len(s.type_annot))
                # static type check for literals
                if s.value is not None and isinstance(s.value, Literal):
                    actual = None
                    v = s.value.value
                    if v is None:
                        actual = "nil"
                    elif isinstance(v, bool):
                        actual = "bool"
                    elif isinstance(v, int):
                        actual = "int"
                    elif isinstance(v, float):
                        actual = "float"
                    elif isinstance(v, str):
                        actual = "string"
                    if actual is not None and actual != s.type_annot:
                        self._add_diag(s.line, ta_col, "Type error: expected %s, got %s" % (s.type_annot, actual), 1,
                                       ta_col + len(s.type_annot))
            return
        if isinstance(s, DestructureStmt):
            if s.value is not None:
                self._analyze_expr(s.value, scope)
            for name in s.names:
                scope.define(name, "variable")
            return
        if isinstance(s, FnDecl):
            if s.name:
                scope.define(s.name, "function")
            new_scope = Scope(scope)
            for p in s.params:
                pname = p[0]
                new_scope.define(pname, "parameter")
                if len(p) > 3 and p[3]:
                    if p[3] not in TYPE_NAMES:
                        annot_col = p[4] if len(p) > 4 else 0
                        annot_line = p[5] if len(p) > 5 else 0
                        if annot_col and annot_line:
                            col = max(0, annot_col - 1)
                            diag_line = annot_line
                        elif annot_col:
                            col = max(0, annot_col - 1)
                            diag_line = s.line
                        else:
                            col = self._col_of(s.line, p[3])
                            diag_line = s.line
                        self._add_diag(diag_line, col, "Unknown type '%s'" % p[3], 2,
                                       col + len(p[3]))
            if getattr(s, "return_type", None):
                if s.return_type not in TYPE_NAMES:
                    rtc = getattr(s, "return_type_col", 0)
                    rtl = getattr(s, "return_type_line", 0)
                    if rtc:
                        col = max(0, rtc - 1)
                        diag_line = rtl if rtl else s.line
                    else:
                        col = self._col_of(s.line, s.return_type)
                        diag_line = s.line
                    self._add_diag(diag_line, col, "Unknown type '%s'" % s.return_type, 2,
                                   col + len(s.return_type))
            self._analyze_stmts(s.body.statements if isinstance(s.body, Block) else [s.body], new_scope)
            return
        if isinstance(s, ClassDecl):
            if s.name:
                scope.define(s.name, "class")
            new_scope = Scope(scope)
            new_scope.define("this", "variable")
            for m in s.methods:
                self._analyze_stmt(m, new_scope)
            for f in s.fields:
                self._analyze_stmt(f, new_scope)
            return
        if isinstance(s, IfStmt):
            self._analyze_expr(s.cond, scope)
            self._analyze_stmt(s.then_branch, scope)
            if s.else_branch is not None:
                self._analyze_stmt(s.else_branch, scope)
            return
        if isinstance(s, WhileStmt):
            self._analyze_expr(s.cond, scope)
            self._analyze_stmt(s.body, scope)
            return
        if isinstance(s, ForStmt):
            new_scope = Scope(scope)
            if s.var is not None:
                new_scope.define(s.var, "variable")
                if s.iterable is not None:
                    self._analyze_expr(s.iterable, scope)
            if s.init is not None:
                self._analyze_stmt(s.init, scope)
            if s.cond is not None:
                self._analyze_expr(s.cond, new_scope)
            if s.step is not None:
                self._analyze_expr(s.step, new_scope)
            self._analyze_stmt(s.body, new_scope)
            return
        if isinstance(s, MatchStmt):
            self._analyze_expr(s.expr, scope)
            for pat, guard, body in s.cases:
                if pat is not None:
                    self._analyze_expr(pat, scope)
                if guard is not None:
                    self._analyze_expr(guard, scope)
                self._analyze_stmt(body, Scope(scope))
            return
        if isinstance(s, TryStmt):
            self._analyze_stmt(s.try_block, scope)
            if s.catch_block is not None:
                new_scope = Scope(scope)
                if s.catch_var:
                    new_scope.define(s.catch_var, "variable")
                self._analyze_stmt(s.catch_block, new_scope)
            if s.finally_block is not None:
                self._analyze_stmt(s.finally_block, scope)
            return
        if isinstance(s, ReturnStmt):
            if s.value is not None:
                self._analyze_expr(s.value, scope)
            return
        if isinstance(s, ThrowStmt):
            self._analyze_expr(s.value, scope)
            return
        if isinstance(s, ImportStmt):
            # mark imported name as defined (best effort)
            if s.names:
                for n in s.names:
                    scope.define(n, "variable")
            elif s.alias:
                scope.define(s.alias, "variable")
            else:
                # import "x" -> module name
                base = s.path.split("/")[-1].replace(".rn", "")
                scope.define(base, "variable")
            return
        if isinstance(s, ExprStmt):
            self._analyze_expr(s.expr, scope)
            return

    def _analyze_expr(self, e, scope):
        if e is None:
            return
        if isinstance(e, Identifier):
            if e.name in KEYWORDS:
                return
            if scope.lookup(e.name) is None and e.name not in self.fn_names and e.name not in self.class_names:
                col = getattr(e, "col", 0)
                if col:
                    col = max(0, col - 1)
                else:
                    col = self._col_of(e.line, e.name)
                self._add_diag(e.line, col, "Undefined variable '%s'" % e.name, 1,
                               col + len(e.name))
            return
        if isinstance(e, Literal):
            return
        if isinstance(e, InterpolatedString):
            for kind, data in e.parts:
                if kind == "expr":
                    self._analyze_expr(data, scope)
            return
        if isinstance(e, UnaryOp):
            self._analyze_expr(e.operand, scope)
            return
        if isinstance(e, BinaryOp):
            self._analyze_expr(e.left, scope)
            self._analyze_expr(e.right, scope)
            return
        if isinstance(e, Assign):
            self._analyze_expr(e.target, scope)
            self._analyze_expr(e.value, scope)
            return
        if isinstance(e, Call):
            self._analyze_expr(e.callee, scope)
            for a in e.args:
                self._analyze_expr(a, scope)
            for _, v in e.kwargs:
                self._analyze_expr(v, scope)
            return
        if isinstance(e, Index):
            self._analyze_expr(e.obj, scope)
            self._analyze_expr(e.index, scope)
            return
        if isinstance(e, Slice):
            self._analyze_expr(e.obj, scope)
            if e.start: self._analyze_expr(e.start, scope)
            if e.stop: self._analyze_expr(e.stop, scope)
            if e.step: self._analyze_expr(e.step, scope)
            return
        if isinstance(e, Member):
            self._analyze_expr(e.obj, scope)
            return
        if isinstance(e, ListLiteral):
            for el in e.elements:
                if isinstance(el, Spread):
                    self._analyze_expr(el.value, scope)
                else:
                    self._analyze_expr(el, scope)
            return
        if isinstance(e, ListComp):
            new_scope = Scope(scope)
            new_scope.define(e.var, "variable")
            self._analyze_expr(e.iterable, scope)
            self._analyze_expr(e.expr, new_scope)
            if e.cond is not None:
                self._analyze_expr(e.cond, new_scope)
            return
        if isinstance(e, DictLiteral):
            for k, v in e.pairs:
                self._analyze_expr(k, scope)
                self._analyze_expr(v, scope)
            return
        if isinstance(e, DictComp):
            new_scope = Scope(scope)
            new_scope.define(e.var, "variable")
            self._analyze_expr(e.iterable, scope)
            self._analyze_expr(e.key, new_scope)
            self._analyze_expr(e.val, new_scope)
            if e.cond is not None:
                self._analyze_expr(e.cond, new_scope)
            return
        if isinstance(e, FunctionExpr):
            new_scope = Scope(scope)
            for p in e.params:
                new_scope.define(p[0], "parameter")
            self._analyze_stmts(e.body.statements if isinstance(e.body, Block) else [e.body], new_scope)
            return
        if isinstance(e, Lambda):
            new_scope = Scope(scope)
            for p in e.params:
                new_scope.define(p[0], "parameter")
            self._analyze_expr(e.body, new_scope)
            return
        if isinstance(e, NewExpr):
            if e.class_name not in self.class_names and scope.lookup(e.class_name) is None:
                col = getattr(e, "class_name_col", 0)
                if col:
                    col = max(0, col - 1)
                    diag_line = e.line
                else:
                    col = self._col_of(e.line, e.class_name)
                    diag_line = e.line
                self._add_diag(diag_line, col, "Unknown class '%s'" % e.class_name, 1,
                               col + len(e.class_name))
            for a in e.args:
                self._analyze_expr(a, scope)
            return
        if isinstance(e, Ternary):
            self._analyze_expr(e.cond, scope)
            self._analyze_expr(e.then_expr, scope)
            self._analyze_expr(e.else_expr, scope)
            return
        if isinstance(e, Spread):
            self._analyze_expr(e.value, scope)
            return


def analyze(text):
    try:
        program = parse(text)
    except RenixxError as e:
        return [], e  # syntax error handled separately
    sa = SemanticAnalyzer(text)
    diags = sa.analyze(program)
    return diags, None
