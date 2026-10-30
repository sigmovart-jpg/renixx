import os
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from renixx.cli import VERSION, main, print_diagnostics

SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")


def _write(tmp_path, name, source):
    path = tmp_path / name
    path.write_text(source, encoding="utf-8")
    return str(path)


# --- successful execution -------------------------------------------------

def test_version(capsys):
    assert main(["version"]) == 0
    assert VERSION in capsys.readouterr().out


def test_help_lists_check_options(capsys):
    assert main(["help"]) == 0
    out = capsys.readouterr().out
    assert "check <file>" in out
    assert "--syntax-only" in out


def test_run_file_success(capsys, tmp_path):
    path = _write(tmp_path, "ok.rn", 'print("hello")\n')
    assert main([path]) == 0
    captured = capsys.readouterr()
    assert captured.out.strip() == "hello"
    assert captured.err == ""


def test_run_command_success(capsys, tmp_path):
    path = _write(tmp_path, "math.rn", "print(1 + 2 * 3)\n")
    assert main(["run", path]) == 0
    assert capsys.readouterr().out.strip() == "7"


# --- errors ---------------------------------------------------------------

def test_run_syntax_error_has_location_and_no_traceback(capsys, tmp_path):
    path = _write(tmp_path, "syntax.rn", "let x =\n")
    assert main(["run", path]) == 1
    err = capsys.readouterr().err
    assert path in err
    assert "ParseError" in err
    assert "^" in err
    assert "Traceback" not in err


def test_run_runtime_error_has_location_and_no_traceback(capsys, tmp_path):
    path = _write(tmp_path, "runtime.rn", "print(undefined_name)\n")
    assert main(["run", path]) == 1
    err = capsys.readouterr().err
    assert path in err
    assert "RuntimeError" in err
    assert "undefined_name" in err
    assert "^" in err
    assert "Traceback" not in err


def test_run_missing_file(capsys, tmp_path):
    missing = str(tmp_path / "nope.rn")
    assert main(["run", missing]) == 1
    err = capsys.readouterr().err
    assert "file not found" in err
    assert missing in err


def test_unknown_command(capsys):
    assert main(["frobnicate"]) == 1
    assert "unknown command" in capsys.readouterr().err


def test_module_entry_point_propagates_exit_code(tmp_path):
    path = _write(tmp_path, "bad.rn", "let x =\n")
    env = dict(os.environ)
    env["PYTHONPATH"] = SRC
    result = subprocess.run(
        [sys.executable, "-m", "renixx", "check", path],
        capture_output=True, text=True, env=env,
    )
    assert result.returncode == 1
    assert "ParseError" in result.stderr


# --- check ----------------------------------------------------------------

def test_check_success(capsys, tmp_path):
    path = _write(tmp_path, "clean.rn", "let x = 1\nprint(x)\n")
    assert main(["check", path]) == 0
    captured = capsys.readouterr()
    assert "%s: OK" % path in captured.out
    assert "Traceback" not in captured.err


def test_check_syntax_only_skips_semantics(capsys, tmp_path):
    path = _write(tmp_path, "semantic_bad.rn", "print(undefined_name)\n")
    assert main(["check", path, "--syntax-only"]) == 0
    assert "%s: OK" % path in capsys.readouterr().out


def test_check_reports_semantic_errors(capsys, tmp_path):
    path = _write(tmp_path, "semantic_bad.rn", "print(undefined_name)\n")
    assert main(["check", path]) == 1
    err = capsys.readouterr().err
    assert path in err
    assert "SemanticError" in err
    assert "undefined_name" in err
    assert "Traceback" not in err


def test_check_parameterized_annotation_is_not_an_error(capsys, tmp_path):
    path = _write(tmp_path, "generic.rn", "let xs: list[int] = [1, 2]\nprint(xs)\n")
    assert main(["check", path]) == 0
    assert "%s: OK" % path in capsys.readouterr().out


def test_check_missing_file(capsys, tmp_path):
    missing = str(tmp_path / "nope.rn")
    assert main(["check", missing]) == 1
    assert "file not found" in capsys.readouterr().err


def test_check_unknown_option(capsys, tmp_path):
    path = _write(tmp_path, "ok.rn", "print(1)\n")
    assert main(["check", path, "--bogus"]) == 1
    assert "unknown option" in capsys.readouterr().err


# --- diagnostic rendering -------------------------------------------------

def test_print_diagnostics_type_error_format(capsys):
    diagnostics = [{
        "line": 2, "col": 4, "end_col": 9,
        "message": "expected int, got string",
        "severity": 1, "source": "typechecker",
    }]
    src = "let x = 1\n    let y = x\n"
    print_diagnostics(diagnostics, "sample.rn", src)
    err = capsys.readouterr().err
    assert "sample.rn:2:5: TypeError: expected int, got string" in err
    assert "    let y = x" in err
    assert "^" in err


def test_print_diagnostics_warning_category(capsys):
    diagnostics = [{
        "line": 1, "col": 0, "end_col": 3,
        "message": "Unused variable 'x'",
        "severity": 2, "source": "semantic",
    }]
    print_diagnostics(diagnostics, "warn.rn", "let x = 1\n")
    err = capsys.readouterr().err
    assert "warn.rn:1:1: SemanticWarning: Unused variable 'x'" in err


def test_print_diagnostics_without_position(capsys):
    diagnostics = [{
        "line": 0, "col": 0,
        "message": "internal note",
        "severity": 1, "source": "semantic",
    }]
    print_diagnostics(diagnostics, "x.rn")
    err = capsys.readouterr().err
    assert "x.rn: SemanticError: internal note" in err


# --- fmt ------------------------------------------------------------------

def test_fmt_prints_formatted_source(capsys, tmp_path):
    path = _write(tmp_path, "fmt.rn", "let x=1\n")
    assert main(["fmt", path]) == 0
    assert "let x = 1" in capsys.readouterr().out


def test_fmt_reports_syntax_error(capsys, tmp_path):
    path = _write(tmp_path, "fmt_bad.rn", "let x =\n")
    assert main(["fmt", path]) == 1
    err = capsys.readouterr().err
    assert path in err
    assert "ParseError" in err
    assert "Traceback" not in err


def test_fmt_write_preserves_list_pattern_match_program(tmp_path):
    from renixx.formatter import format_source
    from renixx.interpreter import Interpreter
    from renixx.parser import parse

    source = (
        "let x = [1, 2]\n"
        "match x {\n"
        "  [a] => { print(a) }\n"
        "  [a, b] => { print(a, b) }\n"
        "  _ => { print(0) }\n"
        "}\n"
    )
    path = _write(tmp_path, "match_list_patterns.rn", source)

    assert main(["fmt", path, "-w"]) == 0
    formatted = open(path, encoding="utf-8").read()
    parse(formatted)
    assert format_source(formatted) == formatted

    original = Interpreter()
    original.run(parse(source))
    after_format = Interpreter()
    after_format.run(parse(formatted))
    assert after_format.output == original.output == ["1 2"]
