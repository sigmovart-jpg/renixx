# Renixx Tutorial

## 1. Variables

```rn
let x = 10
const PI = 3.14159
x = x + 1
print(x, PI)
```

## 2. Types

```rn
let n = 42        // int
let f = 3.14      // float
let s = "hi"      // string
let b = true      // bool
let nothing = nil // nil
let xs = [1,2,3]  // list
let d = {"a":1}   // dict
```

## 3. Operators

```rn
print(2 + 3, 10 - 4, 3 * 4, 10 / 3, 10 % 3, 2 ** 8)
print(1 == 1, 1 != 2, 1 < 2, 2 <= 2)
print(true and false, true or false, not false)
```

## 4. Strings

```rn
let name = "renixx"
print("hello {name}")
print("2+2 = {2+2}")
```

## 5. Control flow

```rn
if x > 0 {
  print("positive")
} else if x == 0 {
  print("zero")
} else {
  print("negative")
}

let i = 0
while i < 5 {
  print(i)
  i = i + 1
}

for x in [10, 20, 30] {
  print(x)
}
```

## 6. Functions

```rn
fn greet(name, greeting = "Hello") {
  print("{greeting}, {name}!")
}
greet("world")
greet("friend", "Hi")

let double = x => x * 2
print(double(7))
```

## 7. Lists and dicts

```rn
let xs = [1, 2, 3]
xs = xs + [4]
print(xs[0], xs[2])  // indexing
print(len(xs))

let d = {"name": "renixx"}
print(d["name"])
d["version"] = 1
```

## 8. Classes

```rn
class Point {
  fn init(x, y) {
    this.x = x
    this.y = y
  }
  fn length() {
    return math.sqrt(this.x*this.x + this.y*this.y)
  }
}
let p = new Point(3, 4)
print(p.length())
```

## 9. Match

```rn
fn describe(n) {
  match n {
    1 => { return "one" }
    2 => { return "two" }
    _ => { return "other" }
  }
}
```

## 10. Error handling

```rn
try {
  throw "something broke"
} catch e {
  print("caught:", e)
} finally {
  print("done")
}
```

## 11. Modules

```rn
print(math.sqrt(2))
print(math.pi)
print(json.stringify({"a": 1}))

// files
fs.write_file("out.txt", "hello")
print(fs.read_file("out.txt"))
print(fs.exists("out.txt"))
```

## 12. Imports

```rn
// built-in
import "math" as m
print(m.sqrt(9))

from "math" import sqrt, pi
print(sqrt(16), pi)

// user file
// import "lib.rn" as lib
```

## Next steps

Read the full [specification](SPEC.md) and [grammar](GRAMMAR.ebnf). Explore
`examples/` for more. Run `renixx` to start the REPL.