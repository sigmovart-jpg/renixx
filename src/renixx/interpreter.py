"""Tree-walking interpreter for Renixx."""
import os
import sys
import time
import math
import random
import json as _json
from .ast import *
from .errors import RuntimeError as RTError, ReturnValue, BreakSignal, ContinueSignal
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
        if isinstance(x, RenixxClass): return "class"
        if isinstance(x, RenixxInstance): return "instance"
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

    # ---- execution ----
    def run(self, program, env=None):
        if env is None:
            env = self.globals_env
        self.current_env = env
        for stmt in program.statements:
            self.exec_stmt(stmt, env)
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
            env.define(stmt.name, val, mutable=stmt.mutable)
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
                    if guard is None or self._truthy(self.eval_expr(guard, env)):
                        self._exec_match_body(body, env)
                        matched = True
                        break
                    continue
                # pattern matching
                if self._match_pattern(pat, val, env):
                    if guard is not None and not self._truthy(self.eval_expr(guard, env)):
                        continue
                    self._exec_match_body(body, env)
                    matched = True
                    break
            return
        if isinstance(stmt, TryStmt):
            try:
                self.exec_stmt(stmt.try_block, env)
            except Exception as e:
                if stmt.catch_block is not None:
                    new_env = Environment(env)
                    if stmt.catch_var:
                        new_env.define(stmt.catch_var, str(e) if not isinstance(e, RTError) else e.message, mutable=True)
                        # store error object
                        new_env.set(stmt.catch_var, e if isinstance(e, Exception) else RTError(str(e)))
                    self.exec_stmt(stmt.catch_block, new_env)
                else:
                    raise
            finally:
                if stmt.finally_block is not None:
                    self.exec_stmt(stmt.finally_block, env)
            return
        if isinstance(stmt, ReturnStmt):
            v = None
            if stmt.value is not None:
                v = self.eval_expr(stmt.value, env)
            raise ReturnValue(v)
        if isinstance(stmt, ThrowStmt):
            v = self.eval_expr(stmt.value, env)
            raise RTError(self.to_string(v))
        if isinstance(stmt, BreakStmt):
            raise BreakSignal()
        if isinstance(stmt, ContinueStmt):
            raise ContinueSignal()
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
        if isinstance(pat, Identifier):
            # binding pattern: bind val to name in env? For simplicity, treat identifier as binding (always matches)
            # But if it's a known const/variable, compare equality
            if env.has(pat.name):
                try:
                    return env.get(pat.name) == val
                except Exception:
                    pass
            # binding: define in a new scope? We'll just accept match and optionally bind not needed
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
            if env.has(name):
                return env.get(name)
            # globals builtins already in globals_env
            if self.globals_env.has(name):
                return self.globals_env.get(name)
            raise RTError("Undefined variable '%s'" % name, expr.line)
        if isinstance(expr, UnaryOp):
            v = self.eval_expr(expr.operand, env)
            if expr.op in ("-",):
                return -v
            if expr.op in ("+",):
                return +v
            if expr.op in ("!", "not"):
                return not self._truthy(v)
            if expr.op == "~":
                return ~int(v)
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
            r = self.eval_expr(expr.right, env)
            op = expr.op
            if op == "+":
                if isinstance(l, str) or isinstance(r, str):
                    return self.to_string(l) + self.to_string(r)
                return l + r
            if op == "-":
                return l - r
            if op == "*":
                if isinstance(l, str) and isinstance(r, int):
                    return l * r
                if isinstance(r, str) and isinstance(l, int):
                    return r * l
                return l * r
            if op == "/":
                return l / r
            if op == "%":
                return l % r
            if op == "**":
                return l ** r
            if op == "==":
                return l == r
            if op == "!=":
                return l != r
            if op == "===":
                return l is r and type(l) is type(r)
            if op == "!==":
                return not (l is r and type(l) is type(r))
            if op in ("<", ">", "<=", ">="):
                return self._compare(l, r, op)
            if op == "is":
                return l is r
            if op == "in":
                if isinstance(r, (list, tuple, str, dict)):
                    if isinstance(r, dict):
                        return l in r
                    return l in r
                raise RTError("'in' not supported", expr.line)
            raise RTError("Unknown binary op %s" % op, expr.line)
        if isinstance(expr, Assign):
            val = self.eval_expr(expr.value, env)
            target = expr.target
            if expr.op != "=":
                cur = self.eval_expr(target, env)
                op = expr.op[:-1]
                if op == "+": val = cur + val
                elif op == "-": val = cur - val
                elif op == "*": val = cur * val
                elif op == "/": val = cur / val
                elif op == "%": val = cur % val
            if isinstance(target, Identifier):
                if target.name == "this":
                    # find instance env? handle below via 'this' binding
                    pass
                env.set(target.name, val)
                return val
            if isinstance(target, Index):
                obj = self.eval_expr(target.obj, env)
                idx = self.eval_expr(target.index, env)
                obj[idx] = val
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
            return self.call_callable(callee, args, kwargs, expr.line)
        if isinstance(expr, Index):
            obj = self.eval_expr(expr.obj, env)
            idx = self.eval_expr(expr.index, env)
            if isinstance(obj, dict):
                if idx not in obj:
                    raise RTError("KeyError: %r" % idx, expr.line)
                return obj[idx]
            if isinstance(obj, (list, tuple, str)):
                return obj[idx]
            raise RTError("Cannot index %s" % type(obj).__name__, expr.line)
        if isinstance(expr, Member):
            obj = self.eval_expr(expr.obj, env)
            if isinstance(obj, RenixxInstance):
                # field?
                if expr.name in obj.fields:
                    return obj.fields[expr.name]
                # method?
                for m in obj.cls.decl.methods:
                    if m.name == expr.name:
                        # bind this
                        bind_env = Environment(obj.cls.env if hasattr(obj.cls, 'env') else self.globals_env)
                        bind_env.define("this", obj, mutable=True)
                        # also expose fields as variables? Access via this.field in code; but code uses this.x. Fine.
                        return RenixxFunction(m, bind_env, self)
                # superclass
                if isinstance(obj.cls.superclass, RenixxClass):
                    sc = obj.cls.superclass
                    for m in sc.decl.methods:
                        if m.name == expr.name:
                            bind_env = Environment(sc.env)
                            bind_env.define("this", obj, mutable=True)
                            return RenixxFunction(m, bind_env, self)
                raise RTError("No property '%s'" % expr.name, expr.line)
            if isinstance(obj, dict):
                if expr.name in obj:
                    return obj[expr.name]
                raise RTError("No property '%s'" % expr.name, expr.line)
            if isinstance(obj, RenixxClass):
                # static? 
                pass
            try:
                return getattr(obj, expr.name)
            except Exception:
                raise RTError("No property '%s'" % expr.name, expr.line)
        if isinstance(expr, ListLiteral):
            return [self.eval_expr(e, env) for e in expr.elements]
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
            for m in cls.decl.methods:
                if m.name == "init":
                    init_method = m
                    break
            if init_method is not None:
                # execute init with this=instance
                fn_env = Environment(cls.env)
                fn_env.define("this", instance, mutable=True)
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

    def _compare(self, l, r, op):
        try:
            if op == "<": return l < r
            if op == ">": return l > r
            if op == "<=": return l <= r
            if op == ">=": return l >= r
        except TypeError:
            raise RTError("Cannot compare %s and %s" % (type(l).__name__, type(r).__name__))
        return False

    def call_callable(self, callee, args, kwargs, line):
        if isinstance(callee, RenixxFunction):
            return self.call_function(callee, args, kwargs)
        if isinstance(callee, RenixxLambda):
            return self.call_lambda(callee, args, kwargs)
        if callable(callee):
            # builtin python function or module fn
            # convert args
            try:
                return callee(*args, **kwargs)
            except TypeError as e:
                raise RTError(str(e), line)
        if isinstance(callee, RenixxBoundMethod) if False else False:
            pass
        # method reference stored as function with this? handle Member returning RenixxFunction for method: need instance binding
        raise RTError("'%s' is not callable" % self.to_string(callee), line)

    def call_function(self, fn, args, kwargs):
        decl = fn.decl
        env = Environment(fn.closure)
        self._bind_params(decl.params, args, kwargs, env)
        # if method, 'this' should be in closure? We'll inject this when creating method. For now, if closure has 'this' keep.
        prev = self.current_env
        self.current_env = env
        try:
            self.exec_stmt(decl.body, env)
        except ReturnValue as rv:
            return rv.value
        finally:
            self.current_env = prev
        return None

    def call_lambda(self, lam, args, kwargs):
        node = lam.node
        env = Environment(lam.closure)
        self._bind_params(node.params, args, kwargs, env)
        prev = self.current_env
        self.current_env = env
        try:
            # body is single expression
            return self.eval_expr(node.body, env)
        finally:
            self.current_env = prev

    def _bind_params(self, params, args, kwargs, env):
        # params: list of (name, default_expr, rest)
        # separate rest
        positional = list(args)
        # handle defaults
        i = 0
        nparams = len(params)
        # find rest index
        rest_idx = None
        for idx, p in enumerate(params):
            if p[2]:
                rest_idx = idx
                break
        # bind positional
        # number of normal params (excluding rest)
        normal = [p for p in params if not p[2]]
        # map kwargs
        kw_map = dict(kwargs)
        # First, bind rest collector
        # We'll iterate params in order
        ai = 0
        for idx, (pname, default, is_rest) in enumerate(params):
            if is_rest:
                # collect remaining positional
                rest_vals = positional[ai:]
                # also kwargs not consumed? collect into list of pairs? Keep simple: positional rest
                env.define(pname, rest_vals, mutable=True)
                ai = len(positional)
                continue
            if pname in kw_map:
                env.define(pname, kw_map.pop(pname), mutable=True)
                continue
            if ai < len(positional):
                env.define(pname, positional[ai], mutable=True)
                ai += 1
                continue
            # default
            if default is not None:
                env.define(pname, self.eval_expr(default, env), mutable=True)
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
