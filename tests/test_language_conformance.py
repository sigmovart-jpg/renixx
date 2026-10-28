"""Behavioral compatibility tests for documented Renixx language features."""
import os
import sys

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "src"))

from renixx.errors import ParseError, RuntimeError as RenixxRuntimeError
from renixx.formatter import format_source
from renixx.interpreter import Interpreter
from renixx.parser import parse


def run_program(source):
    interpreter = Interpreter()
    interpreter.run(parse(source))
    return interpreter.output


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("print(2 + 3 * 4)", ["14"]),
        ("print((2 + 3) * 4)", ["20"]),
        ("print(2 ** 3)", ["8"]),
        ("print(17 % 5)", ["2"]),
        ("print(-3 + 8 / 2)", ["1.0"]),
    ],
)
def test_arithmetic_and_operator_precedence(source, expected):
    assert run_program(source) == expected


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        (
            "let value = 10\n"
            "if true { let value = 2; print(value) }\n"
            "print(value)",
            ["2", "10"],
        ),
        (
            "fn make_adder(amount) {\n"
            "  fn add(value) { return amount + value }\n"
            "  return add\n"
            "}\n"
            "let add_five = make_adder(5)\n"
            "print(add_five(3), add_five(7))",
            ["8 12"],
        ),
        (
            "let value = 10\n"
            "fn identity(value) { return value }\n"
            "print(identity(3), value)",
            ["3 10"],
        ),
    ],
)
def test_scopes_closures_and_shadowing(source, expected):
    assert run_program(source) == expected


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        (
            "fn describe(name, greeting = \"hello\") {\n"
            "  return greeting + \" \" + name\n"
            "}\n"
            "print(describe(\"Renixx\"))\n"
            "print(describe(\"Renixx\", \"welcome\"))",
            ["hello Renixx", "welcome Renixx"],
        ),
        (
            "fn total(first, ...rest) { return first + sum(rest) }\n"
            "print(total(2, 3, 5))",
            ["10"],
        ),
        (
            "fn subtract(left, right) { return left - right }\n"
            "print(subtract(right = 3, left = 10))",
            ["7"],
        ),
        (
            "fn classify(value) {\n"
            "  if value > 0 { return \"positive\" }\n"
            "  return \"not positive\"\n"
            "}\n"
            "print(classify(4), classify(0))",
            ["positive not positive"],
        ),
    ],
)
def test_functions_arguments_defaults_and_returns(source, expected):
    assert run_program(source) == expected


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        (
            "let values = [10, 20, 30, 40]\n"
            "print(values[0], values[-1])",
            ["10 40"],
        ),
        (
            "let values = [0, 1, 2, 3, 4]\n"
            "print(values[:3], values[2:], values[::2])",
            ["[0, 1, 2] [2, 3, 4] [0, 2, 4]"],
        ),
        (
            "let config = {\"mode\": \"safe\", \"retries\": 3}\n"
            "print(config[\"mode\"], config[\"retries\"])",
            ["safe 3"],
        ),
        (
            "let values = [1, 2, 3, 4, 5]\n"
            "print([value * value for value in values if value > 2])",
            ["[9, 16, 25]"],
        ),
        (
            "let values = [1, 2, 3]\n"
            "print({value: value * 10 for value in values})",
            ["{1: 10, 2: 20, 3: 30}"],
        ),
        (
            "let left = [1, 2]\n"
            "let right = [...left, 3]\n"
            "print(right)",
            ["[1, 2, 3]"],
        ),
    ],
)
def test_lists_dictionaries_slices_and_comprehensions(source, expected):
    assert run_program(source) == expected


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        (
            "let total = 0\n"
            "for value in [1, 2, 3, 4, 5] {\n"
            "  if value == 2 { continue }\n"
            "  if value == 5 { break }\n"
            "  total += value\n"
            "}\n"
            "print(total)",
            ["8"],
        ),
        (
            "let n = 0\n"
            "let total = 0\n"
            "while n < 6 {\n"
            "  n += 1\n"
            "  if n == 2 { continue }\n"
            "  if n == 5 { break }\n"
            "  total += n\n"
            "}\n"
            "print(total)",
            ["8"],
        ),
        (
            "let total = 0\n"
            "for (let index = 0; index < 5; index = index + 1) {\n"
            "  total += index\n"
            "}\n"
            "print(total)",
            ["10"],
        ),
    ],
)
def test_loops_break_and_continue(source, expected):
    assert run_program(source) == expected


def test_caught_exception_runs_finally_and_preserves_output_order():
    source = (
        "try {\n"
        "  print(\"before\")\n"
        "  throw \"boom\"\n"
        "} catch error {\n"
        "  print(error)\n"
        "} finally {\n"
        "  print(\"cleanup\")\n"
        "}\n"
    )
    assert run_program(source) == [
        "before",
        "boom",
        "cleanup",
    ]


@pytest.mark.parametrize(
    ("source", "error_type", "line", "message"),
    [
        ("let value = 1\nprint(missing)", RenixxRuntimeError, 2, "Undefined variable"),
        ("let value = 1\nprint(2 + )", ParseError, 2, "Unexpected token"),
    ],
)
def test_errors_report_expected_type_line_and_message(
    source, error_type, line, message
):
    with pytest.raises(error_type, match=message) as error:
        run_program(source)

    assert error.value.line == line


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ('import "math" as numeric\nprint(numeric.sqrt(81))', ["9.0"]),
        ('from "math" import sqrt\nprint(sqrt(49))', ["7.0"]),
    ],
)
def test_builtin_module_import_forms(source, expected):
    assert run_program(source) == expected


def test_file_module_import_exposes_module_values(tmp_path, monkeypatch):
    module_path = tmp_path / "helpers.rn"
    module_path.write_text(
        "let answer = 42\nfn double(value) { return value * 2 }\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    source = 'import "helpers.rn" as helpers\nprint(helpers.answer, helpers.double(6))'

    assert run_program(source) == ["42 12"]


def test_file_module_import_can_select_names(tmp_path, monkeypatch):
    module_path = tmp_path / "helpers.rn"
    module_path.write_text(
        "let answer = 42\nfn double(value) { return value * 2 }\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    source = 'from "helpers.rn" import answer, double\nprint(answer, double(5))'

    assert run_program(source) == ["42 10"]


@pytest.mark.parametrize(
    "source",
    [
        "let total=0\nfor value in [1,2,3] { total += value }\nprint(total)",
        "fn square(value){return value*value}\nprint([square(x) for x in [2,3]])",
    ],
)
def test_formatting_preserves_behavior_and_formatted_code_reparses(source):
    formatted = format_source(source)
    reformatted = format_source(formatted)
    assert reformatted == formatted

    parse(formatted)
    assert run_program(formatted) == run_program(source)
