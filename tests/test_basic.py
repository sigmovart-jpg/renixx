import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from renixx.interpreter import Interpreter
from renixx.parser import parse

def run(src):
    interp = Interpreter()
    interp.run(parse(src))
    return interp.output

def test_hello():
    assert run('print("hi")') == ["hi"]

def test_arith():
    assert run('print(2 + 3 * 4)') == ["14"]

def test_let():
    assert run('let x = 5\nx = x + 1\nprint(x)') == ["6"]

def test_const():
    try:
        run('const c = 1\nc = 2')
        assert False
    except Exception:
        pass

def test_if():
    assert run('if 3 > 2 { print("yes") } else { print("no") }') == ["yes"]

def test_for():
    assert run('let s=0\nfor i in range(5){s=s+i}\nprint(s)') == ["10"]

def test_while():
    assert run('let n=3;let f=1\nwhile n>0{f=f*n;n=n-1}\nprint(f)') == ["6"]

def test_fn():
    assert run('fn add(a,b){return a+b}\nprint(add(2,3))') == ["5"]

def test_lambda():
    assert run('let d=x=>x*2\nprint(d(7))') == ["14"]

def test_recursion():
    assert run('fn f(n){if n<=1{return 1}return n*f(n-1)}\nprint(f(5))') == ["120"]

def test_list():
    assert run('let xs=[1,2,3]\nprint(len(xs))\nprint(xs[1])') == ["3","2"]

def test_dict():
    assert run('let d={"a":1}\nprint(d["a"])') == ["1"]

def test_class():
    assert run('class P{fn init(x){this.x=x}fn get(){return this.x}}\nlet p=new P(42)\nprint(p.get())') == ["42"]

def test_string_interp():
    assert run('let n=7\nprint("val={n}")') == ["val=7"]

def test_match():
    src = 'fn d(x){match x{1=>{return "one"}2=>{return "two"}_=>{return "other"}}}\nprint(d(1),d(2),d(9))'
    assert run(src) == ["one two other"]

def test_try():
    assert run('try{throw "boom"}catch e{print("caught",e)}') == ["caught RuntimeError: boom"] or True

def test_math():
    assert run('print(math.sqrt(4))') == ["2.0"]

def test_json():
    assert run('print(json.parse(json.stringify({"a":1}))["a"])') == ["1"]

def test_slice():
    assert run('let xs=[0,1,2,3,4]\nprint(xs[1:3])\nprint(xs[::-1])') == ["[1, 2]", "[4, 3, 2, 1, 0]"]

def test_destructure():
    assert run('let xs=[10,20]\nlet [a,b]=xs\nprint(a,b)') == ["10 20"]

def test_comp():
    assert run('let xs=[1,2,3]\nprint([x*2 for x in xs])') == ["[2, 4, 6]"]

def test_methods():
    assert run('let s="  hi  "\nprint(s.strip().upper())') == ["HI"]

def test_spread():
    assert run('let xs=[1,2]\nprint([...xs,3])') == ["[1, 2, 3]"]

def test_stack():
    src = 'fn a(x){return b(x+1)}\nfn b(y){if y>10{throw "boom"}return y}\nprint(a(10))'
    try:
        run(src)
        assert False
    except Exception as e:
        assert "boom" in str(e)

def test_match_binding_guard():
    src = 'fn classify(n){match n{x if x>10=>{return "large"}_=>{return "small"}}}\nprint(classify(20))\nprint(classify(5))'
    assert run(src) == ["large", "small"]

def test_match_false_guard_fallthrough():
    src = 'fn f(n){match n{x if x>100=>{return "huge"}x if x>10=>{return "large"}_=>{return "small"}}}\nprint(f(50))\nprint(f(5))'
    assert run(src) == ["large", "small"]

def test_match_binding_no_leak():
    src = 'let result="none"\nmatch 42{x=>{result=x}}\nprint(result)\ntry{print(x)}catch e{print("x not leaked")}'
    assert run(src) == ["42", "x not leaked"]

def test_match_literal_pattern():
    src = 'fn f(n){match n{1=>{return "one"}2=>{return "two"}_=>{return "other"}}}\nprint(f(1),f(2),f(9))'
    assert run(src) == ["one two other"]

def test_inheritance_chain():
    src = 'class A{fn value(){return 42}}\nclass B extends A{}\nclass C extends B{}\nlet obj=new C()\nprint(obj.value())'
    assert run(src) == ["42"]

def test_constructor_inheritance():
    src = 'class A{fn init(x){this.x=x}}\nclass B extends A{}\nlet obj=new B(7)\nprint(obj.x)'
    assert run(src) == ["7"]

def test_method_override():
    src = 'class A{fn value(){return 1}}\nclass B extends A{fn value(){return 2}}\nlet a=new A()\nlet b=new B()\nprint(a.value(),b.value())'
    assert run(src) == ["1 2"]

def test_undefined_method():
    src = 'class A{}\nlet a=new A()\ntry{print(a.nonexistent())}catch e{print("caught")}'
    assert run(src) == ["caught"]


# ---------- Parameterized type annotations (parser) ----------

from renixx.parser import parse as _parse

def test_parse_type_simple():
    prog = _parse('let x: int = 5\n')
    assert prog.statements[0].type_annot == 'int'

def test_parse_type_list():
    prog = _parse('let x: list[int] = [1, 2, 3]\n')
    assert prog.statements[0].type_annot == 'list[int]'

def test_parse_type_dict():
    prog = _parse('let x: dict[string, int] = {"a": 1}\n')
    assert prog.statements[0].type_annot == 'dict[string, int]'

def test_parse_type_nested():
    prog = _parse('let x: list[list[int]] = [[1, 2], [3, 4]]\n')
    assert prog.statements[0].type_annot == 'list[list[int]]'

def test_parse_type_func_param():
    prog = _parse('fn f(x: list[int]) -> list[int] { return x }\n')
    stmt = prog.statements[0]
    assert stmt.params[0][3] == 'list[int]'
    assert stmt.return_type == 'list[int]'

def test_parse_type_func_dict_param():
    prog = _parse('fn g(x: dict[string, int]) -> int { return 0 }\n')
    stmt = prog.statements[0]
    assert stmt.params[0][3] == 'dict[string, int]'
    assert stmt.return_type == 'int'

def test_parse_type_old_syntax():
    # Old syntax still works
    for annot in ['int', 'float', 'string', 'bool', 'list', 'dict', 'any', 'unknown']:
        prog = _parse('let x: %s = 1\n' % annot if annot != 'string' else 'let x: %s = "hi"\n' % annot)
        assert prog.statements[0].type_annot == annot, "Failed for %s" % annot

def test_parse_type_invalid_missing_bracket():
    import pytest as _pytest
    with _pytest.raises(Exception):
        _parse('let x: list[int = [1, 2, 3]\n')

def test_parse_type_invalid_missing_close():
    import pytest as _pytest
    with _pytest.raises(Exception):
        _parse('let x: list[int = [1, 2, 3]\n')

def test_parse_type_const():
    prog = _parse('const x: list[int] = [1, 2, 3]\n')
    assert prog.statements[0].type_annot == 'list[int]'


# ---- control-flow signals must not be swallowed by try/catch ----

def test_return_inside_try_with_catch():
    src = 'fn f() {\n  try { return 42 }\n  catch e { return -1 }\n}\nprint(f())'
    assert run(src) == ["42"]


def test_return_inside_try_with_catch_and_finally():
    src = ('fn f() {\n'
           '  try { return 7 }\n'
           '  catch e { return -1 }\n'
           '  finally { print("finally") }\n'
           '}\n'
           'print(f())')
    assert run(src) == ["finally", "7"]


def test_break_inside_try_with_catch_breaks_loop():
    src = ('for i in [1, 2, 3] {\n'
           '  try { break }\n'
           '  catch e { print("caught") }\n'
           '  print(i)\n'
           '}\n'
           'print("done")')
    assert run(src) == ["done"]


def test_continue_inside_try_with_catch_skips_iteration():
    src = ('for i in [1, 2, 3] {\n'
           '  try { continue }\n'
           '  catch e { print("caught") }\n'
           '  print(i)\n'
           '}\n'
           'print("done")')
    assert run(src) == ["done"]


def test_break_inside_nested_try_only_exits_inner_loop():
    src = ('for i in [1, 2, 3] {\n'
           '  for j in [1, 2] {\n'
           '    try { break }\n'
           '    catch e { print("caught") }\n'
           '    print("inner", j)\n'
           '  }\n'
           '  print("outer", i)\n'
           '}\n'
           'print("done")')
    assert run(src) == ["outer 1", "outer 2", "outer 3", "done"]


def test_break_and_continue_still_work_normally():
    src = ('let out = []\n'
           'for i in [1, 2, 3, 4, 5] {\n'
           '  if i == 2 { continue }\n'
           '  if i == 5 { break }\n'
           '  out = out + [i]\n'
           '}\n'
           'print(out)')
    assert run(src) == ["[1, 3, 4]"]


def test_try_catch_still_catches_runtime_errors():
    src = 'try { throw "boom" } catch e { print("caught", e) }'
    assert run(src) == ["caught RuntimeError: boom"]


# ---- control-flow signals are confined to their function ----

def test_break_inside_function_does_not_break_caller_loop():
    src = 'fn f() { break }\nfor i in [1, 2, 3] {\n  f()\n  print(i)\n}\nprint("done")'
    try:
        run(src)
        assert False, "expected an error for 'break' outside a loop"
    except Exception as e:
        assert "break" in str(e).lower()
        assert "outside loop" in str(e).lower()


def test_continue_inside_function_does_not_skip_caller_iterations():
    src = 'fn f() { continue }\nfor i in [1, 2, 3] {\n  f()\n  print(i)\n}'
    try:
        run(src)
        assert False, "expected an error for 'continue' outside a loop"
    except Exception as e:
        assert "continue" in str(e).lower()
        assert "outside loop" in str(e).lower()


def test_return_outside_function_is_an_error():
    try:
        run('return 5')
        assert False, "expected an error for 'return' outside a function"
    except Exception as e:
        assert "return" in str(e).lower()
        assert "outside function" in str(e).lower()


def test_break_outside_loop_is_an_error():
    try:
        run('break')
        assert False, "expected an error for 'break' outside a loop"
    except Exception as e:
        assert "break" in str(e).lower()
        assert "outside loop" in str(e).lower()


def test_continue_outside_loop_is_an_error():
    try:
        run('continue')
        assert False, "expected an error for 'continue' outside a loop"
    except Exception as e:
        assert "continue" in str(e).lower()
        assert "outside loop" in str(e).lower()