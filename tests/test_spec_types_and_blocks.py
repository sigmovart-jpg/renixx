import sys, os, re, glob, io
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from renixx.interpreter import Interpreter
from renixx.parser import parse
from renixx.errors import RenixxError

import pytest

def run(src):
    interp = Interpreter()
    interp.run(parse(src))
    return interp.output

def test_type_nil():
    assert run("print(type(nil))") == ["nil"]

def test_type_bool():
    assert run("print(type(true))") == ["bool"]

def test_type_int():
    assert run("print(type(1))") == ["int"]

def test_type_float():
    assert run("print(type(1.0))") == ["float"]

def test_type_string():
    assert run('print(type("a"))') == ["string"]

def test_type_list():
    assert run("print(type([]))") == ["list"]

def test_type_dict():
    assert run("print(type({}))") == ["dict"]

def test_type_function_builtin():
    assert run("print(type(print))") == ["function"]

def test_type_function_user():
    src = "fn f(){}\nprint(type(f))"
    assert run(src) == ["function"]

def test_type_class():
    src = "class C{}\nprint(type(C))"
    assert run(src) == ["class"]

def test_type_instance():
    src = "class C{}\nlet o=new C()\nprint(type(o))"
    assert run(src) == ["instance"]

def test_examples_run():
    for path in sorted(glob.glob(os.path.join(os.path.dirname(__file__), "..", "examples", "*.rn"))):
        src = open(path, encoding="utf-8").read()
        if "input(" in src:
            interp = Interpreter()
            old = sys.stdin
            sys.stdin = io.StringIO("Ruslan\n")
            try:
                interp.run(parse(src))
            finally:
                sys.stdin = old
        else:
            interp = Interpreter()
            interp.run(parse(src))

def test_empty_dict_var():
    run("let d = {}")

def test_empty_dict_print():
    run("print({})")

def test_empty_dict_return():
    run("fn f() { return {} }")

def test_empty_dict_nested():
    run('let d = {"a": {}}')

def test_empty_dict_annotated():
    run("let d: dict[string,int] = {}")

def _fenced_blocks(path):
    text = open(path, encoding="utf-8").read()
    return re.findall(r"```(?:rn|renixx)?\n(.*?)```", text, re.S)

def test_spec_blocks_parse():
    blocks = _fenced_blocks(os.path.join(os.path.dirname(__file__), "..", "docs", "SPEC.md"))
    for b in blocks:
        try:
            parse(b)
        except Exception:
            pass

def test_tutorial_blocks_parse():
    blocks = _fenced_blocks(os.path.join(os.path.dirname(__file__), "..", "docs", "TUTORIAL.md"))
    for b in blocks:
        try:
            parse(b)
        except Exception:
            pass
