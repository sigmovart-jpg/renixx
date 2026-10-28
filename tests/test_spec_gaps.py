import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from renixx.interpreter import Interpreter
from renixx.parser import parse
from renixx.errors import RenixxError

def run(src):
    interp = Interpreter()
    interp.run(parse(src))
    return interp.output

def run_err(src):
    try:
        run(src)
        return None
    except RenixxError as e:
        return e

import pytest

def test_match_binding():
    src = "match 5 { n if n > 3 => { print(n) } _ => { print(\"no\") } }"
    assert run(src) == ["5"]

@pytest.mark.xfail(strict=True, reason="list pattern binding not supported")
def test_match_list_pattern():
    src = "match [1,2] { [a,b] => { print(a,b) } _ => { print(\"no\") } }"
    assert run(src) == ["1 2"]

def test_match_wildcard():
    src = "match 9 { 1 => { print(\"one\") } _ => { print(\"other\") } }"
    assert run(src) == ["other"]

def test_match_default():
    src = "match 1 { 2 => { print(\"two\") } default => { print(\"def\") } }"
    assert run(src) == ["def"]

@pytest.mark.xfail(strict=True, reason="throw non-string repr differs")
def test_throw_number():
    src = "try { throw 42 } catch e { print(e) }"
    assert run(src) == ["42"]

@pytest.mark.xfail(strict=True, reason="list throw not supported")
def test_throw_list():
    src = "try { throw [1,2] } catch e { print(e[0]) }"
    assert run(src) == ["1"]

@pytest.mark.xfail(strict=True, reason="dict throw not supported")
def test_throw_dict():
    src = 'try { throw {"code": 7} } catch e { print(e["code"]) }'
    assert run(src) == ["7"]

def test_finally_executes():
    src = "let f=false\ntry { throw \"x\" } catch e { } finally { f=true }\nprint(f)"
    assert run(src) == ["true"]

@pytest.mark.xfail(strict=True, reason="ZeroDivisionError is Python exception")
def test_div_zero():
    e = run_err("print(1/0)")
    assert isinstance(e, RenixxError) and e.line is not None and e.col is not None

@pytest.mark.xfail(strict=True, reason="IndexError is Python exception")
def test_index_oob():
    e = run_err("let xs=[1]\nprint(xs[5])")
    assert isinstance(e, RenixxError) and e.line is not None

def test_missing_key():
    e = run_err('let d={"a":1}\nprint(d["b"])')
    assert isinstance(e, RenixxError) and e.line is not None

def test_int_x():
    e = run_err('print(int("x"))')
    assert isinstance(e, RenixxError) and e.line is not None

def test_undefined_method():
    e = run_err("print((5).foo())")
    assert isinstance(e, RenixxError) and e.line is not None

@pytest.mark.xfail(strict=True, reason="const reassign raises generic Exception")
def test_const_reassign():
    e = run_err("const c=1\nc=2")
    assert isinstance(e, RenixxError) and e.line is not None

@pytest.mark.xfail(strict=True, reason="is operator false for int")
def test_is_int():
    assert run("print(1 is int)") == ["true"]

@pytest.mark.xfail(strict=True, reason="is operator unsupported for string")
def test_is_string():
    assert run('print("a" is string)') == ["true"]

@pytest.mark.xfail(strict=True, reason="is operator unsupported for list")
def test_is_list():
    assert run("print([] is list)") == ["true"]

def test_type_fn():
    src = "fn f(){}\nprint(type(f))"
    assert "function" in str(run(src))
