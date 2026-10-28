import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from renixx.semantics import analyze


def _diagnostics(source):
    diagnostics, parse_error = analyze(source)
    assert parse_error is None, parse_error
    return diagnostics


def _messages(source):
    return [d["message"] for d in _diagnostics(source)]


def _undefined_names(source):
    return [
        d["message"][len("Undefined variable '"):-1]
        for d in _diagnostics(source)
        if d["message"].startswith("Undefined variable '")
    ]


# --- valid bindings -------------------------------------------------------

def test_binding_visible_in_body():
    src = 'match 1 { x => { print(x) } }'
    assert _diagnostics(src) == []


def test_binding_visible_in_guard():
    src = 'match 5 { x if x > 3 => { print(x) } _ => { print(0) } }'
    assert _diagnostics(src) == []


def test_wildcard_is_not_a_binding():
    src = 'match 1 { _ => { print("any") } }'
    assert _diagnostics(src) == []


def test_each_case_has_its_own_binding():
    src = 'match 1 { a => { print(a) } b => { print(b) } }'
    assert _diagnostics(src) == []


def test_same_name_in_several_cases():
    src = 'match 1 { x => { print(x) } x if x > 0 => { print(x) } }'
    assert _diagnostics(src) == []


def test_binding_visible_in_nested_constructs():
    src = """
match 1 {
  x => {
    if x > 0 { print(x) }
    for i in [1, 2] { print(x, i) }
  }
}
"""
    assert _diagnostics(src) == []


def test_nested_match_bindings():
    src = 'match 1 { x => { match 2 { y => { print(x, y) } } } }'
    assert _diagnostics(src) == []


def test_literal_and_default_cases():
    src = """
match 1 {
  1 => { print("one") }
  2 => { print("two") }
  default => { print("other") }
}
"""
    assert _diagnostics(src) == []


# --- real undefined names are still reported ------------------------------

def test_binding_does_not_leak_after_match():
    src = 'match 1 { x => { print(x) } }\nprint(x)'
    assert _undefined_names(src) == ["x"]
    assert _diagnostics(src)[0]["line"] == 2


def test_binding_does_not_leak_into_next_case():
    src = 'match 1 { x => { print(x) } _ => { print(x) } }'
    assert _undefined_names(src) == ["x"]


def test_binding_does_not_leak_into_next_guard():
    src = 'match 1 { x => { print(x) } _ if x > 0 => { print(0) } }'
    assert _undefined_names(src) == ["x"]


def test_unknown_name_in_guard_is_reported():
    src = 'match 1 { x if missing > 0 => { print(x) } }'
    assert _undefined_names(src) == ["missing"]


def test_unknown_name_in_body_is_reported():
    src = 'match 1 { x => { print(x, nope) } }'
    assert _undefined_names(src) == ["nope"]


def test_match_subject_uses_outer_scope():
    src = 'match unknown { x => { print(x) } }'
    assert _undefined_names(src) == ["unknown"]


def test_non_identifier_pattern_is_not_a_binding():
    src = 'match 1 { y + 1 => { print(1) } }'
    assert _undefined_names(src) == ["y"]


def test_unrelated_undefined_name_still_reported_without_match():
    src = 'let x = 1\nprint(y)'
    assert _undefined_names(src) == ["y"]
