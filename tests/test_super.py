"""Tests for super() support in Renixx."""
import subprocess, sys, os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable
SRC = os.path.join(ROOT, "src")

def run_cli(*args):
    env = dict(os.environ)
    env["PYTHONPATH"] = SRC
    return subprocess.run([PY, "-m", "renixx", *args], capture_output=True, text=True, env=env, cwd=ROOT)

def run_code(code):
    import tempfile
    fd, path = tempfile.mkstemp(suffix=".rn")
    with os.fdopen(fd, "w") as f:
        f.write(code)
    r = run_cli("run", path)
    os.remove(path)
    return r

# --- Runtime tests ---

def test_super_simple():
    code = "class A { fn get() { return 1 } }\nclass B extends A { fn get() { return super.get() + 1 } }\nprint(new B().get())\n"
    r = run_code(code)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "2"

def test_super_init_chain():
    code = ("class A { fn init(x) { this.x = x } fn get() { return this.x } }\n"
            "class B extends A { fn init(x, y) { super.init(x); this.y = y } fn get() { return super.get() + this.y } }\n"
            "class C extends B { fn init(x, y, z) { super.init(x, y); this.z = z } fn get() { return super.get() + this.z } }\n"
            "let c = new C(1, 2, 3)\nprint(c.get())\n")
    r = run_code(code)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "6"

def test_super_three_levels():
    code = ("class A { fn val() { return 10 } }\n"
            "class B extends A { fn val() { return super.val() + 1 } fn getB() { return super.val() } }\n"
            "class C extends B { }\n"
            "let c = new C()\nprint(c.val())\nprint(c.getB())\n")
    r = run_code(code)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "11\n10"

def test_super_with_args_and_return():
    code = ("class A { fn add(a, b) { return a + b } }\n"
            "class B extends A { fn add(a, b) { return super.add(a, b) * 2 } }\n"
            "print(new B().add(3, 4))\n")
    r = run_code(code)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "14"

def test_super_outside_class_error():
    code = "fn f() { return super.get() }\nf()\n"
    r = run_code(code)
    assert r.returncode != 0
    assert "super" in r.stderr

def test_super_no_extends_error():
    code = "class A { fn get() { return super.get() } }\nprint(new A().get())\n"
    r = run_code(code)
    assert r.returncode != 0
    assert "super" in r.stderr

def test_super_missing_method_error():
    code = "class A { fn get() { return 1 } }\nclass B extends A { fn foo() { return super.bar() } }\nprint(new B().foo())\n"
    r = run_code(code)
    assert r.returncode != 0
    assert "bar" in r.stderr

# --- Check/typecheck tests (no false diagnostics) ---

def test_check_no_false_diagnostics():
    code = ("class A { fn get() { return 1 } }\n"
            "class B extends A { fn get() { return super.get() + 1 } }\n"
            "print(new B().get())\n")
    import tempfile
    fd, path = tempfile.mkstemp(suffix=".rn")
    with os.fdopen(fd, "w") as f:
        f.write(code)
    r = run_cli("check", path)
    os.remove(path)
    assert r.returncode == 0, r.stderr + r.stdout

def test_check_super_outside_class_reports_error():
    code = "fn f() { return super.get() }\n"
    import tempfile
    fd, path = tempfile.mkstemp(suffix=".rn")
    with os.fdopen(fd, "w") as f:
        f.write(code)
    r = run_cli("check", path)
    os.remove(path)
    assert r.returncode != 0
    assert "super" in (r.stderr + r.stdout).lower()

def test_check_super_no_extends_reports_error():
    code = "class A { fn get() { return super.get() } }\n"
    import tempfile
    fd, path = tempfile.mkstemp(suffix=".rn")
    with os.fdopen(fd, "w") as f:
        f.write(code)
    r = run_cli("check", path)
    os.remove(path)
    assert r.returncode != 0
    assert "super" in (r.stderr + r.stdout).lower()
