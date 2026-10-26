# Renixx

**Renixx** is a modern, dynamically-typed, interpreted programming language.
It is designed to be small, readable, and batteries-included: a clean syntax
inspired by the best of Python, JavaScript, and Rust, with a rich standard
library and a friendly REPL.

- File extension: `.rn`
- Interpreter: Python 3.9+
- License: MIT

## Quick start

```sh
# run a program
renixx run examples/hello.rn

# interactive REPL
renixx

# check syntax
renixx check examples/fibonacci.rn
```

If you don't have the `renixx` launcher installed, run directly:

```sh
PYTHONPATH=src python -m renixx run examples/hello.rn
```

## Hello, world

```rn
print("Hello, World!")
```

## Features

- Variables: `let`, `const`
- Functions, lambdas, closures, recursion
- Classes with inheritance (`extends`)
- Control flow: `if/else`, `while`, `for`, `match`
- Exception handling: `try/catch/finally`, `throw`
- Data structures: lists, dicts, ranges, slicing, destructuring
- Comprehensions: `[x*2 for x in xs if x > 0]`
- String interpolation: `"hello {name}"`
- Spread: `[...xs, 4]`
- Optional type annotations: `fn add(a: int, b: int) -> int`
- Method calls on strings/lists/dicts
- Stack traces and source-context error messages
- Formatter: `renixx fmt`
- Modules: `math`, `random`, `time`, `json`, `os`, `fs`, `re`, `http`, `collections`
- Imports from files and built-in modules
- First-class functions, higher-order functions
- Clean error messages with line numbers

## Example

```rn
fn fib(n) {
  if n <= 1 { return n }
  return fib(n - 1) + fib(n - 2)
}

for i in range(12) {
  print("fib({i}) = {fib(i)}")
}
```

## Project layout

```
renixx/
  src/renixx/        # language implementation
  examples/          # example programs
  tests/             # test suite
  docs/              # specification and grammar
  playground/        # web playground
  tools/             # launchers
```

## Documentation

- [Language specification](docs/SPEC.md)
- [Grammar (EBNF)](docs/GRAMMAR.ebnf)
- [Tutorial](docs/TUTORIAL.md)

## Development

```sh
pip install -e .
python -m pytest
```

## Status

Renixx 1.0 — initial release. Contributions welcome.