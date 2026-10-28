import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from renixx import cli
from renixx.errors import RenixxError, ThrowSignal
from renixx.interpreter import Interpreter
from renixx.parser import parse


def run(source):
    interp = Interpreter()
    interp.run(parse(source))
    return interp.output


def run_error(source):
    with pytest.raises(RenixxError) as info:
        run(source)
    return info.value


def _write(tmp_path, name, source):
    path = tmp_path / name
    path.write_text(source, encoding="utf-8")
    return str(path)


@pytest.fixture(autouse=True)
def _reset_debug_flag():
    yield
    cli._DEBUG = False


# --- user errors are RenixxError with position ----------------------------

def test_division_by_zero_has_position():
    error = run_error("print(1 / 0)")
    assert "Division by zero" in error.message
    assert error.line == 1
    assert error.col == 7
    assert error.stack == []


def test_modulo_by_zero_has_position():
    error = run_error("print(7 % 0)")
    assert "Modulo by zero" in error.message
    assert error.line == 1
    assert error.col == 7


def test_augmented_division_by_zero_has_position():
    error = run_error("let x = 1\nx /= 0")
    assert "Division by zero" in error.message
    assert error.line == 2
    assert error.col == 1


def test_list_index_out_of_range_has_position():
    error = run_error("let xs = [1]\nprint(xs[5])")
    assert "Index out of range" in error.message
    assert error.line == 2
    assert error.col == 7


def test_string_index_out_of_range_has_position():
    error = run_error('print("a"[3])')
    assert "Index out of range" in error.message
    assert error.line == 1


def test_invalid_index_type_is_renixx_error():
    error = run_error('let xs = [1]\nprint(xs["a"])')
    assert "Invalid index type" in error.message
    assert error.line == 2


def test_slice_step_zero_has_position():
    error = run_error("let xs = [1, 2]\nprint(xs[::0])")
    assert "Slice step cannot be zero" in error.message
    assert error.line == 2


def test_missing_dict_key_has_position():
    error = run_error('let d = {"a": 1}\nprint(d["b"])')
    assert "KeyError" in error.message
    assert error.line == 2
    assert error.col == 7


def test_int_conversion_error_has_position():
    error = run_error('print(int("x"))')
    assert "Cannot convert" in error.message
    assert error.line == 1
    assert error.col == 7


def test_float_conversion_error_has_position():
    error = run_error('print(float("x"))')
    assert "Cannot convert" in error.message
    assert error.line == 1
    assert error.col == 7


def test_invalid_operand_types_are_renixx_errors():
    error = run_error("print(1 + [2])")
    assert "Unsupported operand types" in error.message
    assert error.line == 1
    assert error.col == 7


def test_invalid_comparison_is_renixx_error():
    error = run_error('print(1 < "a")')
    assert "Cannot compare" in error.message
    assert error.line == 1


def test_missing_method_has_position():
    error = run_error("print((5).foo())")
    assert "No property 'foo'" in error.message
    assert error.line == 1
    assert error.col == 8


def test_const_reassignment_has_position():
    error = run_error("const c = 1\nc = 2")
    assert "Cannot reassign const 'c'" in error.message
    assert error.line == 2
    assert error.col == 1


def test_const_reassignment_from_function_has_line():
    source = "const c = 1\nfn f() {\n  c = 2\n}\nf()"
    error = run_error(source)
    assert "Cannot reassign const 'c'" in error.message
    assert error.line == 3


def test_undefined_variable_assignment_is_runtime_error():
    error = run_error("zz = 1")
    assert "Undefined variable 'zz'" in error.message
    assert error.line == 1
    assert error.col == 1

    out = run("try { zz = 1 } catch e { print(type(e), e) }")
    assert out == ["string Undefined variable 'zz'"]


def test_runtime_error_carries_call_stack():
    source = "fn inner() {\n  1 / 0\n}\nfn outer() {\n  inner()\n}\nouter()"
    error = run_error(source)
    names = [name for name, _line in error.stack]
    assert "inner" in names
    assert "outer" in names


# --- try/catch receives message strings for runtime errors ----------------

def test_catch_receives_runtime_error_message_string():
    out = run('try { print(1 / 0) } catch e { print(type(e), e) }')
    assert out == ["string Division by zero"]


def test_catch_receives_conversion_error_message():
    out = run('try { print(int("x")) } catch e { print(e) }')
    assert out == ["Cannot convert 'x' to int"]


def test_catch_receives_missing_key_message():
    out = run('let d = {"a": 1}\ntry { print(d["b"]) } catch e { print(e) }')
    assert out == ["KeyError: 'b'"]


# --- throw accepts any value and catch receives it unchanged --------------

def test_throw_number_preserves_value():
    assert run("try { throw 42 } catch e { print(e) }") == ["42"]


def test_throw_list_preserves_object_identity():
    source = "let xs = [1, 2]\ntry { throw xs } catch e { print(e === xs, e[0]) }"
    assert run(source) == ["true 1"]


def test_throw_dict_preserves_object_identity():
    source = 'let d = {"code": 7}\ntry { throw d } catch e { print(e === d, e["code"]) }'
    assert run(source) == ["true 7"]


def test_rethrow_from_catch_keeps_value():
    source = 'try { try { throw "a" } catch e { throw e } } catch outer { print(outer) }'
    assert run(source) == ["a"]


def test_finally_runs_after_caught_throw():
    source = 'let log = ""\ntry { throw "x" } catch e { log = log + "c" } finally { log = log + "f" }\nprint(log)'
    assert run(source) == ["cf"]


def test_finally_runs_after_caught_runtime_error():
    source = 'let log = ""\ntry { print(1 / 0) } catch e { log = log + "c" } finally { log = log + "f" }\nprint(log)'
    assert run(source) == ["cf"]


def test_uncaught_throw_reaches_caller_unchanged():
    with pytest.raises(ThrowSignal) as info:
        run("throw [1, 2]")
    assert info.value.value == [1, 2]
    assert info.value.line == 1


def test_uncaught_throw_inside_function_keeps_stack():
    with pytest.raises(ThrowSignal) as info:
        run('fn f() {\n  throw "x"\n}\nf()')
    names = [name for name, _line in info.value.stack]
    assert "f" in names


# --- internal interpreter bugs are not masked as user errors --------------

def test_try_catch_does_not_swallow_internal_python_errors():
    interp = Interpreter()

    def broken():
        raise RuntimeError("internal failure")

    interp.globals_env.define("broken", broken, False)
    source = 'try { broken() } catch e { print("caught") }'
    with pytest.raises(RuntimeError, match="internal failure"):
        interp.run(parse(source))


# --- return/break/continue keep working through try/finally ----------------

def test_return_through_finally_returns_value():
    source = 'fn f() {\n  try { return 7 } finally { print("cleanup") }\n}\nprint(f())'
    assert run(source) == ["cleanup", "7"]


def test_break_through_finally_exits_loop():
    source = 'for i in [1, 2, 3] {\n  try { break } finally { print("cleanup") }\n}\nprint("done")'
    assert run(source) == ["cleanup", "done"]


def test_continue_through_finally_skips_iteration():
    source = 'for i in [1, 2] {\n  try { continue } finally { print(i) }\n}'
    assert run(source) == ["1", "2"]


# --- CLI behaviour --------------------------------------------------------

def test_cli_uncaught_non_string_throw(capsys, tmp_path):
    path = _write(tmp_path, "throw.rn", "throw 42\n")
    assert cli.main(["run", path]) == 1
    err = capsys.readouterr().err
    assert "Uncaught: 42" in err
    assert path + ":1:7:" in err
    assert "^" in err
    assert "Traceback" not in err


def test_cli_uncaught_list_throw_uses_language_format(capsys, tmp_path):
    path = _write(tmp_path, "throw_list.rn", "throw [1, 2]\n")
    assert cli.main(["run", path]) == 1
    err = capsys.readouterr().err
    assert "Uncaught: [1, 2]" in err


def test_cli_caught_runtime_error_exits_zero(capsys, tmp_path):
    path = _write(tmp_path, "caught.rn", 'try { print(1 / 0) } catch e { print("caught", e) }\n')
    assert cli.main(["run", path]) == 0
    captured = capsys.readouterr()
    assert captured.out.strip() == "caught Division by zero"
    assert captured.err == ""


def test_cli_runtime_error_reports_position(capsys, tmp_path):
    path = _write(tmp_path, "index.rn", "let xs = [1]\nprint(xs[5])\n")
    assert cli.main(["run", path]) == 1
    err = capsys.readouterr().err
    assert path + ":2:7: RuntimeError: Index out of range" in err
    assert "Traceback" not in err


def _break_interpreter(monkeypatch):
    class BrokenInterpreter:
        globals_env = None

        def run(self, program, env):
            raise ValueError("kaboom")

    monkeypatch.setattr(cli, "Interpreter", BrokenInterpreter)


def test_cli_internal_error_has_no_traceback(capsys, monkeypatch, tmp_path):
    _break_interpreter(monkeypatch)
    path = _write(tmp_path, "ok.rn", 'print("x")\n')
    assert cli.main(["run", path]) == 1
    err = capsys.readouterr().err
    assert "internal error: ValueError: kaboom" in err
    assert "bug in the Renixx interpreter" in err
    assert "Traceback" not in err


def test_cli_debug_flag_shows_traceback(capsys, monkeypatch, tmp_path):
    _break_interpreter(monkeypatch)
    path = _write(tmp_path, "ok.rn", 'print("x")\n')
    assert cli.main(["run", "--debug", path]) == 1
    err = capsys.readouterr().err
    assert "internal error: ValueError: kaboom" in err
    assert "Traceback" in err
