import os, subprocess, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable
SRC = os.path.join(ROOT, "src")
GEN = os.path.join(ROOT, "examples", "generics")

def run_cli(*args):
    env = dict(os.environ)
    env["PYTHONPATH"] = SRC
    return subprocess.run([PY, "-m", "renixx", *args], capture_output=True, text=True, env=env, cwd=ROOT)

def test_list_int_ok():
    r = run_cli("run", os.path.join(GEN, "list_int_ok.rn"))
    assert r.returncode == 0

def test_list_int_bad_diagnostic():
    r = run_cli("check", os.path.join(GEN, "list_int_bad.rn"))
    assert r.returncode != 0

def test_dict_ok():
    r = run_cli("run", os.path.join(GEN, "dict_ok.rn"))
    assert r.returncode == 0

def test_dict_bad_value_diagnostic():
    r = run_cli("check", os.path.join(GEN, "dict_bad_value.rn"))
    assert r.returncode != 0

def test_dict_bad_key_diagnostic():
    r = run_cli("check", os.path.join(GEN, "dict_bad_key.rn"))
    assert r.returncode != 0

def test_nested_ok():
    r = run_cli("run", os.path.join(GEN, "nested_ok.rn"))
    assert r.returncode == 0

def test_nested_bad_diagnostic():
    r = run_cli("check", os.path.join(GEN, "nested_bad.rn"))
    assert r.returncode != 0

def test_empty_ok():
    r = run_cli("run", os.path.join(GEN, "empty_ok.rn"))
    assert r.returncode == 0

def test_func_ok():
    r = run_cli("run", os.path.join(GEN, "func_ok.rn"))
    assert r.returncode == 0

def test_reassign_bad_diagnostic():
    r = run_cli("check", os.path.join(GEN, "reassign_bad.rn"))
    assert r.returncode != 0

def test_old_int_ok():
    r = run_cli("run", os.path.join(GEN, "old_int_ok.rn"))
    assert r.returncode == 0
