"""Command-line interface for Renixx."""
import sys
import os
import argparse
import traceback
from .interpreter import Interpreter
from .parser import parse
from .formatter import format_source
from .lexer import tokenize
from .errors import RenixxError, RuntimeError as RenixxRuntimeError, ThrowSignal

VERSION = "1.0.0"
_DEBUG = False

_DIAGNOSTIC_CATEGORIES = {
    "semantic": ("SemanticError", "SemanticWarning"),
    "typechecker": ("TypeError", "TypeWarning"),
}


def _read_source(path):
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def _print_location(path, line, col, category, message, stream):
    location = path or "<input>"
    if line and line > 0:
        location += ":%d" % line
        if col and col > 0:
            location += ":%d" % col
    print("%s: %s: %s" % (location, category, message), file=stream)


def _print_source_context(src, line, col, stream):
    if not src or not line or line < 1:
        return
    lines = src.splitlines()
    if line > len(lines):
        return
    text = lines[line - 1]
    print("  | " + text, file=stream)
    caret = max(0, (col or 1) - 1)
    if caret > len(text):
        caret = len(text)
    print("  | " + " " * caret + "^", file=stream)


def print_renixx_error(error, path=None, src=None, stream=None):
    """Print a RenixxError as a location line plus source context."""
    if stream is None:
        stream = sys.stderr
    _print_location(
        path,
        getattr(error, "line", 0),
        getattr(error, "col", 0),
        getattr(error, "kind", "Error"),
        getattr(error, "message", str(error)),
        stream,
    )
    _print_source_context(src, getattr(error, "line", 0), getattr(error, "col", 0), stream)
    for name, line in reversed(getattr(error, "stack", None) or []):
        print("  at %s (line %s)" % (name, line), file=stream)


def _print_thrown(thrown, interp, path=None, src=None, stream=None):
    """Print an uncaught throw: strings read as runtime errors, others as values."""
    if stream is None:
        stream = sys.stderr
    if isinstance(thrown.value, str):
        error = RenixxRuntimeError(
            thrown.value,
            getattr(thrown, "line", 0),
            getattr(thrown, "col", 0),
            getattr(thrown, "stack", None),
        )
        print_renixx_error(error, path, src, stream)
        return
    _print_location(
        path,
        getattr(thrown, "line", 0),
        getattr(thrown, "col", 0),
        "Uncaught",
        interp.to_string(thrown.value),
        stream,
    )
    _print_source_context(src, getattr(thrown, "line", 0), getattr(thrown, "col", 0), stream)
    for name, line in reversed(getattr(thrown, "stack", None) or []):
        print("  at %s (line %s)" % (name, line), file=stream)


def _report_internal_error(error, stream=None):
    """Report an unexpected Python exception without masking it as a user error."""
    if stream is None:
        stream = sys.stderr
    print("internal error: %s: %s" % (type(error).__name__, error), file=stream)
    print("renixx: this is a bug in the Renixx interpreter, not in your program", file=stream)
    if _DEBUG:
        traceback.print_exc(file=sys.stderr)


def _diagnostic_category(diag):
    source = diag.get("source", "")
    names = _DIAGNOSTIC_CATEGORIES.get(source)
    if names is not None:
        severity = diag.get("severity", 1) or 1
        return names[0] if severity <= 1 else names[1]
    return source.capitalize() if source else "Diagnostic"


def _merge_diagnostics(*groups):
    seen = set()
    merged = []
    for group in groups:
        for diag in group:
            key = (diag.get("line"), diag.get("col"), diag.get("end_col"), diag.get("message"))
            if key in seen:
                continue
            seen.add(key)
            merged.append(diag)
    merged.sort(key=lambda d: (d.get("line") or 0, d.get("col") or 0, d.get("message") or ""))
    return merged


def print_diagnostics(diagnostics, path=None, src=None, stream=None):
    """Print analyzer diagnostics using the shared CLI format."""
    if stream is None:
        stream = sys.stderr
    for diag in diagnostics:
        line = diag.get("line") or 0
        col0 = diag.get("col")
        # Analyzer diagnostics use 0-based columns; display 1-based ones.
        col = (col0 + 1) if isinstance(col0, int) and col0 >= 0 else None
        _print_location(path, line, col, _diagnostic_category(diag), diag.get("message", ""), stream)
        _print_source_context(src, line, col, stream)


def _static_diagnostics(path, src, program):
    """Run the existing analyzers and merge their diagnostics.

    Returns None when the semantic analyzer fails unexpectedly; the failure is
    reported to stderr and the caller must treat the check as failed.
    """
    try:
        from .semantics import analyze as semantic_analyze
        semantic_diags, parse_error = semantic_analyze(src)
    except Exception as exc:
        print("renixx: semantic analysis failed: %s: %s" % (type(exc).__name__, exc), file=sys.stderr)
        return None
    if parse_error is not None:
        print_renixx_error(parse_error, path, src)
        return None

    type_diags = []
    type_check_completed = False
    try:
        from .typechecker import TypeChecker
        type_diags = TypeChecker(src).check(program)
        type_check_completed = True
    except Exception as exc:
        # The type checker is an optional analyzer; report why it could not
        # run instead of pretending the program passed type checking.
        print("renixx: warning: type checking unavailable: %s: %s" % (type(exc).__name__, exc),
              file=sys.stderr)

    if type_check_completed:
        # TypeChecker is authoritative for Unknown type diagnostics.
        # Filter all of them from semantics to avoid duplicates.
        # If TypeChecker failed, keep semantics' as fallback.
        semantic_diags = [
            d for d in semantic_diags
            if not d.get("message", "").startswith("Unknown type '")
        ]

    return _merge_diagnostics(semantic_diags, type_diags)


def run_file(path, args):
    if not os.path.exists(path):
        print("renixx: file not found: %s" % path, file=sys.stderr)
        return 1
    try:
        src = _read_source(path)
    except Exception as e:
        print("renixx: cannot read file: %s" % e, file=sys.stderr)
        return 1
    # set os args
    sys.argv = [path] + list(args)
    try:
        program = parse(src)
    except RenixxError as e:
        print_renixx_error(e, path, src)
        return 1
    interp = Interpreter()
    try:
        interp.run(program, interp.globals_env)
    except RenixxError as e:
        print_renixx_error(e, path, src)
        return 1
    except ThrowSignal as thrown:
        _print_thrown(thrown, interp, path, src)
        return 1
    except SystemExit as e:
        return e.code if isinstance(e.code, int) else 0
    except Exception as e:
        _report_internal_error(e)
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
                src = _read_source(path)
            except Exception as e:
                print("Error: cannot read file: %s" % e)
                continue
            try:
                program = parse(src)
                interp.run(program, interp.globals_env)
            except RenixxError as e:
                print_renixx_error(e, path, src, stream=sys.stdout)
            except ThrowSignal as thrown:
                _print_thrown(thrown, interp, path, src, sys.stdout)
            except Exception as e:
                _report_internal_error(e, sys.stdout)
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
            print_renixx_error(e, "<repl>", buf, stream=sys.stdout)
        except ThrowSignal as thrown:
            _print_thrown(thrown, interp, "<repl>", buf, sys.stdout)
        except Exception as e:
            _report_internal_error(e, sys.stdout)
        buf = ""

def check_file(path, syntax_only=False):
    if not os.path.exists(path):
        print("renixx: file not found: %s" % path, file=sys.stderr)
        return 1
    try:
        src = _read_source(path)
    except Exception as e:
        print("renixx: cannot read file: %s" % e, file=sys.stderr)
        return 1
    try:
        program = parse(src)
    except RenixxError as e:
        print_renixx_error(e, path, src)
        return 1
    if syntax_only:
        print("%s: OK" % path)
        return 0
    diagnostics = _static_diagnostics(path, src, program)
    if diagnostics is None:
        return 1
    if not diagnostics:
        print("%s: OK" % path)
        return 0
    print_diagnostics(diagnostics, path, src)
    has_errors = any((d.get("severity", 1) or 1) <= 1 for d in diagnostics)
    if has_errors:
        return 1
    print("%s: OK" % path)
    return 0

def main(argv=None):
    global _DEBUG
    if argv is None:
        argv = sys.argv[1:]
    argv = list(argv)
    if "--debug" in argv:
        _DEBUG = True
        argv = [arg for arg in argv if arg != "--debug"]
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
        print("  check <file> [--syntax-only]  Check syntax, semantics and types")
        print("  fmt <file>             Format source (prints to stdout)")
        print("  lsp                    Start language server (stdio)")
        print("  version                Show version")
        print("Global options:")
        print("  --debug                Show tracebacks for internal interpreter errors")
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
        syntax_only = False
        for flag in argv[2:]:
            if flag == "--syntax-only":
                syntax_only = True
            else:
                print("renixx: unknown option for check: %s" % flag, file=sys.stderr)
                return 1
        return check_file(argv[1], syntax_only=syntax_only)
    if cmd == "fmt":
        if len(argv) < 2:
            print("renixx: missing file", file=sys.stderr)
            return 1
        path = argv[1]
        if not os.path.exists(path):
            print("renixx: file not found: %s" % path, file=sys.stderr)
            return 1
        try:
            src = _read_source(path)
        except Exception as e:
            print("renixx: cannot read file: %s" % e, file=sys.stderr)
            return 1
        try:
            out = format_source(src)
        except RenixxError as e:
            print_renixx_error(e, path, src)
            return 1
        except Exception as e:
            _report_internal_error(e)
            return 1
        if len(argv) > 2 and argv[2] == "-w":
            open(path, "w", encoding="utf-8").write(out)
            print("formatted %s" % path)
        else:
            print(out, end="")
        return 0
    if cmd == "lsp":
        try:
            from .lsp import main as lsp_main
        except Exception as e:
            print("renixx: cannot start language server: %s: %s" % (type(e).__name__, e), file=sys.stderr)
            return 1
        lsp_main()
        return 0
    # if first arg is a file, run it
    if os.path.exists(cmd):
        return run_file(cmd, argv[1:])
    print("renixx: unknown command: %s" % cmd, file=sys.stderr)
    return 1

if __name__ == "__main__":
    sys.exit(main())
