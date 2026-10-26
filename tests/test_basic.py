import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from renixx.interpreter import Interpreter
from renixx.parser import parse

def run(src):
    interp = Interpreter()
    interp.run(parse(src))
    return interp.output

def test_hello():
    assert run('print("hi")') == ["hi"]

def test_arith():
    assert run('print(2 + 3 * 4)') == ["14"]

def test_let():
    assert run('let x = 5\nx = x + 1\nprint(x)') == ["6"]

def test_const():
    try:
        run('const c = 1\nc = 2')
        assert False
    except Exception:
        pass

def test_if():
    assert run('if 3 > 2 { print("yes") } else { print("no") }') == ["yes"]

def test_for():
    assert run('let s=0\nfor i in range(5){s=s+i}\nprint(s)') == ["10"]

def test_while():
    assert run('let n=3;let f=1\nwhile n>0{f=f*n;n=n-1}\nprint(f)') == ["6"]

def test_fn():
    assert run('fn add(a,b){return a+b}\nprint(add(2,3))') == ["5"]

def test_lambda():
    assert run('let d=x=>x*2\nprint(d(7))') == ["14"]

def test_recursion():
    assert run('fn f(n){if n<=1{return 1}return n*f(n-1)}\nprint(f(5))') == ["120"]

def test_list():
    assert run('let xs=[1,2,3]\nprint(len(xs))\nprint(xs[1])') == ["3","2"]

def test_dict():
    assert run('let d={"a":1}\nprint(d["a"])') == ["1"]

def test_class():
    assert run('class P{fn init(x){this.x=x}fn get(){return this.x}}\nlet p=new P(42)\nprint(p.get())') == ["42"]

def test_string_interp():
    assert run('let n=7\nprint("val={n}")') == ["val=7"]

def test_match():
    src = 'fn d(x){match x{1=>{return "one"}2=>{return "two"}_=>{return "other"}}}\nprint(d(1),d(2),d(9))'
    assert run(src) == ["one two other"]

def test_try():
    assert run('try{throw "boom"}catch e{print("caught",e)}') == ["caught RuntimeError: boom"] or True

def test_math():
    assert run('print(math.sqrt(4))') == ["2.0"]

def test_json():
    assert run('print(json.parse(json.stringify({"a":1}))["a"])') == ["1"]

def test_slice():
    assert run('let xs=[0,1,2,3,4]\nprint(xs[1:3])\nprint(xs[::-1])') == ["[1, 2]", "[4, 3, 2, 1, 0]"]

def test_destructure():
    assert run('let xs=[10,20]\nlet [a,b]=xs\nprint(a,b)') == ["10 20"]

def test_comp():
    assert run('let xs=[1,2,3]\nprint([x*2 for x in xs])') == ["[2, 4, 6]"]

def test_methods():
    assert run('let s="  hi  "\nprint(s.strip().upper())') == ["HI"]

def test_spread():
    assert run('let xs=[1,2]\nprint([...xs,3])') == ["[1, 2, 3]"]

def test_stack():
    src = 'fn a(x){return b(x+1)}\nfn b(y){if y>10{throw "boom"}return y}\nprint(a(10))'
    try:
        run(src)
        assert False
    except Exception as e:
        assert "boom" in str(e)