# Renixx Language Specification (v1.0)

## 1. Overview

Renixx is a dynamically typed, interpreted language. Source files use the
`.rn` extension and UTF-8 encoding. Statements are separated by newlines or
semicolons. Indentation is not significant.

## 2. Lexical structure

### 2.1 Comments

- Line comment: `// ...` or `# ...`
- Block comment: `/* ... */`

### 2.2 Identifiers

`[a-zA-Z_][a-zA-Z0-9_]*`. Identifiers cannot be keywords.

### 2.3 Keywords

`let const fn return if else while for in break continue match case default
class new this import from as export try catch finally throw true false nil
and or not extends is`

### 2.4 Literals

- Integers: `42`, `0xFF`, `0b1010`, with optional underscores `1_000`.
- Floats: `3.14`, `1e3`, `1_000.5`.
- Strings: `"..."` (double) or `'...'` (single). Double-quoted strings
  support interpolation `{expr}` and escape sequences (`\n`, `\t`, `\\`,
  `\"`, `\'`, `\0`). Triple-quoted strings `"""..."""` are supported.
- Booleans: `true`, `false`.
- Nil: `nil`.
- Lists: `[1, 2, 3]`.
- Dicts: `{"a": 1, "b": 2}`.

### 2.5 Operators

Arithmetic: `+ - * / % **`
Comparison: `== != === !== < > <= >=`
Logical: `and or not && || !`
Assignment: `= += -= *= /= %=`
Other: `.` (member), `[]` (index), `()` (call), `? :` (ternary),
`=>` (lambda/case), `..` (range, reserved).

## 3. Types

`nil`, `bool`, `int`, `float`, `string`, `list`, `dict`, `function`,
`class`, `instance`. Truthiness: nil and false and 0 and empty containers
are falsy; everything else truthy.

Optional type annotations may use parameterized types: `list[int]`,
`dict[string, int]`, `list[list[int]]`. Unannotated code is never
checked. Annotations are validated both by the static type checker and
at runtime.

## 4. Variables

```
let x = 5          // mutable
let y              // nil
const PI = 3.14    // immutable
x = 10             // reassign
```

## 5. Functions

```
fn add(a, b) { return a + b }
let mul = (a, b) => a * b
let inc = x => x + 1
```

Parameters support defaults and rest:

```
fn f(a, b = 2, ...rest) { ... }
```

## 6. Control flow

```
if cond { } else if cond2 { } else { }
while cond { }
for x in iterable { }
for (let i=0; i<n; i=i+1) { }
match x {
  1 => { ... }
  n if n > 10 => { ... }
  _ => { ... }
}
```

## 7. Classes

```
class Animal {
  fn init(name) { this.name = name }
  fn speak() { print(this.name) }
}
class Dog extends Animal { ... }
let d = new Dog("Rex")
```

`super.method(args)` calls the parent class method with the same `this`.
`super.init(args)` calls the parent constructor. `super` always refers
to the parent of the class where the method is defined, even when called
on a subclass instance.

## 8. Exception handling

```
try { throw "boom" } catch e { print(e) } finally { cleanup() }
```

## 9. Modules

```
import "math"               // module object
import "math" as m
from "math" import sqrt, pi
import "lib.rn"             // file module
import "lib.rn" as lib
```

Built-in modules: `math`, `random`, `time`, `json`, `os`, `fs`, `re`, `http`,
`collections`.

## 9.5 Advanced features

- Slicing: `xs[1:4]`, `xs[:3]`, `xs[3:]`, `xs[::2]`, `xs[::-1]`.
- Destructuring: `let [a, b] = xs`, `let {name, ver} = d`.
- Comprehensions: `[x*2 for x in xs if x > 0]`, `{k: v for x in xs}`.
- Spread: `let ys = [...xs, 4, 5]`.
- Method calls: `"hi".upper()`, `xs.push(1)`, `xs.map(f)`, `d.get(k, default)`.
- Stack traces on errors with source context.
- Formatter: `renixx fmt file.rn`.

## 10. Standard library (selected)

Global: `print println input len type str int float bool range abs min max
sum sorted reversed enumerate zip keys values`.

- `math`: `pi e sqrt pow floor ceil round abs sin cos tan log exp min max
  gcd factorial`
- `random`: `random randint choice shuffle seed`
- `time`: `now sleep format`
- `json`: `parse stringify`
- `os`: `env args cwd platform exit`
- `fs`: `read_file write_file append_file exists list_dir mkdir remove
  is_file is_dir`
- `re`: `match search findall sub split`
- `http`: `get post`
- `collections`: `Counter defaultdict`

## 11. Grammar

See `docs/GRAMMAR.ebnf`.