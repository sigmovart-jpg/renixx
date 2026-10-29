"""Tree-walking interpreter for Renixx."""
import os
import sys
import time
import math
import random
import json as _json
from .ast import *
from .errors import (
    RenixxError, RuntimeError as RTError, ReturnValue, BreakSignal,
    ContinueSignal, ThrowSignal,
)
from .environment import Environment

class RenixxFunction:
    def __init__(self, decl, closure_env, interpreter):
        self.decl = decl
        self.closure = closure_env
        self.interp = interpreter
        self.name = decl.name

    def __call__(self, *args, **kwargs):
        return self.interp.call_function(self, list(args), kwargs)

    def __repr__(self):
        return "<fn %s>" % (self.name or "anonymous")

class RenixxLambda:
    def __init__(self, node, closure_env, interpreter):
        self.node = node
        self.closure = closure_env
        self.interp = interpreter
    def __call__(self, *args, **kwargs):
        return self.interp.call_lambda(self, list(args), kwargs)
    def __repr__(self):
        return "<lambda>"

class RenixxClass:
    def __init__(self, decl, env, interpreter):
        self.decl = decl
        self.env = env
        self.interp = interpreter
        self.name = decl.name
        self.superclass = None
        if decl.superclass:
            self.superclass = interpreter.globals_env.get(decl.superclass) if interpreter.globals_env.has(decl.superclass) else None
    def __repr__(self):
        return "<class %s>" % self.name

class RenixxInstance:
    def __init__(self, cls):
        self.cls = cls
        self.fields = {}
    def get(self, name):
        if name in self.fields:
            return self.fields[name]
        # method
        for m in self.cls.decl.methods:
            if m.name == name:
                return RenixxBoundMethod(m, self)
        if self.cls.superclass is not None and isinstance(self.cls.superclass, RenixxClass):
            return self.cls.superclass_instance_get(name, self) if hasattr(self.cls.superclass,'superclass_instance_get') else None
        return None
    def set(self, name, value):
        self.fields[name] = value
    def __repr__(self):
        return "<%s instance>" % self.cls.name

class RenixxSuper:
    def __init__(self, instance, defining_class):
        self.instance = instance
        self.defining_class = defining_class
    def __repr__(self):
        return "<super of %s>" % self.defining_class.name

class RenixxBoundMethod:
    def __init__(self, method_decl, instance):
        self.method_decl = method_decl
        self.instance = instance
    def __call__(self, *args, **kwargs):
        # build function
        fn = RenixxFunction(self.method_decl, self.instance.fields and None or None, None)
        # handle via interpreter
        return None

class Interpreter:
    def __init__(self):
        self.globals_env = Environment()
        self.current_env = self.globals_env
        self.output = []
        self.call_stack = []
        self._setup_builtins()

    def _setup_builtins(self):
        env = self.globals_env
        # core functions
        env.define("print", self._builtin_print, False)
        env.define("println", self._builtin_print, False)
        env.define("input", self._builtin_input, False)
        env.define("len", lambda x: self._len(x), False)
        env.define("type", lambda x: self._type(x), False)
        env.define("str", lambda x: self._str(x), False)
        env.define("int", lambda x: self._int(x), False)
        env.define("float", lambda x: self._float(x), False)
        env.define("bool", lambda x: bool(self._truthy(x)), False)
        env.define("range", self._builtin_range, False)
        env.define("abs", lambda x: abs(x), False)
        env.define("min", lambda *a: min(a) if len(a)>1 else min(a[0]), False)
        env.define("max", lambda *a: max(a) if len(a)>1 else max(a[0]), False)
        env.define("sum", lambda x: sum(x), False)
        env.define("sorted", lambda x: sorted(x), False)
        env.define("reversed", lambda x: list(reversed(x)), False)
        env.define("enumerate", self._builtin_enumerate, False)
        env.define("zip", self._builtin_zip, False)
        env.define("keys", lambda d: list(d.keys()), False)
        env.define("values", lambda d: list(d.values()), False)
        env.define("append", None, False)  # placeholder, method style
        env.define("push", None, False)
        # modules as objects (dicts)
        env.define("math", self._make_math_module(), False)
        env.define("random", self._make_random_module(), False)
        env.define("time", self._make_time_module(), False)
        env.define("json", self._make_json_module(), False)
        env.define("os", self._make_os_module(), False)
        env.define("fs", self._make_fs_module(), False)
        env.define("re", self._make_re_module(), False)
        env.define("http", self._make_http_module(), False)
        env.define("collections", self._make_collections_module(), False)
        # constants
        env.define("true", True, False)
        env.define("false", False, False)
        env.define("nil", None, False)
        # Note: true/false/nil keywords handled separately; but keep

    def _truthy(self, v):
        if v is None:
            return False
        if isinstance(v, bool):
            return v
        if isinstance(v, (int, float)):
            return v != 0
        if isinstance(v, str):
            return len(v) > 0
        if isinstance(v, (list, dict)):
            return len(v) > 0
        return True

    def _len(self, x):
        if isinstance(x, (str, list, dict)):
            return len(x)
        raise RTError("len() not supported for %s" % type(x).__name__)

    def _type(self, x):
        if x is None: return "nil"
        if isinstance(x, bool): return "bool"
        if isinstance(x, int): return "int"
        if isinstance(x, float): return "float"
        if isinstance(x, str): return "string"
        if isinstance(x, list): return "list"
        if isinstance(x, dict): return "dict"
        if isinstance(x, RenixxFunction): return "function"
        if isinstance(x, RenixxLambda): return "function"
        if isinstance(x, RenixxBoundMethod): return "function"
        if isinstance(x, RenixxSuper): return "super"
        if isinstance(x, RenixxClass): return "class"
        if isinstance(x, RenixxInstance): return "instance"
        if callable(x): return "function"
        return "unknown"

    def _str(self, x):
        return self.to_string(x)

    def to_string(self, x):
        if x is None:
            return "nil"
        if isinstance(x, bool):
            return "true" if x else "false"
        if isinstance(x, float):
            if x == int(x) and abs(x) < 1e15:
                return repr(x)
            return repr(x)
        if isinstance(x, list):
            return "[" + ", ".join(self.to_string(e) for e in x) + "]"
        if isinstance(x, dict):
            parts = []
            for k, v in x.items():
                parts.append(self.to_string(k) + ": " + self.to_string(v))
            return "{" + ", ".join(parts) + "}"
        if isinstance(x, RenixxInstance):
            return "<%s instance>" % x.cls.name
        return str(x)

    def _pos(self, node):
        """Best-effort (line, col) for a node, looking into children for a column."""
        line = getattr(node, "line", 0) or 0
        col = getattr(node, "col", 0) or 0
        if col:
            return line, col
        for attr in ("callee", "left", "obj", "value", "target", "index", "operand"):
            child = getattr(node, attr, None)
            if isinstance(child, Node):
                child_line, child_col = self._pos(child)
                if child_col:
                    return line or child_line, child_col
        return line, col

    def _bad_operands(self, op, l, r, line, col):
        return RTError(
            "Unsupported operand types for %s: %s and %s"
            % (op, type(l).__name__, type(r).__name__),
            line, col,
        )

    def _int(self, x):
        if isinstance(x, bool):
            return 1 if x else 0
        if isinstance(x, (int, float)):
            return int(x)
        if isinstance(x, str):
            try:
                return int(x)
            except ValueError:
                try:
                    return int(float(x))
                except ValueError:
                    raise RTError("Cannot convert %r to int" % x)
        raise RTError("Cannot convert to int")

    def _float(self, x):
        if isinstance(x, bool):
            return 1.0 if x else 0.0
        if isinstance(x, (int, float)):
            return float(x)
        if isinstance(x, str):
            try:
                return float(x)
            except ValueError:
                raise RTError("Cannot convert %r to float" % x)
        raise RTError("Cannot convert to float")

    def _builtin_print(self, *args):
        s = " ".join(self.to_string(a) for a in args)
        self.output.append(s)
        try:
            print(s)
        except Exception:
            pass
        return None

    def _builtin_input(self, prompt=""):
        try:
            return input(self.to_string(prompt))
        except EOFError:
            return ""

    def _builtin_range(self, *args):
        # range(stop) or range(start, stop) or range(start, stop, step)
        if len(args) == 1:
            start, stop, step = 0, args[0], 1
        elif len(args) == 2:
            start, stop, step = args[0], args[1], 1
        elif len(args) == 3:
            start, stop, step = args[0], args[1], args[2]
        else:
            raise RTError("range() expects 1-3 arguments")
        start = self._int(start); stop = self._int(stop); step = self._int(step)
        if step == 0:
            raise RTError("range() step cannot be 0")
        res = []
        if step > 0:
            i = start
            while i < stop:
                res.append(i)
                i += step
        else:
            i = start
            while i > stop:
                res.append(i)
                i += step
        return res

    def _builtin_enumerate(self, iterable):
        return [[i, v] for i, v in enumerate(iterable)]

    def _builtin_zip(self, *iterables):
        return [list(t) for t in zip(*iterables)]

    def _make_math_module(self):
        m = {}
        m["pi"] = math.pi
        m["e"] = math.e
        m["sqrt"] = lambda x: math.sqrt(x)
        m["pow"] = lambda a, b: a ** b
        m["floor"] = lambda x: math.floor(x)
        m["ceil"] = lambda x: math.ceil(x)
        m["round"] = lambda x, n=0: round(x, n)
        m["abs"] = lambda x: abs(x)
        m["sin"] = math.sin
        m["cos"] = math.cos
        m["tan"] = math.tan
        m["log"] = lambda x, base=None: math.log(x) if base is None else math.log(x, base)
        m["exp"] = math.exp
        m["min"] = lambda *a: min(a) if len(a) > 1 else min(a[0])
        m["max"] = lambda *a: max(a) if len(a) > 1 else max(a[0])
        m["gcd"] = math.gcd
        m["factorial"] = math.factorial
        return m

    def _make_random_module(self):
        m = {}
        m["random"] = random.random
        m["randint"] = random.randint
        m["choice"] = random.choice
        m["shuffle"] = lambda lst: (random.shuffle(lst), lst)[1]
        m["seed"] = random.seed
        return m

    def _make_time_module(self):
        m = {}
        m["now"] = lambda: time.time()
        m["sleep"] = lambda s: time.sleep(s)
        m["format"] = lambda t=None, fmt="%Y-%m-%d %H:%M:%S": time.strftime(fmt, time.localtime() if t is None else time.localtime(t))
        return m

    def _make_json_module(self):
        m = {}
        m["parse"] = lambda s: _json.loads(s)
        m["stringify"] = lambda o, indent=None: _json.dumps(o, indent=indent, default=self.to_string)
        return m

    def _make_os_module(self):
        m = {}
        m["env"] = lambda name, default=None: os.environ.get(name, default)
        m["args"] = lambda: list(sys.argv)
        m["cwd"] = lambda: os.getcwd()
        m["platform"] = sys.platform
        m["exit"] = lambda code=0: sys.exit(code)
        return m

    def _make_fs_module(self):
        m = {}
        m["read_file"] = lambda p: open(p, "r", encoding="utf-8").read()
        m["write_file"] = lambda p, c: (open(p, "w", encoding="utf-8").write(self.to_string(c) if not isinstance(c, str) else c), None)[1]
        m["append_file"] = lambda p, c: (open(p, "a", encoding="utf-8").write(self.to_string(c) if not isinstance(c, str) else c), None)[1]
        m["exists"] = lambda p: os.path.exists(p)
        m["list_dir"] = lambda p=".": os.listdir(p)
        m["mkdir"] = lambda p: (os.makedirs(p, exist_ok=True), None)[1]
        m["remove"] = lambda p: (os.remove(p), None)[1]
        m["is_file"] = lambda p: os.path.isfile(p)
        m["is_dir"] = lambda p: os.path.isdir(p)
        return m

    def _make_re_module(self):
        import re as _re
        m = {}
        m["match"] = lambda pat, s: _re.match(pat, s)
        m["search"] = lambda pat, s: _re.search(pat, s)
        m["findall"] = lambda pat, s: _re.findall(pat, s)
        m["sub"] = lambda pat, repl, s: _re.sub(pat, repl, s)
        m["split"] = lambda pat, s: _re.split(pat, s)
        return m

    def _make_http_module(self):
        import urllib.request as _u
        m = {}
        def get(url, headers=None):
            req = _u.Request(url, headers=headers or {})
            with _u.urlopen(req) as r:
                return r.read().decode("utf-8", "replace")
        m["get"] = get
        m["post"] = lambda url, data="", headers=None: None
        return m

    def _make_collections_module(self):
        from collections import Counter, defaultdict
        m = {}
        m["Counter"] = lambda iterable=None: dict(Counter(iterable)) if iterable is not None else {}
        m["defaultdict"] = lambda factory=None: {}
        return m

    def _type_name(self, v):
        if v is None: return "nil"
        if isinstance(v, bool): return "bool"
        if isinstance(v, int): return "int"
        if isinstance(v, float): return "float"
        if isinstance(v, str): return "string"
        if isinstance(v, list): return "list"
        if isinstance(v, dict): return "dict"
        return type(v).__name__

    def _check_type(self, value, annot):
        if annot is None:
            return
        annot = str(annot).strip()
        if annot in ("any", "unknown"):
            return
        # Extract base type name (before '[')
        base = annot.split("[")[0].strip()
        actual = self._type_name(value)
        # nil handling
        if value is None:
            if base == "nil":
                return
            raise RTError("Type error: expected %s, got nil" % annot)
        if base != actual:
            # allow int -> float coercion
            if base == "float" and actual == "int":
                pass
            else:
                raise RTError("Type error: expected %s, got %s" % (annot, actual))
        # Check container element types
        if base == "list" and isinstance(value, list):
            # Parse element type from annot: list[X] or list[X, ...]
            elem_annot = None
            if "[" in annot:
                inner = annot[annot.find("[")+1:annot.rfind("]")]
                # split top-level by comma
                depth = 0
                parts = []
                cur = ""
                for ch in inner:
                    if ch == "[":
                        depth += 1
                        cur += ch
                    elif ch == "]":
                        depth -= 1
                        cur += ch
                    elif ch == "," and depth == 0:
                        parts.append(cur.strip())
                        cur = ""
                    else:
                        cur += ch
                if cur.strip():
                    parts.append(cur.strip())
                if parts:
                    elem_annot = parts[0]
            if elem_annot is not None:
                for elem in value:
                    self._check_type(elem, elem_annot)
        elif base == "dict" and isinstance(value, dict):
            key_annot = None
            val_annot = None
            if "[" in annot:
                inner = annot[annot.find("[")+1:annot.rfind("]")]
                depth = 0
                parts = []
                cur = ""
                for ch in inner:
                    if ch == "[":
                        depth += 1
                        cur += ch
                    elif ch == "]":
                        depth -= 1
                        cur += ch
                    elif ch == "," and depth == 0:
                        parts.append(cur.strip())
                        cur = ""
                    else:
                        cur += ch
                if cur.strip():
                    parts.append(cur.strip())
                if len(parts) >= 2:
                    key_annot = parts[0]
                    val_annot = parts[1]
                elif len(parts) == 1:
                    val_annot = parts[0]
            if key_annot is not None:
                for k in value:
                    self._check_type(k, key_annot)
            if val_annot is not None:
                for v in value.values():
                    self._check_type(v, val_annot)

    def _bind_one(self, env, name, value, annot):
        self._check_type(value, annot)
        env.define(name, value, mutable=True)

    # ---- execution ----
    def run(self, program, env=None):
        if env is None:
            env = self.globals_env
        self.current_env = env
        from .errors import set_current_stack
        set_current_stack(self.call_stack)
        try:
            for stmt in program.statements:
                self.exec_stmt(stmt, env)
        except ReturnValue as sig:
            raise RTError("'return' outside function", getattr(sig, "line", 0))
        except BreakSignal as sig:
            raise RTError("'break' outside loop", getattr(sig, "line", 0))
        except ContinueSignal as sig:
            raise RTError("'continue' outside loop", getattr(sig, "line", 0))
        return None

    def exec_stmt(self, stmt, env):
        if isinstance(stmt, Block):
            new_env = Environment(env)
            for s in stmt.statements:
                self.exec_stmt(s, new_env)
            return
        if isinstance(stmt, LetStmt):
            val = None
            if stmt.value is not None:
                val = self.eval_expr(stmt.value, env)
            if getattr(stmt, "type_annot", None):
                self._check_type(val, stmt.type_annot)
            env.define(stmt.name, val, mutable=stmt.mutable)
            return
        if isinstance(stmt, DestructureStmt):
            val = self.eval_expr(stmt.value, env)
            if stmt.kind == "list":
                for i, name in enumerate(stmt.names):
                    v = val[i] if i < len(val) else None
                    env.define(name, v, mutable=stmt.mutable)
            else:
                for name in stmt.names:
                    v = val.get(name) if isinstance(val, dict) else None
                    env.define(name, v, mutable=stmt.mutable)
            return
        if isinstance(stmt, ExprStmt):
            self.eval_expr(stmt.expr, env)
            return
        if isinstance(stmt, FnDecl):
            fn = RenixxFunction(stmt, env, self)
            env.define(stmt.name, fn, mutable=True)
            return
        if isinstance(stmt, ClassDecl):
            cls = RenixxClass(stmt, env, self)
            env.define(stmt.name, cls, mutable=True)
            return
        if isinstance(stmt, IfStmt):
            cond = self.eval_expr(stmt.cond, env)
            if self._truthy(cond):
                self.exec_stmt(stmt.then_branch, env)
            elif stmt.else_branch is not None:
                self.exec_stmt(stmt.else_branch, env)
            return
        if isinstance(stmt, WhileStmt):
            while True:
                cond = self.eval_expr(stmt.cond, env)
                if not self._truthy(cond):
                    break
                try:
                    self.exec_stmt(stmt.body, env)
                except BreakSignal:
                    break
                except ContinueSignal:
                    continue
            return
        if isinstance(stmt, ForStmt):
            if stmt.var is not None and stmt.iterable is not None:
                iterable = self.eval_expr(stmt.iterable, env)
                for item in iterable:
                    new_env = Environment(env)
                    new_env.define(stmt.var, item, mutable=True)
                    try:
                        self.exec_stmt(stmt.body, new_env)
                    except BreakSignal:
                        break
                    except ContinueSignal:
                        continue
                return
            # C-style
            loop_env = Environment(env)
            if stmt.init is not None:
                self.exec_stmt(stmt.init, loop_env)
            while True:
                if stmt.cond is not None:
                    c = self.eval_expr(stmt.cond, loop_env)
                    if not self._truthy(c):
                        break
                try:
                    self.exec_stmt(stmt.body, loop_env)
                except BreakSignal:
                    break
                except ContinueSignal:
                    pass
                if stmt.step is not None:
                    self.eval_expr(stmt.step, loop_env)
            return
        if isinstance(stmt, MatchStmt):
            val = self.eval_expr(stmt.expr, env)
            matched = False
            for pat, guard, body in stmt.cases:
                if pat is None:
                    # default
                    case_env = Environment(env)
                    if guard is None or self._truthy(self.eval_expr(guard, case_env)):
                        self._exec_match_body(body, case_env)
                        matched = True
                        break
                    continue
                # pattern matching
                case_env = Environment(env)
                if self._match_pattern(pat, val, case_env):
                    if guard is not None and not self._truthy(self.eval_expr(guard, case_env)):
                        continue
                    self._exec_match_body(body, case_env)
                    matched = True
                    break
            return
        if isinstance(stmt, TryStmt):
            try:
                self.exec_stmt(stmt.try_block, env)
            except (ReturnValue, BreakSignal, ContinueSignal):
                # Control-flow signals are not errors: let them reach the
                # enclosing function/loop instead of swallowing them here.
                raise
            except ThrowSignal as thrown:
                if stmt.catch_block is None:
                    raise
                new_env = Environment(env)
                if stmt.catch_var:
                    # `catch e` receives exactly the thrown value.
                    new_env.define(stmt.catch_var, thrown.value, mutable=True)
                self.exec_stmt(stmt.catch_block, new_env)
            except RenixxError as error:
                if stmt.catch_block is None:
                    raise
                new_env = Environment(env)
                if stmt.catch_var:
                    # Runtime errors are caught as their message string.
                    new_env.define(stmt.catch_var, error.message, mutable=True)
                self.exec_stmt(stmt.catch_block, new_env)
            finally:
                if stmt.finally_block is not None:
                    self.exec_stmt(stmt.finally_block, env)
            return
        if isinstance(stmt, ReturnStmt):
            v = None
            if stmt.value is not None:
                v = self.eval_expr(stmt.value, env)
            signal = ReturnValue(v)
            signal.line = stmt.line
            raise signal
        if isinstance(stmt, ThrowStmt):
            v = self.eval_expr(stmt.value, env)
            line, col = self._pos(stmt)
            raise ThrowSignal(v, line, col)
        if isinstance(stmt, BreakStmt):
            signal = BreakSignal()
            signal.line = stmt.line
            raise signal
        if isinstance(stmt, ContinueStmt):
            signal = ContinueSignal()
            signal.line = stmt.line
            raise signal
        if isinstance(stmt, ImportStmt):
            self.exec_import(stmt, env)
            return
        raise RTError("Unknown statement type: %s" % type(stmt).__name__)

    def _exec_match_body(self, body, env):
        if isinstance(body, Block):
            self.exec_stmt(body, env)
        else:
            self.exec_stmt(body, env)

    def _match_pattern(self, pat, val, env):
        # pat is an Expr (Literal, Identifier, etc.)
        if isinstance(pat, Literal):
            return pat.value == val
        if isinstance(pat, ListLiteral):
            if not isinstance(val, (list, tuple)):
                return False
            if len(pat.elements) != len(val):
                return False
            for pe, ve in zip(pat.elements, val):
                if not self._match_pattern(pe, ve, env):
                    return False
            return True

        if isinstance(pat, Identifier):
            if pat.name == "_":
                # wildcard: always matches, no binding
                return True
            # binding pattern: bind val to name in env
            if env.has(pat.name):
                try:
                    return env.get(pat.name) == val
                except Exception:
                    pass
            env.define(pat.name, val, mutable=True)
            return True
        if isinstance(pat, BinaryOp) and pat.op == "|":
            # not parsed; skip
            return False
        # range? 
        return False

    def eval_expr(self, expr, env):
        if isinstance(expr, Literal):
            return expr.value
        if isinstance(expr, InterpolatedString):
            out = ""
            for kind, data in expr.parts:
                if kind == "text":
                    out += data
                else:
                    out += self.to_string(self.eval_expr(data, env))
            return out
        if isinstance(expr, Identifier):
            name = expr.name
            if name == "this":
                # find 'this' in env
                if env.has("this"):
                    return env.get("this")
                raise RTError("this used outside class", expr.line)
            if name == "super":
                if env.has("super"):
                    return env.get("super")
                raise RTError("super used outside class or class has no superclass", expr.line)
            if env.has(name):
                return env.get(name)
            # globals builtins already in globals_env
            if self.globals_env.has(name):
                return self.globals_env.get(name)
            raise RTError("Undefined variable '%s'" % name, expr.line)
        if isinstance(expr, UnaryOp):
            v = self.eval_expr(expr.operand, env)
            line, col = self._pos(expr)
            if expr.op in ("-", "+"):
                try:
                    return -v if expr.op == "-" else +v
                except TypeError:
                    raise RTError(
                        "Unsupported operand type for %s: %s"
                        % (expr.op, type(v).__name__),
                        line, col,
                    )
            if expr.op in ("!", "not"):
                return not self._truthy(v)
            if expr.op == "~":
                try:
                    return ~int(v)
                except (TypeError, ValueError):
                    raise RTError(
                        "Unsupported operand type for ~: %s" % type(v).__name__,
                        line, col,
                    )
            raise RTError("Unknown unary op %s" % expr.op, expr.line)
        if isinstance(expr, BinaryOp):
            # short-circuit for and/or
            if expr.op in ("and", "&&"):
                l = self.eval_expr(expr.left, env)
                if not self._truthy(l):
                    return l
                return self.eval_expr(expr.right, env)
            if expr.op in ("or", "||"):
                l = self.eval_expr(expr.left, env)
                if self._truthy(l):
                    return l
                return self.eval_expr(expr.right, env)
            l = self.eval_expr(expr.left, env)
            if op if False else (expr.op == "is" and isinstance(expr.right, Identifier) and expr.right.name in ("int", "float", "string", "bool", "list", "dict", "function", "instance")):
                r = None
            else:
                r = self.eval_expr(expr.right, env)
            op = expr.op
            line, col = self._pos(expr)
            if op == "+":
                if isinstance(l, str) or isinstance(r, str):
                    return self.to_string(l) + self.to_string(r)
                try:
                    return l + r
                except TypeError:
                    raise self._bad_operands(op, l, r, line, col)
            if op == "-":
                try:
                    return l - r
                except TypeError:
                    raise self._bad_operands(op, l, r, line, col)
            if op == "*":
                if isinstance(l, str) and isinstance(r, int):
                    return l * r
                if isinstance(r, str) and isinstance(l, int):
                    return r * l
                try:
                    return l * r
                except TypeError:
                    raise self._bad_operands(op, l, r, line, col)
            if op == "/":
                try:
                    return l / r
                except ZeroDivisionError:
                    raise RTError("Division by zero", line, col)
                except TypeError:
                    raise self._bad_operands(op, l, r, line, col)
            if op == "%":
                try:
                    return l % r
                except ZeroDivisionError:
                    raise RTError("Modulo by zero", line, col)
                except TypeError:
                    raise self._bad_operands(op, l, r, line, col)
            if op == "**":
                try:
                    return l ** r
                except ZeroDivisionError:
                    raise RTError("Division by zero", line, col)
                except TypeError:
                    raise self._bad_operands(op, l, r, line, col)
            if op == "==":
                return l == r
            if op == "!=":
                return l != r
            if op == "===":
                return l is r and type(l) is type(r)
            if op == "!==":
                return not (l is r and type(l) is type(r))
            if op in ("<", ">", "<=", ">="):
                return self._compare(l, r, op, line, col)
            if op == "is":
                # Type check: if right side is a type name, check runtime type
                if isinstance(expr.right, Identifier) and expr.right.name in ("int", "float", "string", "bool", "list", "dict", "function", "instance"):
                    type_name = expr.right.name
                    actual = self._type(l)
                    # normalize: bool is subtype of int
                    if type_name == "int" and actual == "bool":
                        return True
                    if type_name == "float" and actual == "int":
                        return True
                    return actual == type_name
                return l is r
            if op == "in":
                if isinstance(r, (list, tuple, str, dict)):
                    try:
                        return l in r
                    except TypeError:
                        raise RTError(
                            "Unhashable key type: %s" % type(l).__name__,
                            line, col,
                        )
                raise RTError("'in' not supported", line, col)
            raise RTError("Unknown binary op %s" % op, line, col)
        if isinstance(expr, Assign):
            val = self.eval_expr(expr.value, env)
            target = expr.target
            line, col = self._pos(target)
            if expr.op != "=":
                cur = self.eval_expr(target, env)
                op = expr.op[:-1]
                try:
                    if op == "+": val = cur + val
                    elif op == "-": val = cur - val
                    elif op == "*": val = cur * val
                    elif op == "/": val = cur / val
                    elif op == "%": val = cur % val
                except ZeroDivisionError:
                    raise RTError("Division by zero", line, col)
                except TypeError:
                    raise self._bad_operands(op, cur, val, line, col)
            if isinstance(target, Identifier):
                if target.name == "this":
                    # find instance env? handle below via 'this' binding
                    pass
                env.set(target.name, val, target.line, target.col)
                return val
            if isinstance(target, Index):
                obj = self.eval_expr(target.obj, env)
                idx = self.eval_expr(target.index, env)
                try:
                    obj[idx] = val
                except IndexError:
                    raise RTError("Index out of range: %r" % (idx,), line, col)
                except TypeError as error:
                    raise RTError("Cannot assign by index: %s" % error, line, col)
                return val
            if isinstance(target, Member):
                obj = self.eval_expr(target.obj, env)
                if isinstance(obj, RenixxInstance):
                    obj.set(target.name, val)
                elif isinstance(obj, dict):
                    obj[target.name] = val
                else:
                    setattr(obj, target.name, val)
                return val
            raise RTError("Invalid assignment target", expr.line)
        if isinstance(expr, Call):
            callee = self.eval_expr(expr.callee, env)
            args = [self.eval_expr(a, env) for a in expr.args]
            kwargs = {}
            for name, e in expr.kwargs:
                kwargs[name] = self.eval_expr(e, env)
            line, col = self._pos(expr)
            return self.call_callable(callee, args, kwargs, line, col)
        if isinstance(expr, Index):
            obj = self.eval_expr(expr.obj, env)
            idx = self.eval_expr(expr.index, env)
            line, col = self._pos(expr)
            if isinstance(obj, dict):
                try:
                    if idx not in obj:
                        raise RTError("KeyError: %r" % idx, line, col)
                    return obj[idx]
                except TypeError:
                    raise RTError(
                        "Unhashable key type: %s" % type(idx).__name__,
                        line, col,
                    )
            if isinstance(obj, (list, tuple, str)):
                try:
                    return obj[idx]
                except IndexError:
                    raise RTError("Index out of range: %r" % (idx,), line, col)
                except TypeError:
                    raise RTError(
                        "Invalid index type: %s" % type(idx).__name__,
                        line, col,
                    )
            raise RTError("Cannot index %s" % type(obj).__name__, line, col)
        if isinstance(expr, Slice):
            obj = self.eval_expr(expr.obj, env)
            start = self.eval_expr(expr.start, env) if expr.start is not None else None
            stop = self.eval_expr(expr.stop, env) if expr.stop is not None else None
            step = self.eval_expr(expr.step, env) if expr.step is not None else None
            line, col = self._pos(expr)
            if isinstance(obj, (list, tuple, str)):
                try:
                    return obj[slice(start, stop, step)]
                except ValueError:
                    raise RTError("Slice step cannot be zero", line, col)
                except TypeError:
                    raise RTError("Invalid slice bounds", line, col)
            raise RTError("Cannot slice %s" % type(obj).__name__, line, col)
        if isinstance(expr, Member):
            obj = self.eval_expr(expr.obj, env)
            line, col = self._pos(expr)
            if isinstance(obj, RenixxSuper):
                defining = obj.defining_class
                cur = defining.superclass if isinstance(defining.superclass, RenixxClass) else None
                while isinstance(cur, RenixxClass):
                    for m in cur.decl.methods:
                        if m.name == expr.name:
                            bind_env = Environment(cur.env if hasattr(cur, 'env') else self.globals_env)
                            bind_env.define("this", obj.instance, mutable=True)
                            if cur.superclass is not None and isinstance(cur.superclass, RenixxClass):
                                bind_env.define("super", RenixxSuper(obj.instance, cur), mutable=True)
                            return RenixxFunction(m, bind_env, self)
                    cur = cur.superclass if isinstance(cur.superclass, RenixxClass) else None
                raise RTError("No property '%s'" % expr.name, line, col)
            if isinstance(obj, RenixxInstance):
                # field?
                if expr.name in obj.fields:
                    return obj.fields[expr.name]
                # method? walk full superclass chain
                cls = obj.cls
                while isinstance(cls, RenixxClass):
                    for m in cls.decl.methods:
                        if m.name == expr.name:
                            # bind this
                            bind_env = Environment(cls.env if hasattr(cls, 'env') else self.globals_env)
                            bind_env.define("this", obj, mutable=True)
                            if cls.superclass is not None and isinstance(cls.superclass, RenixxClass):
                                bind_env.define("super", RenixxSuper(obj, cls), mutable=True)
                            return RenixxFunction(m, bind_env, self)
                    cls = cls.superclass if isinstance(cls.superclass, RenixxClass) else None
                raise RTError("No property '%s'" % expr.name, line, col)
            if isinstance(obj, dict):
                if expr.name in obj:
                    return obj[expr.name]
                # dict methods
                if expr.name == "get":
                    return lambda k, default=None: obj.get(k, default)
                if expr.name == "keys":
                    return lambda: list(obj.keys())
                if expr.name == "values":
                    return lambda: list(obj.values())
                if expr.name == "has":
                    return lambda k: k in obj
                raise RTError("No property '%s'" % expr.name, line, col)
            if isinstance(obj, list):
                if expr.name == "push":
                    return lambda x: (obj.append(x), None)[1]
                if expr.name == "append":
                    return lambda x: (obj.append(x), None)[1] or None
                if expr.name == "pop":
                    return lambda i=-1: obj.pop(i)
                if expr.name == "insert":
                    return lambda i, x: (obj.insert(i, x), None)[1]
                if expr.name == "remove":
                    return lambda x: (obj.remove(x), None)[1]
                if expr.name == "sort":
                    return lambda: (obj.sort(), None)[1]
                if expr.name == "reverse":
                    return lambda: (obj.reverse(), None)[1]
                if expr.name == "contains":
                    return lambda x: x in obj
                if expr.name == "indexOf":
                    return lambda x: obj.index(x) if x in obj else -1
                if expr.name == "map":
                    return lambda f: [f(x) for x in obj]
                if expr.name == "filter":
                    return lambda f: [x for x in obj if f(x)]
                if expr.name == "join":
                    return lambda sep="": sep.join(self.to_string(x) for x in obj)
                raise RTError("No property '%s'" % expr.name, line, col)
            if isinstance(obj, str):
                if expr.name == "upper":
                    return lambda: obj.upper()
                if expr.name == "lower":
                    return lambda: obj.lower()
                if expr.name == "strip":
                    return lambda: obj.strip()
                if expr.name == "split":
                    return lambda sep=None: obj.split(sep)
                if expr.name == "replace":
                    return lambda a, b: obj.replace(a, b)
                if expr.name == "contains":
                    return lambda x: x in obj
                if expr.name == "startswith":
                    return lambda x: obj.startswith(x)
                if expr.name == "endswith":
                    return lambda x: obj.endswith(x)
                raise RTError("No property '%s'" % expr.name, line, col)
            if isinstance(obj, RenixxClass):
                # static? 
                pass
            try:
                return getattr(obj, expr.name)
            except AttributeError:
                raise RTError("No property '%s'" % expr.name, line, col)
        if isinstance(expr, ListLiteral):
            result = []
            for e in expr.elements:
                if isinstance(e, Spread):
                    val = self.eval_expr(e.value, env)
                    if isinstance(val, (list, tuple)):
                        result.extend(val)
                    else:
                        result.append(val)
                else:
                    result.append(self.eval_expr(e, env))
            return result
        if isinstance(expr, ListComp):
            iterable = self.eval_expr(expr.iterable, env)
            result = []
            for item in iterable:
                new_env = Environment(env)
                new_env.define(expr.var, item, mutable=True)
                if expr.cond is not None and not self._truthy(self.eval_expr(expr.cond, new_env)):
                    continue
                result.append(self.eval_expr(expr.expr, new_env))
            return result
        if isinstance(expr, DictComp):
            iterable = self.eval_expr(expr.iterable, env)
            result = {}
            for item in iterable:
                new_env = Environment(env)
                new_env.define(expr.var, item, mutable=True)
                if expr.cond is not None and not self._truthy(self.eval_expr(expr.cond, new_env)):
                    continue
                k = self.eval_expr(expr.key, new_env)
                v = self.eval_expr(expr.val, new_env)
                result[k] = v
            return result
        if isinstance(expr, DictLiteral):
            d = {}
            for k, v in expr.pairs:
                key = self.eval_expr(k, env)
                # make hashable if needed
                if isinstance(key, (list, dict)):
                    raise RTError("Unhashable key", expr.line)
                d[key] = self.eval_expr(v, env)
            return d
        if isinstance(expr, FunctionExpr):
            return RenixxFunction(expr, env, self)
        if isinstance(expr, Lambda):
            return RenixxLambda(expr, env, self)
        if isinstance(expr, NewExpr):
            cls = None
            if env.has(expr.class_name):
                cls = env.get(expr.class_name)
            elif self.globals_env.has(expr.class_name):
                cls = self.globals_env.get(expr.class_name)
            if not isinstance(cls, RenixxClass):
                raise RTError("Unknown class '%s'" % expr.class_name, expr.line)
            instance = RenixxInstance(cls)
            # call init
            args = [self.eval_expr(a, env) for a in expr.args]
            init_method = None
            # walk full superclass chain to find init
            cur = cls
            while isinstance(cur, RenixxClass):
                for m in cur.decl.methods:
                    if m.name == "init":
                        init_method = m
                        cls = cur  # use the class where init was found for env
                        break
                if init_method is not None:
                    break
                cur = cur.superclass if isinstance(cur.superclass, RenixxClass) else None
            if init_method is not None:
                # execute init with this=instance
                fn_env = Environment(cls.env)
                fn_env.define("this", instance, mutable=True)
                if cls.superclass is not None and isinstance(cls.superclass, RenixxClass):
                    fn_env.define("super", RenixxSuper(instance, cls), mutable=True)
                # bind params
                params = init_method.params
                # handle defaults/rest
                self._bind_params(params, args, {}, fn_env)
                # execute body
                prev_env = self.current_env
                self.current_env = fn_env
                try:
                    self.exec_stmt(init_method.body, fn_env)
                except ReturnValue:
                    pass
                finally:
                    self.current_env = prev_env
            return instance
        if isinstance(expr, Ternary):
            if self._truthy(self.eval_expr(expr.cond, env)):
                return self.eval_expr(expr.then_expr, env)
            return self.eval_expr(expr.else_expr, env)
        if isinstance(expr, RangeExpr):
            start = self.eval_expr(expr.start, env) if expr.start else 0
            stop = self.eval_expr(expr.stop, env)
            step = self.eval_expr(expr.step, env) if expr.step else 1
            return self._builtin_range(start, stop, step)
        raise RTError("Unknown expression type: %s" % type(expr).__name__, getattr(expr, "line", 0))

    def _compare(self, l, r, op, line=0, col=0):
        try:
            if op == "<": return l < r
            if op == ">": return l > r
            if op == "<=": return l <= r
            if op == ">=": return l >= r
        except TypeError:
            raise RTError(
                "Cannot compare %s and %s" % (type(l).__name__, type(r).__name__),
                line, col,
            )
        return False

    def call_callable(self, callee, args, kwargs, line, col=0):
        if isinstance(callee, RenixxFunction):
            return self.call_function(callee, args, kwargs)
        if isinstance(callee, RenixxLambda):
            return self.call_lambda(callee, args, kwargs)
        if callable(callee):
            # builtin python function or module fn
            # convert args
            try:
                return callee(*args, **kwargs)
            except RTError as error:
                # Position is known only at the call site, not inside builtins.
                if not error.line:
                    error.line = line
                    if not error.col:
                        error.col = col
                raise
            except (ZeroDivisionError, IndexError, KeyError, ValueError, TypeError) as error:
                raise RTError(str(error), line, col)
        if isinstance(callee, RenixxBoundMethod) if False else False:
            pass
        # method reference stored as function with this? handle Member returning RenixxFunction for method: need instance binding
        raise RTError("'%s' is not callable" % self.to_string(callee), line, col)

    def call_function(self, fn, args, kwargs):
        decl = fn.decl
        env = Environment(fn.closure)
        self._bind_params(decl.params, args, kwargs, env)
        # if method, 'this' should be in closure? We'll inject this when creating method. For now, if closure has 'this' keep.
        prev = self.current_env
        self.current_env = env
        self.call_stack.append((fn.name or "<fn>", getattr(decl, "line", 0)))
        from .errors import set_current_stack
        set_current_stack(self.call_stack)
        try:
            self.exec_stmt(decl.body, env)
        except ReturnValue as rv:
            if getattr(decl, "return_type", None):
                self._check_type(rv.value, decl.return_type)
            return rv.value
        except BreakSignal as sig:
            raise RTError("'break' outside loop", getattr(sig, "line", 0))
        except ContinueSignal as sig:
            raise RTError("'continue' outside loop", getattr(sig, "line", 0))
        finally:
            if self.call_stack:
                self.call_stack.pop()
            self.current_env = prev
            set_current_stack(self.call_stack)
        if getattr(decl, "return_type", None):
            self._check_type(None, decl.return_type)
        return None

    def call_lambda(self, lam, args, kwargs):
        node = lam.node
        env = Environment(lam.closure)
        self._bind_params(node.params, args, kwargs, env)
        prev = self.current_env
        self.current_env = env
        self.call_stack.append(("<lambda>", getattr(node, "line", 0)))
        from .errors import set_current_stack
        set_current_stack(self.call_stack)
        try:
            # body is single expression
            return self.eval_expr(node.body, env)
        finally:
            if self.call_stack:
                self.call_stack.pop()
            self.current_env = prev
            set_current_stack(self.call_stack)

    def _bind_params(self, params, args, kwargs, env):
        positional = list(args)
        rest_idx = None
        for idx, p in enumerate(params):
            if len(p) >= 3 and p[2]:
                rest_idx = idx
                break
        kw_map = dict(kwargs)
        ai = 0
        for idx, p in enumerate(params):
            pname = p[0]
            default = p[1] if len(p) > 1 else None
            is_rest = p[2] if len(p) > 2 else False
            annot = p[3] if len(p) > 3 else None
            if is_rest:
                # collect remaining positional
                rest_vals = positional[ai:]
                # also kwargs not consumed? collect into list of pairs? Keep simple: positional rest
                self._bind_one(env, pname, rest_vals, annot)
                ai = len(positional)
                continue
            if pname in kw_map:
                self._bind_one(env, pname, kw_map.pop(pname), annot)
                continue
            if ai < len(positional):
                self._bind_one(env, pname, positional[ai], annot)
                ai += 1
                continue
            # default
            if default is not None:
                self._bind_one(env, pname, self.eval_expr(default, env), annot)
                continue
            # missing required
            raise RTError("Missing argument '%s'" % pname)
        # extra kwargs? ignore or error
        # extra positional?
        if ai < len(positional) and rest_idx is None:
            raise RTError("Too many arguments")

    def exec_import(self, stmt, env):
        path = stmt.path
        # built-in module via "std:xxx" or name
        if path in ("math", "random", "time", "json", "os", "fs"):
            # import as module object
            mod = self.globals_env.get(path)
            target = stmt.alias or path
            if stmt.names:
                for n in stmt.names:
                    if isinstance(mod, dict) and n in mod:
                        env.define(n, mod[n], mutable=True)
                    else:
                        raise RTError("Name '%s' not found in module %s" % (n, path))
            else:
                env.define(target, mod, mutable=True)
            return
        # std: prefix
        if path.startswith("std:"):
            name = path[4:]
            return self.exec_import(ImportStmt(path=name, alias=stmt.alias, names=stmt.names, line=stmt.line), env)
        # file import
        # resolve relative to current file? We don't track; use cwd
        full = path
        if not os.path.isabs(full):
            full = os.path.join(os.getcwd(), full)
        if not os.path.exists(full):
            raise RTError("Module not found: %s" % path)
        src = open(full, encoding="utf-8").read()
        from .parser import parse as parse_src
        program = parse_src(src)
        mod_env = Environment(self.globals_env)
        self.run(program, mod_env)
        # export: if names/alias
        if stmt.names:
            for n in stmt.names:
                if mod_env.has(n):
                    env.define(n, mod_env.get(n), mutable=True)
                else:
                    raise RTError("Name '%s' not exported" % n)
        else:
            target = stmt.alias or os.path.splitext(os.path.basename(path))[0]
            # expose all top-level as a dict module
            mod = dict(mod_env.values)
            env.define(target, mod, mutable=True)

    def eval_file(self, path):
        src = open(path, encoding="utf-8").read()
        from .parser import parse as parse_src
        program = parse_src(src)
        self.run(program, self.globals_env)
