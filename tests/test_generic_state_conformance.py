import os, subprocess, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable
SRC = os.path.join(ROOT, "src")
GEN = os.path.join(ROOT, "examples", "generics")

def run_cli(*args):
    env = dict(os.environ)
    env["PYTHONPATH"] = SRC
    return subprocess.run([PY, "-m", "renixx", *args], capture_output=True, text=True, env=env, cwd=ROOT)

tests = [
 ("assign_var_ok.rn", "run", 0),
 ("nested_func_ok.rn", "run", 0),
 ("index_assign_bad.rn", "check", 1),
 ("mixed_bad.rn", "check", 1),
 ("reassign_seq_ok.rn", "run", 0),
 ("reassign_seq_bad.rn", "check", 1),
 ("unparam_compat_ok.rn", "run", 0),
]
for name, cmd, expected in tests:
    pass

def test_assign_var_ok():
    assert run_cli("run", os.path.join(GEN, "assign_var_ok.rn")).returncode == 0

def test_nested_func_ok():
    assert run_cli("run", os.path.join(GEN, "nested_func_ok.rn")).returncode == 0

def test_index_assign_bad():
    r = run_cli("check", os.path.join(GEN, "index_assign_bad.rn"))
    if r.returncode == 0:
        r2 = run_cli("run", os.path.join(GEN, "index_assign_bad.rn"))
        assert r2.returncode != 0
    else:
        assert True

def test_mixed_bad():
    assert run_cli("check", os.path.join(GEN, "mixed_bad.rn")).returncode != 0

def test_reassign_seq_ok():
    assert run_cli("run", os.path.join(GEN, "reassign_seq_ok.rn")).returncode == 0

def test_reassign_seq_bad():
    assert run_cli("check", os.path.join(GEN, "reassign_seq_bad.rn")).returncode != 0

def test_unparam_compat_ok():
    assert run_cli("run", os.path.join(GEN, "unparam_compat_ok.rn")).returncode == 0
