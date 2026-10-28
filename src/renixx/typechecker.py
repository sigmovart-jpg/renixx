"""Static type checker for the Renixx language.

This module provides optional static type checking for Renixx programs.
It works on the AST produced by the parser and returns a list of
diagnostics (dicts with keys: line, col, end_col, message, severity, source).

Types are represented as strings: "int", "float", "string", "bool",
"nil", "list", "dict", "function", "class", "instance", "any", "unknown",
or parameterized like "list[int]", "dict[string, int]".

"unknown" means the type could not be inferred (dynamic, not checked).
"any" means compatible with all types (for unannotated constructs).

The checker is conservative: it only reports errors when types are
explicitly annotated and provably incompatible. Unannotated code is
never flagged.
"""
from .ast import *
from .parser import parse


# Type names recognized in annotations (base names; parameterized like list[int] are validated separately)
TYPE_NAMES = {"int", "float", "string", "bool", "nil", "list", "dict",
              "any", "unknown"}


def parse_type(s):
    """Parse a type string into (name, args) tuple. E.g. 'list[int]' -> ('list', ['int'])."""
    s = s.strip()
    if not s:
        return ("unknown", [])
    bracket_idx = s.find("[")
    if bracket_idx != -1:
        name = s[:bracket_idx].strip()
        depth = 0
        args_str = ""
        for j in range(bracket_idx, len(s)):
            if s[j] == "[":
                depth += 1
            elif s[j] == "]":
                depth -= 1
                if depth == 0:
                    args_str = s[bracket_idx + 1:j]
                    break
        args = _split_type_args(args_str)
        return (name, [a.strip() for a in args if a.strip()])
    return (s, [])


def _split_type_args(s):
    """Split type arguments by top-level commas."""
    args = []
    depth = 0
    current = ""
    for ch in s:
        if ch == "[":
            depth += 1
            current += ch
        elif ch == "]":
            depth -= 1
            current += ch
        elif ch == "," and depth == 0:
            args.append(current.strip())
            current = ""
        else:
            current += ch
    if current.strip():
        args.append(current.strip())
    return args


class Scope:
    """Scope for type information."""

    def __init__(self, parent=None):
        self.parent = parent
        self.types = {}  # name -> type string
        self.kinds = {}  # name -> kind string

    def define(self, name, typ="unknown", kind="variable"):
        self.types[name] = typ
        self.kinds[name] = kind

    def lookup_type(self, name):
        if name in self.types:
            return self.types[name]
        if self.parent is not None:
            return self.parent.lookup_type(name)
        return None

    def has(self, name):
        if name in self.types:
            return True
        if self.parent is not None:
            return self.parent.has(name)
        return False


class TypeChecker:
    """Static type checker for Renixx AST."""

    def __init__(self, text):
        self.text = text
        self.lines = text.splitlines()
        self.diagnostics = []
        self.fn_types = {}  # function name -> (param_types, return_type)
        self.class_types = {}  # class name -> {methods, fields}

    def _col(self, node, name=None):
        """Get 0-based column for a node or name."""
        col = getattr(node, "col", 0) or 0
        if col:
            return max(0, col - 1)
        if name and hasattr(node, "line"):
            line_no = node.line
            if 1 <= line_no <= len(self.lines):
                line_text = self.lines[line_no - 1]
                idx = line_text.find(name)
                if idx >= 0:
                    return idx
        return 0

    def _add_diag(self, line, col, message, severity=1, end_col=None):
        if end_col is None:
            end_col = col + 1
        self.diagnostics.append({
            "line": line,
            "col": col,
            "end_col": end_col,
            "message": message,
            "severity": severity,
            "source": "typechecker",
        })

    def check(self, program):
        if program is None:
            return self.diagnostics
        # Pre-collect function and class types
        self._collect_types(program)
        # Hoist function/class names into global scope
        scope = Scope()
        for name, (params, ret) in self.fn_types.items():
            scope.define(name, "function", "function")
        for name in self.class_types:
            scope.define(name, "class", "class")
        # Builtins
        for b in ("print", "println", "input", "len", "type", "str", "int",
                  "float", "bool", "range", "abs", "min", "max", "sum",
                  "sorted", "reversed", "enumerate", "zip", "keys", "values",
                  "math", "random", "time", "json", "os", "fs", "re", "http",
                  "collections"):
            scope.define(b, "any", "builtin")
        self._check_stmts(program.statements, scope)
        return self.diagnostics

    def _collect_types(self, program):
        """First pass: collect function signatures and class info."""
        for stmt in program.statements:
            if isinstance(stmt, FnDecl) and stmt.name:
                params = []
                for p in stmt.params:
                    pname = p[0]
                    annot = p[3] if len(p) > 3 else None
                    is_rest = p[2] if len(p) > 2 else False
                    params.append((pname, annot or "unknown", is_rest))
                ret = stmt.return_type or "unknown"
                self.fn_types[stmt.name] = (params, ret)
            if isinstance(stmt, ClassDecl):
                self.class_types[stmt.name] = {
                    "methods": {},
                    "fields": {},
                }
                for m in stmt.methods:
                    if m.name:
                        mparams = []
                        for p in m.params:
                            pname = p[0]
                            annot = p[3] if len(p) > 3 else None
                            is_rest = p[2] if len(p) > 2 else False
                            mparams.append((pname, annot or "unknown", is_rest))
                        mret = m.return_type or "unknown"
                        self.class_types[stmt.name]["methods"][m.name] = (mparams, mret)

    def _check_stmts(self, stmts, scope):
        for s in stmts:
            self._check_stmt(s, scope)

    def _check_stmt(self, s, scope):
        if s is None:
            return
        if isinstance(s, Block):
            new_scope = Scope(scope)
            self._check_stmts(s.statements, new_scope)
            return
        if isinstance(s, LetStmt):
            val_type = "unknown"
            if s.value is not None:
                val_type = self._infer_type(s.value, scope)
                if s.type_annot:
                    base_type = s.type_annot.split("[")[0].strip()
                    if base_type not in TYPE_NAMES:
                        col = getattr(s, "type_annot_col", 0)
                        col = max(0, col - 1) if col else self._col_of(s.line, s.type_annot)
                        self._add_diag(s.line, col, "Unknown type '%s'" % s.type_annot, 2,
                                       col + len(s.type_annot))
                    elif not self._compatible(val_type, s.type_annot) and not (s.type_annot.startswith("list[") and isinstance(s.value, ListLiteral) and val_type.split("[")[0].strip() == s.type_annot.split("[")[0].strip()) and not (s.type_annot.startswith("dict[") and isinstance(s.value, DictLiteral) and val_type.split("[")[0].strip() == s.type_annot.split("[")[0].strip()):
                        col = getattr(s, "name_col", 0)
                        col = max(0, col - 1) if col else self._col_of(s.line, s.name)
                        self._add_diag(s.line, col,
                                       "Type error: expected %s, got %s" % (s.type_annot, val_type), 1,
                                       col + len(s.name))
                    # Check collection element types recursively
                    self._check_collection_elements(s.value, s.type_annot, scope, s.line)

            if s.name:
                if s.type_annot:
                    typ = s.type_annot
                elif s.value is not None:
                    typ = val_type
                else:
                    typ = "unknown"
                scope.define(s.name, typ)
            return
        if isinstance(s, DestructureStmt):
            if s.value is not None:
                self._infer_type(s.value, scope)
            for name in s.names:
                scope.define(name, "unknown")
            return
        if isinstance(s, FnDecl):
            if s.name:
                scope.define(s.name, "function")
            new_scope = Scope(scope)
            for p in s.params:
                pname = p[0]
                annot = p[3] if len(p) > 3 else None
                annot_col = p[4] if len(p) > 4 else 0
                if annot and annot.split("[")[0].strip() not in TYPE_NAMES:
                    col = max(0, annot_col - 1) if annot_col else self._col_of(s.line, annot)
                    self._add_diag(s.line, col, "Unknown type '%s'" % annot, 2,
                                   col + len(annot))
                ptype = annot if annot else "unknown"
                new_scope.define(pname, ptype)
            if getattr(s, "return_type", None):
                base_type = s.return_type.split("[")[0].strip()
                if base_type not in TYPE_NAMES:
                    rtc = getattr(s, "return_type_col", 0)
                    col = max(0, rtc - 1) if rtc else self._col_of(s.line, s.return_type)
                    self._add_diag(s.line, col, "Unknown type '%s'" % s.return_type, 2,
                                   col + len(s.return_type))
            if isinstance(s.body, Block):
                self._check_stmts(s.body.statements, new_scope)
            if s.return_type and s.return_type.split("[")[0].strip() in TYPE_NAMES:
                self._check_returns(s.body, new_scope, s.return_type)
            return
        if isinstance(s, ClassDecl):
            if s.name:
                scope.define(s.name, "class")
            new_scope = Scope(scope)
            new_scope.define("this", s.name)
            if getattr(s, "superclass", None):
                new_scope.define("super", s.superclass)
            for f in s.fields:
                self._check_stmt(f, new_scope)
            for m in s.methods:
                self._check_stmt(m, new_scope)
            return
        if isinstance(s, IfStmt):
            self._infer_type(s.cond, scope)
            self._check_stmt(s.then_branch, scope)
            if s.else_branch is not None:
                self._check_stmt(s.else_branch, scope)
            return
        if isinstance(s, WhileStmt):
            self._infer_type(s.cond, scope)
            self._check_stmt(s.body, scope)
            return
        if isinstance(s, ForStmt):
            new_scope = Scope(scope)
            if s.var is not None:
                if s.iterable is not None:
                    it_type = self._infer_type(s.iterable, scope)
                    parsed = parse_type(it_type)
                    elem_type = parsed[1][0] if parsed[0] == "list" and parsed[1] else "unknown"
                    new_scope.define(s.var, elem_type)
            if s.init is not None:
                self._check_stmt(s.init, new_scope)
            if s.cond is not None:
                self._infer_type(s.cond, new_scope)
            if s.step is not None:
                self._infer_type(s.step, new_scope)
            self._check_stmt(s.body, new_scope)
            return
        if isinstance(s, MatchStmt):
            self._infer_type(s.expr, scope)
            for pat, guard, body in s.cases:
                case_scope = Scope(scope)
                if guard is not None:
                    self._infer_type(guard, case_scope)
                self._check_stmt(body, case_scope)
            return
        if isinstance(s, TryStmt):
            self._check_stmt(s.try_block, scope)
            if s.catch_block is not None:
                new_scope = Scope(scope)
                if s.catch_var:
                    new_scope.define(s.catch_var, "any")
                self._check_stmt(s.catch_block, new_scope)
            if s.finally_block is not None:
                self._check_stmt(s.finally_block, scope)
            return
        if isinstance(s, ReturnStmt):
            if s.value is not None:
                self._infer_type(s.value, scope)
            return
        if isinstance(s, ThrowStmt):
            self._infer_type(s.value, scope)
            return
        if isinstance(s, ExprStmt):
            self._infer_type(s.expr, scope)
            return
        if isinstance(s, ImportStmt):
            return

    def _check_returns(self, body, scope, expected_type):
        if body is None:
            return
        if isinstance(body, Block):
            for s in body.statements:
                self._check_returns(s, scope, expected_type)
            return
        if isinstance(body, ReturnStmt):
            if body.value is not None:
                actual = self._infer_type(body.value, scope)
                # Check collection element types in return values
                if expected_type.startswith("list[") and isinstance(body.value, ListLiteral):
                    elem_type = expected_type[len("list["):-1].strip()
                    for elem in body.value.elements:
                        elem_actual = self._infer_type(elem, scope)
                        if elem_actual not in ("unknown", "any") and not self._compatible(elem_actual, elem_type):
                            col = 0
                            if hasattr(elem, "col"):
                                col = max(0, elem.col - 1)
                            self._add_diag(elem.line if hasattr(elem, "line") else body.line, col,
                                           "Type error: expected %s, got %s" % (elem_type, elem_actual), 1)
                elif expected_type.startswith("dict[") and isinstance(body.value, DictLiteral):
                    inner = expected_type[len("dict["):-1].strip()
                    parts = []
                    depth = 0
                    current = ""
                    for ch in inner:
                        if ch == "[":
                            depth += 1
                            current += ch
                        elif ch == "]":
                            depth -= 1
                            current += ch
                        elif ch == "," and depth == 0:
                            parts.append(current.strip())
                            current = ""
                        else:
                            current += ch
                    if current.strip():
                        parts.append(current.strip())
                    if len(parts) >= 2:
                        key_type = parts[0]
                        val_type = parts[1]
                        for k, v in body.value.pairs:
                            ak = self._infer_type(k, scope)
                            av = self._infer_type(v, scope)
                            if ak not in ("unknown", "any") and not self._compatible(ak, key_type):
                                col = getattr(k, "col", 0)
                                col = max(0, col - 1) if col else 0
                                self._add_diag(k.line if hasattr(k, "line") else body.line, col,
                                               "Type error: expected %s, got %s" % (key_type, ak), 1)
                            if av not in ("unknown", "any") and not self._compatible(av, val_type):
                                col = getattr(v, "col", 0)
                                col = max(0, col - 1) if col else 0
                                self._add_diag(v.line if hasattr(v, "line") else body.line, col,
                                               "Type error: expected %s, got %s" % (val_type, av), 1)
                elif actual != "unknown" and actual != "any" and not self._compatible(actual, expected_type):
                    col = 0
                    if hasattr(body.value, "col"):
                        col = max(0, body.value.col - 1)
                    self._add_diag(body.line, col,
                                   "Type error: expected %s, got %s" % (expected_type, actual), 1)
            return
        if isinstance(body, IfStmt):
            self._check_returns(body.then_branch, scope, expected_type)
            if body.else_branch is not None:
                self._check_returns(body.else_branch, scope, expected_type)
        if isinstance(body, MatchStmt):
            for pat, guard, b in body.cases:
                self._check_returns(b, scope, expected_type)
        if isinstance(body, WhileStmt):
            self._check_returns(body.body, scope, expected_type)
        if isinstance(body, ForStmt):
            self._check_returns(body.body, scope, expected_type)
        if isinstance(body, TryStmt):
            self._check_returns(body.try_block, scope, expected_type)
            if body.catch_block is not None:
                self._check_returns(body.catch_block, scope, expected_type)
            if body.finally_block is not None:
                self._check_returns(body.finally_block, scope, expected_type)
        if isinstance(body, Block):
            for s in body.statements:
                self._check_returns(s, scope, expected_type)

    def _infer_type(self, expr, scope):
        if expr is None:
            return "unknown"
        if isinstance(expr, Literal):
            v = expr.value
            if v is None:
                return "nil"
            if isinstance(v, bool):
                return "bool"
            if isinstance(v, int):
                return "int"
            if isinstance(v, float):
                return "float"
            if isinstance(v, str):
                return "string"
            return "unknown"
        if isinstance(expr, Identifier):
            if expr.name in ("true", "false"):
                return "bool"
            if expr.name == "nil":
                return "nil"
            if expr.name == "super":
                t = scope.lookup_type("super")
                if t is not None:
                    return t
                return "unknown"
            t = scope.lookup_type(expr.name)
            if t is not None:
                return t
            if expr.name in ("print", "println", "input", "len", "type", "str",
                             "int", "float", "bool", "range", "abs", "min", "max",
                             "sum", "sorted", "reversed", "enumerate", "zip",
                             "keys", "values"):
                return "function"
            if expr.name in ("math", "random", "time", "json", "os", "fs", "re",
                             "http", "collections"):
                return "dict"
            return "unknown"
        if isinstance(expr, InterpolatedString):
            return "string"
        if isinstance(expr, UnaryOp):
            if expr.op in ("-", "+"):
                return self._infer_type(expr.operand, scope)
            if expr.op in ("!", "not", "~"):
                return "bool"
            return "unknown"
        if isinstance(expr, BinaryOp):
            lt = self._infer_type(expr.left, scope)
            rt = self._infer_type(expr.right, scope)
            op = expr.op
            if op == "+":
                if lt == "string" or rt == "string":
                    return "string"
                if lt == "int" and rt == "int":
                    return "int"
                if lt in ("int", "float") and rt in ("int", "float"):
                    return "float"
                if lt.startswith("list") and rt.startswith("list"):
                    return lt if lt == rt else "list"
                return "unknown"
            if op in ("-", "*", "/", "%", "**"):
                if lt == "int" and rt == "int" and op != "/":
                    return "int"
                if lt in ("int", "float") and rt in ("int", "float"):
                    return "float"
                return "unknown"
            if op in ("==", "!=", "<", ">", "<=", ">=", "is", "in"):
                return "bool"
            if op in ("and", "or", "&&", "||"):
                return rt if lt not in ("unknown", "any") else lt
            return "unknown"
        if isinstance(expr, Ternary):
            t = self._infer_type(expr.then_expr, scope)
            e = self._infer_type(expr.else_expr, scope)
            if t == e:
                return t
            return "unknown"
        if isinstance(expr, ListLiteral):
            if not expr.elements:
                return "list"
            elem_types = [self._infer_type(e, scope) for e in expr.elements]
            if len(set(elem_types)) == 1 and elem_types[0] not in ("unknown",):
                return "list[" + elem_types[0] + "]"
            # Mixed types: return unparameterized "list" (do not guess from first element)
            return "list"
        if isinstance(expr, DictLiteral):
            if not expr.pairs:
                return "dict"
            key_types = [self._infer_type(k, scope) for k, _ in expr.pairs]
            val_types = [self._infer_type(v, scope) for _, v in expr.pairs]
            # Only parameterize if ALL keys have the same type and ALL values have the same type
            if (key_types and len(set(key_types)) == 1 and key_types[0] not in ("unknown",)
                    and val_types and len(set(val_types)) == 1 and val_types[0] not in ("unknown",)):
                return "dict[" + key_types[0] + ", " + val_types[0] + "]"
            return "dict"
        if isinstance(expr, ListComp):
            return "list"
        if isinstance(expr, DictComp):
            return "dict"
        if isinstance(expr, Slice):
            obj_type = self._infer_type(expr.obj, scope)
            if obj_type.startswith("string"):
                return "string"
            if obj_type.startswith("list"):
                return obj_type
            return "list"
        if isinstance(expr, Index):
            obj_type = self._infer_type(expr.obj, scope)
            parsed = parse_type(obj_type)
            if parsed[0] == "list" and parsed[1]:
                return parsed[1][0]
            if parsed[0] == "dict" and len(parsed[1]) >= 2:
                return parsed[1][1]
            if parsed[0] == "string":
                return "string"
            if parsed[0] == "list":
                return "unknown"
            if parsed[0] == "dict":
                return "unknown"
            return "unknown"
        if isinstance(expr, NewExpr):
            if expr.class_name in self.class_types:
                cls_info = self.class_types[expr.class_name]
                if "init" in cls_info["methods"]:
                    params, ret = cls_info["methods"]["init"]
                    for i, arg in enumerate(expr.args):
                        if i < len(params):
                            expected = params[i][1]
                            if expected and expected not in ("unknown", "any"):
                                actual = self._infer_type(arg, scope)
                                exp_base = expected.split("[")[0].strip()
                                act_base = actual.split("[")[0].strip() if actual else ""
                                if (actual not in ("unknown", "any")
                                        and exp_base != act_base
                                        and not self._compatible(actual, expected)):
                                    col = 0
                                    if hasattr(arg, "col"):
                                        col = max(0, arg.col - 1)
                                    self._add_diag(arg.line if hasattr(arg, "line") else expr.line, col,
                                                   "Type error: expected %s, got %s" % (expected, actual), 1)
                                self._check_collection_elements(arg, expected, scope, getattr(arg, "line", expr.line))
                return expr.class_name
            return "unknown"
        if isinstance(expr, Call):
            for arg in expr.args:
                self._infer_type(arg, scope)
            for _, v in expr.kwargs:
                self._infer_type(v, scope)
            callee_type = self._infer_type(expr.callee, scope)
            if isinstance(expr.callee, Identifier):
                name = expr.callee.name
                if name in self.fn_types:
                    params, ret = self.fn_types[name]
                    if len(expr.args) > len(params):
                        if not (params and len(params[-1]) > 2 and params[-1][2]):
                            col = getattr(expr.callee, "col", 0)
                            col = max(0, col - 1) if col else 0
                            self._add_diag(expr.line, col,
                                           "Too many arguments to '%s'" % name, 1)
                    for i, arg in enumerate(expr.args):
                        if i < len(params):
                            expected = params[i][1]
                            if expected and expected not in ("unknown", "any"):
                                actual = self._infer_type(arg, scope)
                                exp_base = expected.split("[")[0].strip()
                                act_base = actual.split("[")[0].strip() if actual else ""
                                if (actual not in ("unknown", "any")
                                        and exp_base != act_base
                                        and not self._compatible(actual, expected)):
                                    col = 0
                                    if hasattr(arg, "col"):
                                        col = max(0, arg.col - 1)
                                    self._add_diag(arg.line if hasattr(arg, "line") else expr.line, col,
                                                   "Type error: expected %s, got %s" % (expected, actual), 1)
                                self._check_collection_elements(arg, expected, scope, getattr(arg, "line", expr.line))
                    return ret if ret and ret != "unknown" else "unknown"
            if isinstance(expr.callee, Member):
                obj_type = self._infer_type(expr.callee.obj, scope)
                method_name = expr.callee.name
                if obj_type in self.class_types:
                    cls_info = self.class_types[obj_type]
                    if method_name in cls_info["methods"]:
                        params, ret = cls_info["methods"][method_name]
                        for i, arg in enumerate(expr.args):
                            if i < len(params):
                                expected = params[i][1]
                                if expected and expected not in ("unknown", "any"):
                                    actual = self._infer_type(arg, scope)
                                    exp_base = expected.split("[")[0].strip()
                                    act_base = actual.split("[")[0].strip() if actual else ""
                                    if (actual not in ("unknown", "any")
                                            and exp_base != act_base
                                            and not self._compatible(actual, expected)):
                                        col = 0
                                        if hasattr(arg, "col"):
                                            col = max(0, arg.col - 1)
                                        self._add_diag(arg.line if hasattr(arg, "line") else expr.line, col,
                                                       "Type error: expected %s, got %s" % (expected, actual), 1)
                                    self._check_collection_elements(arg, expected, scope, getattr(arg, "line", expr.line))
                        return ret if ret and ret != "unknown" else "unknown"
            return "unknown"
        if isinstance(expr, Member):
            obj_type = self._infer_type(expr.obj, scope)
            name = expr.name
            if obj_type in self.class_types:
                cls_info = self.class_types[obj_type]
                if name in cls_info["methods"]:
                    params, ret = cls_info["methods"][name]
                    return ret if ret and ret != "unknown" else "unknown"
                if name in cls_info["fields"]:
                    return cls_info["fields"][name]
            if obj_type == "dict" and isinstance(expr.obj, Identifier) and expr.obj.name in ("math", "random", "time", "json", "os", "fs", "re", "http", "collections"):
                return "any"
            return "unknown"
        if isinstance(expr, FunctionExpr):
            return "function"
        if isinstance(expr, Lambda):
            return "function"
        if isinstance(expr, Spread):
            return self._infer_type(expr.value, scope)
        if isinstance(expr, Assign):
            target_type = self._infer_type(expr.target, scope)
            val_type = self._infer_type(expr.value, scope)
            if isinstance(expr.target, Index):
                obj_type = self._infer_type(expr.target.obj, scope)
                parsed = parse_type(obj_type)
                if parsed[0] == "list" and parsed[1]:
                    elem_type = parsed[1][0]
                    if val_type not in ("unknown", "any") and not self._compatible(val_type, elem_type):
                        col = 0
                        if hasattr(expr.value, "col"):
                            col = max(0, expr.value.col - 1)
                        self._add_diag(expr.line, col,
                                       "Type error: expected %s, got %s" % (elem_type, val_type), 1)
                elif parsed[0] == "dict" and len(parsed[1]) >= 2:
                    val_elem_type = parsed[1][1]
                    if val_type not in ("unknown", "any") and not self._compatible(val_type, val_elem_type):
                        col = 0
                        if hasattr(expr.value, "col"):
                            col = max(0, expr.value.col - 1)
                        self._add_diag(expr.line, col,
                                       "Type error: expected %s, got %s" % (val_elem_type, val_type), 1)
            elif target_type not in ("unknown", "any") and val_type not in ("unknown", "any"):
                if not self._compatible(val_type, target_type):
                    col = 0
                    if hasattr(expr.value, "col"):
                        col = max(0, expr.value.col - 1)
                    self._add_diag(expr.line, col,
                                   "Type error: expected %s, got %s" % (target_type, val_type), 1)
            return val_type
        if isinstance(expr, Ternary):
            t = self._infer_type(expr.then_expr, scope)
            e = self._infer_type(expr.else_expr, scope)
            if t == e:
                return t
            return "unknown"
        return "unknown"

    def _compatible(self, source, target):
        src = parse_type(source) if isinstance(source, str) else source
        tgt = parse_type(target) if isinstance(target, str) else target
        if isinstance(src, tuple):
            src_name, src_args = src
        else:
            src_name, src_args = src.name, src.args
        if isinstance(tgt, tuple):
            tgt_name, tgt_args = tgt
        else:
            tgt_name, tgt_args = tgt.name, tgt.args
        if src_name in ("any", "unknown") or tgt_name in ("any", "unknown"):
            return True
        if src_name != tgt_name:
            if src_name == "int" and tgt_name == "float":
                return True
            if src_name == "bool" and tgt_name == "int":
                return True
            return False
        if not src_args or not tgt_args:
            return True
        if len(src_args) != len(tgt_args):
            return False
        return all(self._compatible(s, t) for s, t in zip(src_args, tgt_args))

    def _check_collection_elements(self, value_expr, expected_type, scope, line):
        if not expected_type or not isinstance(value_expr, (ListLiteral, DictLiteral)):
            return
        expected_type = expected_type.strip()
        if expected_type.startswith("list[") and isinstance(value_expr, ListLiteral):
            inner = expected_type[len("list["):-1].strip()
            elem_type = inner
            for elem in value_expr.elements:
                actual = self._infer_type(elem, scope)
                # Only report top-level mismatch if base types differ
                elem_base = elem_type.split("[")[0].strip() if elem_type else ""
                actual_base = actual.split("[")[0].strip() if actual else ""
                if (actual not in ("unknown", "any")
                        and elem_base != actual_base
                        and not self._compatible(actual, elem_type)):
                    col = getattr(elem, "col", 0)
                    col = max(0, col - 1) if col else 0
                    self._add_diag(elem.line if hasattr(elem, "line") else line, col,
                                   "Type error: expected %s, got %s" % (elem_type, actual), 1)
                self._check_collection_elements(elem, elem_type, scope, getattr(elem, "line", line))
        elif expected_type.startswith("dict[") and isinstance(value_expr, DictLiteral):
            inner = expected_type[len("dict["):-1].strip()
            parts = []
            depth = 0
            current = ""
            for ch in inner:
                if ch == "[":
                    depth += 1
                    current += ch
                elif ch == "]":
                    depth -= 1
                    current += ch
                elif ch == "," and depth == 0:
                    parts.append(current.strip())
                    current = ""
                else:
                    current += ch
            if current.strip():
                parts.append(current.strip())
            if len(parts) >= 2:
                key_type = parts[0]
                val_type = parts[1]
                for k, v in value_expr.pairs:
                    ak = self._infer_type(k, scope)
                    av = self._infer_type(v, scope)
                    ak_base = key_type.split("[")[0].strip() if key_type else ""
                    actual_ak_base = ak.split("[")[0].strip() if ak else ""
                    if (ak not in ("unknown", "any")
                            and ak_base != actual_ak_base
                            and not self._compatible(ak, key_type)):
                        col = getattr(k, "col", 0)
                        col = max(0, col - 1) if col else 0
                        self._add_diag(k.line if hasattr(k, "line") else line, col,
                                       "Type error: expected %s, got %s" % (key_type, ak), 1)
                    av_base = val_type.split("[")[0].strip() if val_type else ""
                    actual_av_base = av.split("[")[0].strip() if av else ""
                    if (av not in ("unknown", "any")
                            and av_base != actual_av_base
                            and not self._compatible(av, val_type)):
                        col = getattr(v, "col", 0)
                        col = max(0, col - 1) if col else 0
                        self._add_diag(v.line if hasattr(v, "line") else line, col,
                                       "Type error: expected %s, got %s" % (val_type, av), 1)
                    self._check_collection_elements(k, key_type, scope, getattr(k, "line", line))
                    self._check_collection_elements(v, val_type, scope, getattr(v, "line", line))

    def _col_of(self, line_no, name):
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

    def _has_rest(self, params):
        if not params:
            return False
        last = params[-1]
        return isinstance(last, tuple) and len(last) > 2 and last[2]

def type_check(text):
    program = parse(text)
    checker = TypeChecker(text)
    return checker.check(program)