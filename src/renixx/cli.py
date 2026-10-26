"""Command-line interface for Renixx."""
import sys
import os
import argparse
from .interpreter import Interpreter
from .parser import parse
from .formatter import format_source
from .lexer import tokenize
from .errors import RenixxError

VERSION = "1.0.0"

def run_file(path, args):
    if not os.path.exists(path):
        print("renixx: file not found: %s" % path, file=sys.stderr)
        return 1
    try:
        src = open(path, encoding="utf-8").read()
    except Exception as e:
        print("renixx: cannot read file: %s" % e, file=sys.stderr)
        return 1
    # set os args
    import sys as _sys
    _sys.argv = [path] + list(args)
    try:
        program = parse(src)
    except RenixxError as e:
        print(str(e), file=sys.stderr)
        if getattr(e, "stack", None):
            for name, line in reversed(e.stack):
                print("  at %s (line %s)" % (name, line), file=sys.stderr)
        return 1
    interp = Interpreter()
    # inject script path into os module? already via sys.argv
    try:
        interp.eval_file(path) if False else None
        # run with env
        interp.run(program, interp.globals_env)
    except RenixxError as e:
        print(str(e), file=sys.stderr)
        if getattr(e, "stack", None):
            for name, line in reversed(e.stack):
                print("  at %s (line %s)" % (name, line), file=sys.stderr)
        return 1
    except SystemExit as e:
        return e.code if isinstance(e.code, int) else 0
    except Exception as e:
        print("renixx: %s: %s" % (type(e).__name__, e), file=sys.stderr)
        return 1
    return 0

def repl():
    print("Renixx %s REPL. Type :help for commands, :quit to exit." % VERSION)
    interp = Interpreter()
    buf = ""
    while True:
        try:
            prompt = "... " if buf else ">>> "
            line = input(prompt)
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if line.strip() == ":quit" or line.strip() == ":exit":
            break
        if line.strip() == ":help":
            print("Commands: :quit, :reset, :load <file>")
            continue
        if line.strip().startswith(":load "):
            path = line.strip()[6:].strip()
            try:
                src = open(path, encoding="utf-8").read()
                program = parse(src)
                interp.run(program, interp.globals_env)
            except Exception as e:
                print("Error:", e)
            continue
        if line.strip() == ":reset":
            interp = Interpreter()
            print("Reset.")
            continue
        buf += line + "\n"
        # try parse; if incomplete, continue
        try:
            program = parse(buf)
        except Exception as e:
            # maybe incomplete; check if it's a parse error about EOF/brace
            msg = str(e).lower()
            if "expected" in msg or "unexpected" in msg:
                continue
            print("Error:", e)
            buf = ""
            continue
        try:
            interp.run(program, interp.globals_env)
        except RenixxError as e:
            print(str(e))
            if getattr(e, "stack", None):
                for name, line in reversed(e.stack):
                    print("  at %s (line %s)" % (name, line))
        except Exception as e:
            print("Error:", e)
        buf = ""

def check_file(path):
    if not os.path.exists(path):
        print("renixx: file not found: %s" % path, file=sys.stderr)
        return 1
    src = open(path, encoding="utf-8").read()
    try:
        parse(src)
        print("%s: OK" % path)
        return 0
    except RenixxError as e:
        print(str(e), file=sys.stderr)
        if getattr(e, "stack", None):
            for name, line in reversed(e.stack):
                print("  at %s (line %s)" % (name, line), file=sys.stderr)
        return 1

def main(argv=None):
    if argv is None:
        argv = sys.argv[1:]
    if not argv:
        repl()
        return 0
    cmd = argv[0]
    if cmd in ("--version", "-v", "version"):
        print("Renixx %s" % VERSION)
        return 0
    if cmd in ("--help", "-h", "help"):
        print("Usage: renixx [command] [args...]")
        print("Commands:")
        print("  run <file> [args...]   Run a Renixx program")
        print("  repl                   Start interactive REPL")
        print("  check <file>           Check syntax")
        print("  fmt <file>             Format source (prints to stdout)")
        print("  version                Show version")
        return 0
    if cmd == "run":
        if len(argv) < 2:
            print("renixx: missing file", file=sys.stderr)
            return 1
        return run_file(argv[1], argv[2:])
    if cmd == "repl":
        repl()
        return 0
    if cmd == "check":
        if len(argv) < 2:
            print("renixx: missing file", file=sys.stderr)
            return 1
        return check_file(argv[1])
    if cmd == "fmt":
        if len(argv) < 2:
            print("renixx: missing file", file=sys.stderr)
            return 1
        path = argv[1]
        if not os.path.exists(path):
            print("renixx: file not found: %s" % path, file=sys.stderr)
            return 1
        src = open(path, encoding="utf-8").read()
        try:
            out = format_source(src)
        except RenixxError as e:
            print(str(e), file=sys.stderr)
            return 1
        if len(argv) > 2 and argv[2] == "-w":
            open(path, "w", encoding="utf-8").write(out)
            print("formatted %s" % path)
        else:
            print(out, end="")
        return 0
    # if first arg is a file, run it
    if os.path.exists(cmd):
        return run_file(cmd, argv[1:])
    print("renixx: unknown command: %s" % cmd, file=sys.stderr)
    return 1

if __name__ == "__main__":
    sys.exit(main())
