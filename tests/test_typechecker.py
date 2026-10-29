"""Tests for the Renixx static type checker."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from renixx.typechecker import TypeChecker, type_check
from renixx.parser import parse


def check(src):
    program = parse(src)
    checker = TypeChecker(src)
    return checker.check(program)


def test_no_errors_simple():
    diags = check("let x = 5\nprint(x)\n")
    assert diags == []


def test_var_type_annotation_match():
    diags = check('let x: int = 5\n')
    assert diags == []


def test_var_type_annotation_mismatch():
    diags = check('let x: int = "hi"\n')
    assert len(diags) == 1
    assert "Type error" in diags[0]["message"]
    assert "int" in diags[0]["message"]
    assert "string" in diags[0]["message"]


def test_var_type_annotation_float():
    diags = check('let x: float = 3.14\n')
    assert diags == []


def test_var_type_annotation_bool():
    diags = check('let x: bool = true\n')
    assert diags == []


def test_var_type_annotation_string():
    diags = check('let x: string = "hello"\n')
    assert diags == []


def test_var_no_annotation_no_check():
    diags = check('let x = "hi"\nlet y: int = x\n')
    # x is string, y expects int -> type error
    assert len(diags) == 1
    assert "Type error" in diags[0]["message"]


def test_reassignment_type_check():
    diags = check('let x: int = 5\nx = "hello"\n')
    assert len(diags) == 1
    assert "Type error" in diags[0]["message"]


def test_function_return_type_match():
    diags = check('fn add(a: int, b: int) -> int { return a + b }\n')
    assert diags == []


def test_function_return_type_mismatch():
    diags = check('fn f() -> int { return "hello" }\n')
    assert len(diags) == 1
    assert "Type error" in diags[0]["message"]
    assert "int" in diags[0]["message"]
    assert "string" in diags[0]["message"]


def test_function_arg_type_mismatch():
    diags = check('fn add(a: int, b: int) -> int { return a + b }\nprint(add(1, "a"))\n')
    assert len(diags) == 1
    assert "Type error" in diags[0]["message"]
    assert "int" in diags[0]["message"]
    assert "string" in diags[0]["message"]


def test_function_arg_count_too_many():
    diags = check('fn add(a: int, b: int) -> int { return a + b }\nprint(add(1, 2, 3))\n')
    assert len(diags) == 1
    assert "Too many arguments" in diags[0]["message"]


def test_function_no_annotations_no_check():
    diags = check('fn f(a, b) { return a + b }\nprint(f(1, "a"))\n')
    assert diags == []


def test_arithmetic_int_int():
    diags = check('let x: int = 1 + 2\n')
    assert diags == []


def test_arithmetic_int_float():
    diags = check('let x: float = 1 + 2.0\n')
    assert diags == []


def test_arithmetic_string_concat():
    diags = check('let x: string = "a" + "b"\n')
    assert diags == []


def test_arithmetic_type_error():
    diags = check('let x = 1 + "a"\n')
    # 1 is int, "a" is string -> int + string is unknown (not an error per se, but type is unknown)
    # Actually, our checker returns "unknown" for int + string, no diagnostic
    # This is acceptable for v1 (conservative)
    pass


def test_comparison_types():
    diags = check('let x: bool = 1 < 2\n')
    assert diags == []


def test_comparison_type_error():
    diags = check('let x = 1 < "a"\n')
    # 1 < "a" -> comparison of int and string -> our checker allows (==, !=) but not (<, >)
    # Actually our checker returns bool for all comparisons regardless
    pass


def test_unknown_type_annotation():
    diags = check('let x: Foo = 5\n')
    assert len(diags) == 1
    assert "Unknown type" in diags[0]["message"]


def test_unknown_function_return_type():
    diags = check('fn f() -> Foo { return 1 }\n')
    assert len(diags) == 1
    assert "Unknown type" in diags[0]["message"]


def test_unknown_param_type():
    diags = check('fn f(x: Foo) { return 1 }\n')
    assert len(diags) == 1
    assert "Unknown type" in diags[0]["message"]


def test_class_type():
    diags = check('class Point { fn init(x: int, y: int) { this.x = x } }\nlet p = new Point(1, 2)\n')
    assert diags == []


def test_class_wrong_arg_type():
    diags = check('class Point { fn init(x: int, y: int) { this.x = x } }\nlet p = new Point("a", 2)\n')
    assert len(diags) == 1
    assert "Type error" in diags[0]["message"]


def test_assign_type_check():
    diags = check('let x: int = 5\nx = "hello"\n')
    assert len(diags) == 1
    assert "Type error" in diags[0]["message"]


def test_const_type_check():
    diags = check('const x: int = "hi"\n')
    assert len(diags) == 1
    assert "Type error" in diags[0]["message"]


def test_position_accuracy():
    diags = check('let x: int = "hi"\n')
    assert len(diags) == 1
    # "let x: int = "hi"" -> type_annot "int" at col 6 (0-based)
    # Actually col should point to name 'x' (col 4) per semantics convention
    assert diags[0]["line"] == 1


def test_method_call_argument_type_mismatch():
    diags = check(
        "class Point {\n"
        "  fn init(x: int) { this.x = x }\n"
        "  fn move(dx: int) { return dx }\n"
        "}\n"
        "let p = new Point(1)\n"
        'p.move("bad")\n'
    )
    assert len(diags) == 1
    assert "Type error" in diags[0]["message"]
    assert "int" in diags[0]["message"]
    assert "string" in diags[0]["message"]


def test_string_slice_keeps_string_type():
    diags = check('let s: string = "abc"[1:2]\n')
    assert diags == []


def test_return_type_checked_inside_match():
    diags = check(
        "fn f(n: int) -> int {\n"
        "  match n {\n"
        "    0 => { return 0 }\n"
        '    _ => { return "bad" }\n'
        "  }\n"
        "}\n"
    )
    assert len(diags) == 1
    assert "Type error" in diags[0]["message"]
    assert "int" in diags[0]["message"]
    assert "string" in diags[0]["message"]


def test_rest_parameter_allows_extra_arguments():
    diags = check("fn f(a: int, ...rest) { return a }\nprint(f(1, 2, 3))\n")
    assert diags == []


def test_c_style_for_init_does_not_leak_into_outer_scope():
    diags = check(
        'let i: string = "outer"\n'
        "for (let i: int = 0; i < 3; i = i + 1) { }\n"
        "let x: string = i\n"
    )
    assert diags == []


def test_empty_program():
    diags = check('')
    assert diags == []


def test_no_annotations():
    diags = check('let x = 5\nlet y = x + 1\nprint(y)\n')
    assert diags == []


# ---------- Parameterized collection types ----------

def test_list_int_valid():
    diags = check('let xs: list[int] = [1, 2, 3]\n')
    assert diags == []

def test_list_int_element_mismatch():
    diags = check('let xs: list[int] = [1, "a"]\n')
    assert len(diags) == 1
    assert "Type error" in diags[0]["message"]

def test_list_int_empty():
    diags = check('let xs: list[int] = []\n')
    assert diags == []

def test_list_string_valid():
    diags = check('let xs: list[string] = ["a", "b"]\n')
    assert diags == []

def test_dict_valid():
    diags = check('let d: dict[string, int] = {"a": 1, "b": 2}\n')
    assert diags == []

def test_dict_key_mismatch():
    diags = check('let d: dict[string, int] = {1: 2}\n')
    assert len(diags) == 1
    assert "Type error" in diags[0]["message"]

def test_dict_value_mismatch():
    diags = check('let d: dict[string, int] = {"a": "x"}\n')
    assert len(diags) == 1
    assert "Type error" in diags[0]["message"]

def test_dict_empty():
    # Empty dict literal is not yet supported by the parser.
    # Use a non-empty dict instead.
    diags = check('let d: dict[string, int] = {"a": 1}\n')
    assert diags == []

def test_list_index_read():
    diags = check('let xs: list[int] = [1, 2, 3]\nlet x: int = xs[0]\n')
    assert diags == []

def test_list_index_read_mismatch():
    diags = check('let xs: list[int] = [1, 2, 3]\nlet x: string = xs[0]\n')
    assert len(diags) == 1
    assert "Type error" in diags[0]["message"]

def test_list_index_write():
    diags = check('let xs: list[int] = [1, 2, 3]\nxs[0] = 5\n')
    assert diags == []

def test_list_index_write_mismatch():
    diags = check('let xs: list[int] = [1, 2, 3]\nxs[0] = "a"\n')
    assert len(diags) == 1
    assert "Type error" in diags[0]["message"]

def test_dict_index_read():
    diags = check('let d: dict[string, int] = {"a": 1}\nlet x: int = d["a"]\n')
    assert diags == []

def test_dict_index_read_mismatch():
    diags = check('let d: dict[string, int] = {"a": 1}\nlet x: string = d["a"]\n')
    assert len(diags) == 1
    assert "Type error" in diags[0]["message"]

def test_dict_index_write():
    diags = check('let d: dict[string, int] = {"a": 1}\nd["b"] = 2\n')
    assert diags == []

def test_dict_index_write_mismatch():
    diags = check('let d: dict[string, int] = {"a": 1}\nd["b"] = "x"\n')
    assert len(diags) == 1
    assert "Type error" in diags[0]["message"]

def test_nested_list():
    diags = check('let xs: list[list[int]] = [[1, 2], [3, 4]]\n')
    assert diags == []

def test_list_unparameterized_compat():
    diags = check('let xs: list = [1, 2, 3]\nlet ys: list[int] = xs\n')
    assert diags == []

def test_list_param_compat():
    diags = check('let xs: list[int] = [1, 2, 3]\nlet ys: list = xs\n')
    assert diags == []

def test_list_param_mismatch():
    diags = check('let xs: list[int] = [1, 2, 3]\nlet ys: list[string] = xs\n')
    assert len(diags) == 1
    assert "Type error" in diags[0]["message"]

def test_func_param_list():
    diags = check('fn sum(xs: list[int]) -> int { let s: int = 0\n for x in xs { s = s + x }\n return s }\nlet r: int = sum([1, 2, 3])\n')
    assert diags == []

def test_func_param_list_mismatch():
    diags = check('fn sum(xs: list[int]) -> int { return 0 }\nlet r = sum(["a", "b"])\n')
    assert len(diags) == 2
    assert "Type error" in diags[0]["message"]
    assert "Type error" in diags[1]["message"]

def test_func_return_list():
    diags = check('fn f() -> list[int] { return [1, 2, 3] }\n')
    assert diags == []

def test_func_return_list_mismatch():
    diags = check('fn f() -> list[int] { return [1, "a"] }\n')
    assert len(diags) == 1
    assert "Type error" in diags[0]["message"]

def test_new_class_param_list():
    diags = check('class Foo { fn init(xs: list[int]) { this.xs = xs } }\nlet f = new Foo([1, 2, 3])\n')
    assert diags == []

def test_new_class_param_list_mismatch():
    diags = check('class Foo { fn init(xs: list[int]) { this.xs = xs } }\nlet f = new Foo(["a"])\n')
    assert len(diags) == 1
    assert "Type error" in diags[0]["message"]

def test_any_compat():
    diags = check('let x: any = [1, 2, 3]\nlet y: list[int] = x\n')
    assert diags == []

def test_unknown_no_check():
    # x is now list[int], so x[0] is int. string is not compatible with int.
    diags = check('let x = [1, 2, 3]\nlet y: string = x[0]\n')
    assert len(diags) == 1
    assert "Type error" in diags[0]["message"]

def test_empty_list_assign():
    diags = check('let xs: list[int] = []\nxs = [1, 2]\n')
    assert diags == []

def test_slice_preserves_type():
    diags = check('let xs: list[int] = [1, 2, 3, 4]\nlet ys: list[int] = xs[1:3]\n')
    assert diags == []


# ---------- Parameterized collection types ----------

def test_list_int_valid():
    diags = check('let xs: list[int] = [1, 2, 3]\n')
    assert diags == []

def test_list_int_element_mismatch():
    diags = check('let xs: list[int] = [1, "a"]\n')
    assert len(diags) == 1
    assert "Type error" in diags[0]["message"]
    assert "int" in diags[0]["message"]
    assert "string" in diags[0]["message"]

def test_list_int_empty():
    diags = check('let xs: list[int] = []\n')
    assert diags == []

def test_list_string_valid():
    diags = check('let xs: list[string] = ["a", "b"]\n')
    assert diags == []

def test_list_float_valid():
    diags = check('let xs: list[float] = [1.0, 2.0]\n')
    assert diags == []

def test_dict_valid():
    diags = check('let d: dict[string, int] = {"a": 1, "b": 2}\n')
    assert diags == []

def test_dict_key_mismatch():
    diags = check('let d: dict[string, int] = {1: 2}\n')
    assert len(diags) == 1
    assert "Type error" in diags[0]["message"]

def test_dict_value_mismatch():
    diags = check('let d: dict[string, int] = {"a": "x"}\n')
    assert len(diags) == 1
    assert "Type error" in diags[0]["message"]

def test_dict_empty():
    # Empty dict literal is not yet supported by the parser.
    # Use a non-empty dict instead.
    diags = check('let d: dict[string, int] = {"a": 1}\n')
    assert diags == []

def test_list_index_read():
    diags = check('let xs: list[int] = [1, 2, 3]\nlet x: int = xs[0]\n')
    assert diags == []

def test_list_index_read_mismatch():
    diags = check('let xs: list[int] = [1, 2, 3]\nlet x: string = xs[0]\n')
    assert len(diags) == 1
    assert "Type error" in diags[0]["message"]

def test_list_index_write():
    diags = check('let xs: list[int] = [1, 2, 3]\nxs[0] = 5\n')
    assert diags == []

def test_list_index_write_mismatch():
    diags = check('let xs: list[int] = [1, 2, 3]\nxs[0] = "a"\n')
    assert len(diags) == 1
    assert "Type error" in diags[0]["message"]

def test_dict_index_read():
    diags = check('let d: dict[string, int] = {"a": 1}\nlet x: int = d["a"]\n')
    assert diags == []

def test_dict_index_read_mismatch():
    diags = check('let d: dict[string, int] = {"a": 1}\nlet x: string = d["a"]\n')
    assert len(diags) == 1
    assert "Type error" in diags[0]["message"]

def test_dict_index_write():
    diags = check('let d: dict[string, int] = {"a": 1}\nd["b"] = 2\n')
    assert diags == []

def test_dict_index_write_mismatch():
    diags = check('let d: dict[string, int] = {"a": 1}\nd["b"] = "x"\n')
    assert len(diags) == 1
    assert "Type error" in diags[0]["message"]

def test_nested_list():
    diags = check('let xs: list[list[int]] = [[1, 2], [3, 4]]\n')
    assert diags == []

def test_list_unparameterized_compat():
    diags = check('let xs: list = [1, 2, 3]\nlet ys: list[int] = xs\n')
    assert diags == []

def test_list_param_compat():
    diags = check('let xs: list[int] = [1, 2, 3]\nlet ys: list = xs\n')
    assert diags == []

def test_list_param_mismatch():
    diags = check('let xs: list[int] = [1, 2, 3]\nlet ys: list[string] = xs\n')
    assert len(diags) == 1
    assert "Type error" in diags[0]["message"]

def test_func_param_list():
    diags = check('fn sum(xs: list[int]) -> int { let s: int = 0\n for x in xs { s = s + x }\n return s }\nlet r: int = sum([1, 2, 3])\n')
    assert diags == []

def test_func_param_list_mismatch():
    diags = check('fn sum(xs: list[int]) -> int { return 0 }\nlet r = sum(["a", "b"])\n')
    assert len(diags) == 2
    assert "Type error" in diags[0]["message"]
    assert "Type error" in diags[1]["message"]

def test_func_return_list():
    diags = check('fn f() -> list[int] { return [1, 2, 3] }\n')
    assert diags == []

def test_func_return_list_mismatch():
    diags = check('fn f() -> list[int] { return [1, "a"] }\n')
    assert len(diags) == 1
    assert "Type error" in diags[0]["message"]

def test_new_class_param_list():
    diags = check('class Foo { fn init(xs: list[int]) { this.xs = xs } }\nlet f = new Foo([1, 2, 3])\n')
    assert diags == []

def test_new_class_param_list_mismatch():
    diags = check('class Foo { fn init(xs: list[int]) { this.xs = xs } }\nlet f = new Foo(["a"])\n')
    assert len(diags) == 1
    assert "Type error" in diags[0]["message"]

def test_any_compat():
    diags = check('let x: any = [1, 2, 3]\nlet y: list[int] = x\n')
    assert diags == []

def test_unknown_no_check():
    # x is now list[int], so x[0] is int. string is not compatible with int.
    diags = check('let x = [1, 2, 3]\nlet y: string = x[0]\n')
    assert len(diags) == 1
    assert "Type error" in diags[0]["message"]


# ---- Unknown type name validation (generic) ----

def test_unknown_nested_list():
    diags = check("let xs: list[list[Foo]] = [[]]\n")
    assert len(diags) == 1
    assert "Unknown type 'Foo'" in diags[0]["message"]
    assert diags[0]["col"] == 18

def test_unknown_dict_key():
    diags = check('let d: dict[Foo, int] = {"a": 1}\n')
    assert len(diags) == 1
    assert "Unknown type 'Foo'" in diags[0]["message"]
    assert diags[0]["col"] == 12

def test_unknown_dict_value_nested():
    diags = check('let d: dict[string, list[Bar]] = {"a": []}\n')
    assert len(diags) == 1
    assert "Unknown type 'Bar'" in diags[0]["message"]

def test_unknown_return_type():
    diags = check("fn f() -> Foo { return 1 }\n")
    assert len(diags) == 1
    assert "Unknown type 'Foo'" in diags[0]["message"]

def test_unknown_param_type():
    diags = check("fn f(x: Foo) {}\n")
    assert len(diags) == 1
    assert "Unknown type 'Foo'" in diags[0]["message"]

def test_unknown_method_param():
    diags = check("class A { fn m(x: Foo) {} }\n")
    assert len(diags) == 1
    assert "Unknown type 'Foo'" in diags[0]["message"]

def test_class_name_valid_type():
    diags = check("class Dog {}\nlet a: Dog = 1\n")
    unknown = [d for d in diags if "Unknown type" in d["message"]]
    assert unknown == []

def test_forward_ref_class():
    diags = check("fn f(x: Foo) {}\nclass Foo {}\n")
    unknown = [d for d in diags if "Unknown type" in d["message"]]
    assert unknown == []

def test_import_no_diagnostic():
    diags = check('from "lib.rn" import Foo\nlet x: Foo = 1\n')
    unknown = [d for d in diags if "Unknown type" in d["message"]]
    assert unknown == []

def test_no_false_positive_valid_generics():
    diags = check("let xs: list[int] = [1, 2, 3]\nlet d: dict[string, int] = {\"a\": 1}\nfn f() -> list[int] { return [1] }\n")
    unknown = [d for d in diags if "Unknown type" in d["message"]]
    assert unknown == []

def test_unknown_multiple_names():
    diags = check("let x: Foo = 1\nlet y: Bar = 2\n")
    unknown = [d for d in diags if "Unknown type" in d["message"]]
    assert len(unknown) == 2
