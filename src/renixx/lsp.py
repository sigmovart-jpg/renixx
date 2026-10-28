"""Language Server Protocol server for Renixx."""
import sys
import json
import os
from .parser import parse
from .lexer import tokenize
from .errors import RenixxError, ParseError, LexError
from .ast import *
from .semantics import analyze as semantic_analyze
from .typechecker import TypeChecker

# ---- JSON-RPC transport ----
def read_message():
    headers = {}
    while True:
        line = sys.stdin.readline()
        if not line:
            return None
        line = line.rstrip("\r\n")
        if line == "":
            break
        if ":" in line:
            key, val = line.split(":", 1)
            headers[key.strip().lower()] = val.strip()
    length = int(headers.get("content-length", 0))
    if length == 0:
        return None
    body = sys.stdin.read(length)
    return json.loads(body)

def write_message(msg):
    body = json.dumps(msg)
    sys.stdout.write("Content-Length: %d\r\n\r\n%s" % (len(body.encode("utf-8")), body))
    sys.stdout.flush()


# ---- UTF-16 <-> code point conversion (LSP uses UTF-16 code units) ----
def py_col_to_utf16(line_text, py_col):
    """Convert a Python code-point column to a UTF-16 code-unit column."""
    return len(line_text[:py_col].encode("utf-16-le")) // 2

def utf16_col_to_py(line_text, utf16_col):
    """Convert a UTF-16 code-unit column to a Python code-point column."""
    units = 0
    for i, ch in enumerate(line_text):
        if units >= utf16_col:
            return i
        units += 2 if ord(ch) > 0xFFFF else 1
    return len(line_text)


# ---- document store ----
documents = {}  # uri -> text
asts = {}       # uri -> program or None
diagnostics_cache = {}  # uri -> list of LSP diagnostics

KEYWORDS = ["let","const","fn","return","if","else","while","for","in","break","continue",
            "match","case","default","class","new","this","import","from","as","export",
            "try","catch","finally","throw","true","false","nil","and","or","not","extends","is"]

BUILTINS = ["print","println","input","len","type","str","int","float","bool","range",
            "abs","min","max","sum","sorted","reversed","enumerate","zip","keys","values",
            "math","random","time","json","os","fs","re","http","collections"]

def analyze(uri, text):
    try:
        program = parse(text)
        asts[uri] = program
    except RenixxError as e:
        asts[uri] = None
        # store syntax error
        asts[uri + "::err"] = e
        # publish syntax error and return
        _publish_syntax_error(uri, text, e)
        return
    except Exception as e:
        asts[uri] = None
        asts[uri + "::err"] = RenixxError(str(e))
        _publish_syntax_error(uri, text, asts[uri + "::err"])
        return
    # clear syntax error marker
    asts.pop(uri + "::err", None)
    # semantic analysis
    sem_diags, _ = semantic_analyze(text)
    # type checking (wrapped in try/except to avoid LSP crashes)
    type_diags = []
    type_check_completed = False
    try:
        checker = TypeChecker(text)
        type_diags = checker.check(program)
        type_check_completed = True
    except Exception as e:
        # Don't crash LSP on type checker errors
        pass
    if type_check_completed:
        # Generic annotations are validated by TypeChecker; the older
        # semantic analyzer does not understand parameterized type syntax.
        sem_diags = [
            d for d in sem_diags
            if not (
                d.get("message", "").startswith("Unknown type '")
                and "[" in d.get("message", "")
            )
        ]
    # combine and deduplicate diagnostics
    all_diags = list(sem_diags) + list(type_diags)
    # Identical diagnostics from different analyzers share a source location.
    # Keep same-message diagnostics at distinct locations on the same line.
    seen_diagnostics = set()
    unique_diags = []
    for d in all_diags:
        key = (
            d.get("line"),
            d.get("col"),
            d.get("end_col"),
            d.get("message"),
        )
        if key in seen_diagnostics:
            continue
        seen_diagnostics.add(key)
        unique_diags.append(d)
    lsp_diags = []
    lines = text.splitlines()
    for d in unique_diags:
        line = max(0, d["line"] - 1)
        col = max(0, d["col"])
        end_col = d.get("end_col", col + 1)
        # convert Python code-point columns to UTF-16 code units
        if line < len(lines):
            col = py_col_to_utf16(lines[line], col)
            end_col = py_col_to_utf16(lines[line], end_col)
        lsp_diags.append({
            "range": {"start": {"line": line, "character": col},
                      "end": {"line": line, "character": end_col}},
            "severity": d.get("severity", 1),
            "source": "renixx",
            "message": d["message"],
        })
    diagnostics_cache[uri] = lsp_diags
    write_message({
        "jsonrpc": "2.0",
        "method": "textDocument/publishDiagnostics",
        "params": {"uri": uri, "diagnostics": lsp_diags},
    })

def _publish_syntax_error(uri, text, e):
    line = max(0, (e.line or 1) - 1)
    col = max(0, (e.col or 1) - 1)
    lines = text.splitlines()
    end_col = col
    if line < len(lines):
        end_col = len(lines[line])
        # convert to UTF-16
        col = py_col_to_utf16(lines[line], col)
        end_col = py_col_to_utf16(lines[line], end_col)
    diags = [{
        "range": {"start": {"line": line, "character": col},
                  "end": {"line": line, "character": end_col}},
        "severity": 1,
        "source": "renixx",
        "message": str(e),
    }]
    diagnostics_cache[uri] = diags
    write_message({
        "jsonrpc": "2.0",
        "method": "textDocument/publishDiagnostics",
        "params": {"uri": uri, "diagnostics": diags},
    })

def publish_diagnostics(uri):
    # kept for compatibility; analyze already publishes
    pass

def find_definitions(program, text=None):
    """Return list of (name, kind, line0, col0)."""
    defs = []
    if program is None:
        return defs
    lines = (text or "").splitlines()
    tokens = tokenize(text or "")
    def col_of(line_no, name):
        if line_no < 1 or line_no > len(lines):
            return 0
        s = lines[line_no - 1]
        idx = s.find(name)
        return idx if idx >= 0 else 0

    def add_named_definition(stmt, kind):
        if not stmt.name:
            return
        col = getattr(stmt, "name_col", 0)
        if col:
            col = max(0, col - 1)
        else:
            col = col_of(stmt.line, stmt.name)
        defs.append((stmt.name, kind, stmt.line - 1, col))

    used_destructure_tokens = set()

    def add_destructure_definitions(stmt):
        open_type, close_type = (
            ("LBRACKET", "RBRACKET")
            if stmt.kind == "list"
            else ("LBRACE", "RBRACE")
        )
        for start, token in enumerate(tokens):
            if (
                token.type != "KEYWORD"
                or token.value not in ("let", "const")
                or token.line != stmt.line
                or start in used_destructure_tokens
            ):
                continue
            opening = start + 1
            while opening < len(tokens) and tokens[opening].type == "NEWLINE":
                opening += 1
            if opening >= len(tokens) or tokens[opening].type != open_type:
                continue
            names = []
            name_tokens = []
            for candidate in tokens[opening + 1:]:
                if candidate.type == close_type:
                    break
                if candidate.type == "IDENT":
                    names.append(candidate.value)
                    name_tokens.append(candidate)
            if names != stmt.names:
                continue
            used_destructure_tokens.add(start)
            for name, name_token in zip(stmt.names, name_tokens):
                defs.append((
                    name,
                    "variable",
                    name_token.line - 1,
                    max(0, name_token.col - 1),
                ))
            return

    def visit_declarations(node):
        if node is None:
            return
        if isinstance(node, FnDecl):
            add_named_definition(node, "function")
            visit_declarations(node.body)
            return
        if isinstance(node, ClassDecl):
            add_named_definition(node, "class")
            for method in node.methods:
                add_named_definition(method, "method")
                visit_declarations(method.body)
            return
        if isinstance(node, DestructureStmt):
            add_destructure_definitions(node)
        if isinstance(node, (list, tuple)):
            for child in node:
                visit_declarations(child)
            return
        if isinstance(node, Node):
            for child in vars(node).values():
                visit_declarations(child)

    for stmt in program.statements:
        if isinstance(stmt, LetStmt) and stmt.name:
            add_named_definition(stmt, "variable")
        visit_declarations(stmt)
    return defs

def collect_identifiers(program):
    ids = set()
    if program is None:
        return ids
    def walk(node):
        if node is None:
            return
        if isinstance(node, Identifier):
            ids.add(node.name)
        for attr in ("statements","body","then_branch","else_branch","expr","cond",
                     "value","left","right","operand","callee","obj","index","elements",
                     "pairs","cases","try_block","catch_block","finally_block","init",
                     "step","iterable","start","stop"):
            v = getattr(node, attr, None)
            if isinstance(v, list):
                for x in v:
                    walk(x)
            elif hasattr(v, "__dict__") and not isinstance(v, (str, int, float, bool)):
                walk(v)
    walk(program)
    return ids

# ---- request handlers ----
def handle_initialize(params):
    return {
        "capabilities": {
            "textDocumentSync": 2,  # Incremental
            "completionProvider": {"triggerCharacters": [".", " "]},
            "hoverProvider": True,
            "definitionProvider": True,
            "documentSymbolProvider": True,
            "documentFormattingProvider": True,
            "signatureHelpProvider": {"triggerCharacters": ["(", ","]},
            "referencesProvider": True,
            "renameProvider": True,
            "codeActionProvider": True,
            "workspaceSymbolProvider": True,
            "semanticTokensProvider": {"legend": {"tokenTypes": ["keyword","function","variable","class","string","number","comment","operator"], "tokenModifiers": []}, "range": False, "full": True},
        },
        "serverInfo": {"name": "renixx-lsp", "version": "1.0.0"},
    }

def _program_for_features(uri):
    program = asts.get(uri)
    if program is not None:
        return program
    text = documents.get(uri, "")
    try:
        return parse(text)
    except Exception:
        pass
    for end in range(len(text), 0, -1):
        if text[end - 1] != "\n":
            continue
        try:
            return parse(text[:end])
        except Exception:
            continue
    return None

def _identifier_at_position(text, line, utf16_col):
    lines = text.splitlines()
    if line < 0 or line >= len(lines):
        return None
    line_text = lines[line]
    py_col = utf16_col_to_py(line_text, max(0, utf16_col))
    try:
        tokens = tokenize(text)
    except Exception:
        return None
    for token in tokens:
        if token.line != line + 1 or token.type not in ("IDENT", "KEYWORD"):
            continue
        start = max(0, token.col - 1)
        end = start + len(token.value)
        if start <= py_col <= end:
            return token.value, start, end
    return None

def _node_position(node, text):
    lines = text.splitlines()
    line = max(0, getattr(node, "line", 1) - 1)
    if line >= len(lines):
        return line, 0
    col = getattr(node, "name_col", 0)
    return line, max(0, col - 1) if col else 0

def _function_declarations(program):
    declarations = []

    def visit(node):
        if node is None:
            return
        if isinstance(node, FnDecl):
            declarations.append(node)
        if isinstance(node, (list, tuple)):
            for child in node:
                visit(child)
        elif isinstance(node, Node):
            for child in vars(node).values():
                visit(child)

    visit(program)
    return declarations

def _function_range(fn, text, tokens, brace_pairs):
    if not fn.name:
        return None
    name_col = max(0, getattr(fn, "name_col", 0) - 1)
    name_token = None
    name_index = None
    for index, token in enumerate(tokens):
        if (token.type == "IDENT" and token.value == fn.name
                and token.line == fn.line and max(0, token.col - 1) == name_col):
            name_token = token
            name_index = index
            break
    if name_index is None:
        return None
    open_paren = next(
        (i for i in range(name_index + 1, len(tokens)) if tokens[i].type == "LPAREN"),
        None,
    )
    if open_paren is None:
        return None
    depth = 0
    close_paren = None
    for index in range(open_paren, len(tokens)):
        if tokens[index].type == "LPAREN":
            depth += 1
        elif tokens[index].type == "RPAREN":
            depth -= 1
            if depth == 0:
                close_paren = index
                break
    if close_paren is None:
        return None
    open_brace = next(
        (i for i in range(close_paren + 1, len(tokens)) if tokens[i].type == "LBRACE"),
        None,
    )
    if open_brace not in brace_pairs:
        return None
    lines = text.splitlines(keepends=True)

    def offset(token):
        return sum(len(value) for value in lines[:token.line - 1]) + max(0, token.col - 1)

    start = offset(name_token)
    opening = offset(tokens[open_brace])
    closing = offset(tokens[brace_pairs[open_brace]])
    return start, opening, closing

def _function_signature(fn):
    params = []
    for param in fn.params:
        name = param[0]
        default = param[1] if len(param) > 1 else None
        is_rest = param[2] if len(param) > 2 else False
        annotation = param[3] if len(param) > 3 else None
        label = ("..." if is_rest else "") + name
        if annotation:
            label += ": " + annotation
        if default is not None:
            label += " = ..."
        params.append(label)
    signature = "fn %s(%s)" % (fn.name, ", ".join(params))
    if fn.return_type:
        signature += " -> " + fn.return_type
    return signature

def _visible_symbols(uri, program, line, utf16_col):
    text = documents.get(uri, "")
    lines = text.splitlines()
    if line < 0 or line >= len(lines):
        return {}
    py_col = utf16_col_to_py(lines[line], max(0, utf16_col))
    offset = sum(len(value) for value in text.splitlines(keepends=True)[:line]) + py_col
    try:
        tokens = tokenize(text)
    except Exception:
        tokens = []
    brace_stack = []
    brace_pairs = {}
    for index, token in enumerate(tokens):
        if token.type == "LBRACE":
            brace_stack.append(index)
        elif token.type == "RBRACE" and brace_stack:
            brace_pairs[brace_stack.pop()] = index
    source_lines = text.splitlines(keepends=True)

    def token_offset(token):
        return sum(len(value) for value in source_lines[:token.line - 1]) + max(0, token.col - 1)

    brace_ranges = [
        (
            token_offset(tokens[opening]),
            token_offset(tokens[closing]),
            tokens[opening].line - 1,
        )
        for opening, closing in brace_pairs.items()
    ]

    functions = _function_declarations(program)
    ranges = []
    for fn in functions:
        fn_range = _function_range(fn, text, tokens, brace_pairs)
        if fn_range and fn_range[0] <= offset <= fn_range[2]:
            ranges.append((fn_range[2] - fn_range[0], fn, fn_range))
    ranges.sort(reverse=True, key=lambda item: item[0])

    checker = TypeChecker(text)
    try:
        checker.check(program)
        from .typechecker import Scope
        scope = Scope()
    except Exception:
        checker = None
        from .typechecker import Scope
        scope = Scope()
    symbols = {}

    if checker is not None:
        for name in checker.fn_types:
            scope.define(name, "function", "function")
            declaration = next((fn for fn in functions if fn.name == name), None)
            symbols[name] = {"kind": "function", "type": "function", "declaration": declaration}
        for name in checker.class_types:
            scope.define(name, "class", "class")
            symbols[name] = {"kind": "class", "type": "class", "declaration": None}
    for name in BUILTINS:
        scope.define(name, "any", "builtin")
        symbols.setdefault(name, {"kind": "builtin", "type": "any", "declaration": None})

    def before_cursor(node):
        decl_line, decl_col = _node_position(node, text)
        return (decl_line, decl_col) <= (line, py_col)

    def define_statement(stmt, current_scope):
        if isinstance(stmt, LetStmt) and stmt.name and before_cursor(stmt):
            annotation = stmt.type_annot
            try:
                inferred = checker._infer_type(stmt.value, current_scope) if checker else None
            except Exception:
                inferred = None
            symbol_type = annotation or (inferred if inferred not in (None, "unknown") else None)
            current_scope.define(stmt.name, symbol_type or "unknown", "variable")
            symbols[stmt.name] = {"kind": "variable", "type": symbol_type, "declaration": stmt}
        elif isinstance(stmt, DestructureStmt) and before_cursor(stmt):
            for name in stmt.names:
                current_scope.define(name, "unknown", "variable")
                symbols[name] = {"kind": "variable", "type": None, "declaration": stmt}
        elif isinstance(stmt, FnDecl) and stmt.name and before_cursor(stmt):
            current_scope.define(stmt.name, "function", "function")
            symbols[stmt.name] = {"kind": "function", "type": "function", "declaration": stmt}
        elif isinstance(stmt, ClassDecl) and stmt.name and before_cursor(stmt):
            current_scope.define(stmt.name, "class", "class")
            symbols[stmt.name] = {"kind": "class", "type": "class", "declaration": stmt}

    for stmt in program.statements:
        if isinstance(stmt, (LetStmt, DestructureStmt, FnDecl, ClassDecl)):
            define_statement(stmt, scope)

    for _, fn, _ in ranges:
        child_scope = Scope(scope)
        for param in fn.params:
            name = param[0]
            annotation = param[3] if len(param) > 3 else None
            default = param[1] if len(param) > 1 else None
            try:
                inferred = checker._infer_type(default, scope) if checker and default is not None else None
            except Exception:
                inferred = None
            symbol_type = annotation or (inferred if inferred not in (None, "unknown") else None)
            child_scope.define(name, symbol_type or "unknown", "variable")
            symbols[name] = {"kind": "variable", "type": symbol_type, "declaration": fn}
        for stmt in fn.body.statements:
            if isinstance(stmt, (LetStmt, DestructureStmt, FnDecl, ClassDecl)):
                define_statement(stmt, child_scope)
        scope = child_scope

    nested_declarations = []
    for_statements = []
    try_statements = []
    for_init_ids = set()

    def collect_nested_declarations(node):
        if node is None:
            return
        if isinstance(node, LetStmt):
            nested_declarations.append(node)
        if isinstance(node, ForStmt):
            for_statements.append(node)
            if isinstance(node.init, LetStmt):
                for_init_ids.add(id(node.init))
        if isinstance(node, TryStmt):
            try_statements.append(node)
        if isinstance(node, (list, tuple)):
            for child in node:
                collect_nested_declarations(child)
        elif isinstance(node, Node):
            for child in vars(node).values():
                collect_nested_declarations(child)

    collect_nested_declarations(program)
    nested_declarations.sort(key=lambda stmt: _node_position(stmt, text))
    for stmt in nested_declarations:
        if not stmt.name or id(stmt) in for_init_ids or not before_cursor(stmt):
            continue
        decl_line, decl_col = _node_position(stmt, text)
        decl_offset = sum(
            len(value) for value in source_lines[:decl_line]
        ) + decl_col
        containing_ranges = [
            pair for pair in brace_ranges if pair[0] < decl_offset < pair[1]
        ]
        if not containing_ranges:
            continue
        scope_range = min(containing_ranges, key=lambda pair: pair[1] - pair[0])
        if not scope_range[0] < offset < scope_range[1]:
            continue
        annotation = stmt.type_annot
        try:
            inferred = checker._infer_type(stmt.value, scope) if checker else None
        except Exception:
            inferred = None
        symbol_type = annotation or (inferred if inferred not in (None, "unknown") else None)
        scope.define(stmt.name, symbol_type or "unknown", "variable")
        symbols[stmt.name] = {"kind": "variable", "type": symbol_type, "declaration": stmt}

    def body_range(block, after_offset=0):
        candidates = [
            (start, end) for start, end, open_line in brace_ranges
            if open_line == block.line - 1
            and start >= after_offset
            and start < offset < end
        ]
        return min(candidates, key=lambda pair: pair[1] - pair[0]) if candidates else None

    for loop in for_statements:
        loop_name = loop.var
        loop_name_offset = 0
        if loop_name:
            for index, token in enumerate(tokens[:-1]):
                if (token.type == "KEYWORD" and token.value == "for"
                        and token.line == loop.line
                        and tokens[index + 1].type == "IDENT"
                        and tokens[index + 1].value == loop_name):
                    loop_name_offset = token_offset(tokens[index + 1])
                    break
        else:
            loop_name = loop.init.name if isinstance(loop.init, LetStmt) else None
            if loop_name:
                loop_line, loop_col = _node_position(loop.init, text)
                loop_name_offset = sum(
                    len(value) for value in source_lines[:loop_line]
                ) + loop_col
        active_body = body_range(loop.body, loop_name_offset)
        if not loop_name or active_body is None:
            continue
        symbol_type = None
        if loop.var and checker:
            try:
                iterable_type = checker._infer_type(loop.iterable, scope)
                from .typechecker import parse_type
                parsed_type = parse_type(iterable_type)
                if parsed_type[0] == "list" and parsed_type[1]:
                    symbol_type = parsed_type[1][0]
            except Exception:
                pass
        elif isinstance(loop.init, LetStmt):
            symbol_type = loop.init.type_annot
            if symbol_type is None and checker:
                try:
                    symbol_type = checker._infer_type(loop.init.value, scope)
                except Exception:
                    symbol_type = None
            if symbol_type == "unknown":
                symbol_type = None
        scope.define(loop_name, symbol_type or "unknown", "variable")
        symbols[loop_name] = {"kind": "variable", "type": symbol_type, "declaration": loop}

    for try_stmt in try_statements:
        if not try_stmt.catch_var or try_stmt.catch_block is None:
            continue
        catch_offset = None
        for index, token in enumerate(tokens):
            if token.type != "KEYWORD" or token.value != "catch":
                continue
            catch_name = None
            for candidate in tokens[index + 1:index + 5]:
                if candidate.type == "IDENT" and candidate.value == try_stmt.catch_var:
                    catch_name = candidate
                if candidate.type == "LBRACE":
                    if (catch_name is not None
                            and candidate.line == try_stmt.catch_block.line):
                        catch_offset = token_offset(catch_name)
                    break
            if catch_offset is not None:
                break
        if catch_offset is None or body_range(try_stmt.catch_block, catch_offset) is None:
            continue
        scope.define(try_stmt.catch_var, "any", "variable")
        symbols[try_stmt.catch_var] = {
            "kind": "variable",
            "type": "any",
            "declaration": try_stmt,
        }
    return symbols

def handle_completion(params):
    uri = params["textDocument"]["uri"]
    program = _program_for_features(uri)
    pos = params.get("position", {})
    symbols = _visible_symbols(uri, program, pos.get("line", 0), pos.get("character", 0)) if program else {}
    items = []
    for kw in KEYWORDS:
        items.append({"label": kw, "kind": 14, "detail": "keyword"})
    for b in BUILTINS:
        items.append({"label": b, "kind": 3, "detail": "builtin"})
    for name, symbol in symbols.items():
        kind = symbol["kind"]
        kind_num = 12 if kind == "function" else (5 if kind == "class" else 13 if kind == "variable" else 3)
        detail = kind
        if kind == "variable" and symbol.get("type"):
            detail += ": " + symbol["type"]
        elif kind == "function" and symbol.get("declaration"):
            detail = _function_signature(symbol["declaration"])
        items.append({"label": name, "kind": kind_num, "detail": detail})
    # dedupe
    seen = set()
    out = []
    for it in items:
        if it["label"] in seen:
            continue
        seen.add(it["label"])
        out.append(it)
    return out

def handle_signature_help(params):
    uri = params["textDocument"]["uri"]
    pos = params["position"]
    text = documents.get(uri, "")
    lines = text.splitlines()
    line = pos.get("line", 0)
    ch = pos.get("character", 0)
    if line < 0 or line > len(lines):
        return None
    # find the function name before the last unclosed '('
    # gather text up to cursor
    prefix = ""
    for i in range(line):
        prefix += lines[i] + "\n"
    if line < len(lines):
        ch = utf16_col_to_py(lines[line], ch)
        prefix += lines[line][:ch]
    # find last '(' not closed
    depth = 0
    idx = -1
    for i in range(len(prefix) - 1, -1, -1):
        c = prefix[i]
        if c == ")":
            depth += 1
        elif c == "(":
            if depth == 0:
                idx = i
                break
            depth -= 1
    if idx == -1:
        return None
    # find identifier before '('
    j = idx - 1
    while j >= 0 and prefix[j].isspace():
        j -= 1
    end = j + 1
    while j >= 0 and (prefix[j].isalnum() or prefix[j] == "_"):
        j -= 1
    name = prefix[j+1:end]
    if not name:
        return None
    program = _program_for_features(uri)
    symbols = _visible_symbols(uri, program, line, pos.get("character", 0)) if program else {}
    symbol = symbols.get(name)
    fn = symbol.get("declaration") if symbol else None
    if fn is None:
        candidates = [candidate for candidate in _function_declarations(program) if candidate.name == name] if program else []
        fn = candidates[0] if len(candidates) == 1 else None
    if fn is None:
        return None
    params_list = fn.params
    # count active parameter (commas at depth 0 after '(')
    after = prefix[idx+1:]
    depth2 = 0
    commas = 0
    for c in after:
        if c == "(":
            depth2 += 1
        elif c == ")":
            depth2 -= 1
        elif c == "," and depth2 == 0:
            commas += 1
    sig_params = []
    for p in params_list:
        pname = p[0]
        annot = p[3] if len(p) > 3 else None
        default = p[1] if len(p) > 1 else None
        label = pname
        if annot:
            label += ": " + annot
        if default is not None:
            label += " = ..."
        sig_params.append({"label": label})
    signature_label = _function_signature(fn)
    return {
        "signatures": [{"label": signature_label,
                        "parameters": sig_params}],
        "activeSignature": 0,
        "activeParameter": min(commas, len(sig_params) - 1) if sig_params else 0,
    }

def _word_at(text, line, ch):
    lines = text.splitlines()
    if line >= len(lines):
        return ""
    s = lines[line]
    if ch > len(s):
        ch = len(s)
    start = ch
    while start > 0 and (s[start-1].isalnum() or s[start-1] == "_"):
        start -= 1
    end = ch
    while end < len(s) and (s[end].isalnum() or s[end] == "_"):
        end += 1
    return s[start:end]

def _identifier_positions(text, name):
    """Return list of (line0, col0) for identifier tokens equal to name (not in strings/comments)."""
    res = []
    try:
        toks = tokenize(text)
    except Exception:
        return res
    # reconstruct line/col from token.line (1-based) and token.col? token.col may be 0
    # tokenizer sets col only sometimes; recompute by scanning
    lines = text.splitlines()
    # We'll locate each occurrence by walking tokens with a running position
    # Simpler: for each token, if IDENT/KEYWORD with value==name, find its column in the corresponding line
    # Track occurrence index per line
    from collections import defaultdict
    occ_counter = defaultdict(int)
    for tok in toks:
        if tok.type in ("IDENT", "KEYWORD") and tok.value == name:
            ln = tok.line - 1
            if 0 <= ln < len(lines):
                line_text = lines[ln]
                # find the occurrence index
                # find all positions of name in line_text
                positions = []
                idx = 0
                while True:
                    j = line_text.find(name, idx)
                    if j == -1:
                        break
                    left_ok = (j == 0) or not (line_text[j-1].isalnum() or line_text[j-1] == "_")
                    right_ok = (j + len(name) >= len(line_text)) or not (line_text[j+len(name)].isalnum() or line_text[j+len(name)] == "_")
                    if left_ok and right_ok:
                        positions.append(j)
                    idx = j + 1
                if positions:
                    occ = occ_counter[ln]
                    if occ < len(positions):
                        col = positions[occ]
                    else:
                        col = positions[-1]
                    occ_counter[ln] += 1
                    res.append((ln, col))
    return res

def handle_references(params):
    uri = params["textDocument"]["uri"]
    pos = params["position"]
    text = documents.get(uri, "")
    lines = text.splitlines()
    line = pos["line"]
    ch = pos["character"]
    if line < len(lines):
        ch = utf16_col_to_py(lines[line], ch)
    word = _word_at(text, line, ch)
    if not word:
        return []
    result = []
    for u, t in documents.items():
        # only search the same identifier name
        for (ln, col) in _identifier_positions(t, word):
            lines = t.splitlines()
            line_text = lines[ln] if ln < len(lines) else ""
            utf16_col = py_col_to_utf16(line_text, col)
            utf16_end = py_col_to_utf16(line_text, col + len(word))
            result.append({"uri": u, "range": {"start": {"line": ln, "character": utf16_col},
                                              "end": {"line": ln, "character": utf16_end}}})
    return result

def handle_rename(params):
    uri = params["textDocument"]["uri"]
    pos = params["position"]
    new_name = params["newName"]
    text = documents.get(uri, "")
    lines = text.splitlines()
    line = pos["line"]
    ch = pos["character"]
    if line < len(lines):
        ch = utf16_col_to_py(lines[line], ch)
    word = _word_at(text, line, ch)
    if not word or not word.isidentifier():
        return None
    refs = handle_references({"textDocument": {"uri": uri}, "position": pos})
    if not refs:
        return None
    changes = {}
    for r in refs:
        u = r["uri"]
        changes.setdefault(u, []).append({"range": r["range"], "newText": new_name})
    return {"changes": changes}

def handle_code_action(params):
    uri = params["textDocument"]["uri"]
    rng = params["range"]
    # simple: offer "Format document"
    return [{
        "title": "Format document",
        "kind": "source.formatDocument",
        "command": {"title": "Format", "command": "editor.action.formatDocument", "arguments": []},
    }]

def handle_workspace_symbol(params):
    query = params.get("query", "")
    result = []
    for uri, text in documents.items():
        program = asts.get(uri, None)
        defs = find_definitions(program, documents.get(uri, ""))
        for name, kind, dline, dcol in defs:
            if query.lower() in name.lower():
                sk = 12 if kind == "function" else (5 if kind == "class" else 13)
                lines = (documents.get(uri, "") or "").splitlines()
                line_text = lines[dline] if dline < len(lines) else ""
                uc = py_col_to_utf16(line_text, dcol)
                ue = py_col_to_utf16(line_text, dcol + len(name))
                result.append({
                    "name": name,
                    "kind": sk,
                    "location": {"uri": uri, "range": {"start": {"line": dline, "character": uc},
                                                       "end": {"line": dline, "character": ue}}},
                })
    return result

TOKEN_TYPES = {"keyword":0,"function":1,"variable":2,"class":3,"string":4,"number":5,"comment":6,"operator":7}
def handle_semantic_tokens(params):
    uri = params["textDocument"]["uri"]
    text = documents.get(uri, "")
    # produce tokens: keywords, strings, numbers, comments, functions, classes
    lines = text.splitlines()
    data = []
    # we'll do a simple regex-based tokenization
    import re
    prev_line = 0
    prev_col = 0
    tokens = []  # list of (line, col, length, type)
    for i, ln in enumerate(lines):
        # comments
        # find // comments
        ci = ln.find("//")
        if ci != -1:
            tokens.append((i, ci, len(ln) - ci, "comment"))
        # strings (double)
        for m in re.finditer(r'"(?:[^"\\]|\\.)*"', ln):
            tokens.append((i, m.start(), m.end() - m.start(), "string"))
        # numbers
        for m in re.finditer(r"\b\d+(?:\.\d+)?\b", ln):
            tokens.append((i, m.start(), m.end() - m.start(), "number"))
        # keywords
        for kw in KEYWORDS:
            for m in re.finditer(r"\b" + kw + r"\b", ln):
                tokens.append((i, m.start(), m.end() - m.start(), "keyword"))
    # functions/classes names from defs
    program = asts.get(uri, None)
    defs = find_definitions(program, text)
    for name, kind, dline, dcol in defs:
        ttype = "function" if kind in ("function","method") else ("class" if kind == "class" else "variable")
        # keep Python (code-point) positions; conversion to UTF-16 happens in encoding loop
        tokens.append((dline, dcol, len(name), ttype))
    # sort by line, col
    tokens.sort(key=lambda t: (t[0], t[1]))
    # convert columns to UTF-16 and encode delta
    prev_line = 0
    prev_col = 0
    out = []
    for line, col, length, ttype in tokens:
        line_text = lines[line] if line < len(lines) else ""
        utf16_col = py_col_to_utf16(line_text, col)
        utf16_len = py_col_to_utf16(line_text[col:col+length], 0) + (py_col_to_utf16(line_text[col:col+length], length) if length <= len(line_text) - col else length)
        # simpler: length in UTF-16
        utf16_len = len(line_text[col:col+length].encode("utf-16-le")) // 2
        delta_line = line - prev_line
        delta_col = utf16_col if delta_line > 0 else utf16_col - prev_col
        out.extend([delta_line, delta_col, utf16_len, TOKEN_TYPES.get(ttype, 2), 0])
        prev_line = line
        prev_col = utf16_col
    return {"data": out}

def handle_hover(params):
    uri = params["textDocument"]["uri"]
    pos = params["position"]
    text = documents.get(uri, "")
    line = pos.get("line", 0)
    token = _identifier_at_position(text, line, pos.get("character", 0))
    if token is None:
        return None
    word, start, end = token
    program = _program_for_features(uri)
    symbols = _visible_symbols(uri, program, line, pos.get("character", 0)) if program else {}
    symbol = symbols.get(word)
    if symbol is None and program is not None:
        candidates = [fn for fn in _function_declarations(program) if fn.name == word]
        if len(candidates) == 1:
            symbol = {"kind": "function", "declaration": candidates[0], "type": "function"}
    docs = {
        "print": "print(...): print values to stdout",
        "len": "len(x): length of string/list/dict",
        "range": "range(stop) / range(start, stop) / range(start, stop, step)",
        "math": "math module: sqrt, sin, cos, pi, ...",
        "json": "json module: parse, stringify",
    }
    if symbol:
        kind = symbol["kind"]
        declaration = symbol.get("declaration")
        if kind == "function" and declaration:
            info = _function_signature(declaration)
        elif kind == "function":
            info = "function %s" % word
        elif kind == "class":
            info = "class %s" % word
        elif kind == "variable" and symbol.get("type"):
            info = "%s: %s" % (word, symbol["type"])
        elif kind == "builtin":
            info = docs.get(word, "built-in %s" % word)
        else:
            info = kind + " " + word
    else:
        info = docs.get(word)
    if info is None:
        return None
    line_text = text.splitlines()[line]
    return {
        "contents": {"kind": "markdown", "value": "```\n%s\n```" % info},
        "range": {
            "start": {"line": line, "character": py_col_to_utf16(line_text, start)},
            "end": {"line": line, "character": py_col_to_utf16(line_text, end)},
        },
    }

def handle_definition(params):
    uri = params["textDocument"]["uri"]
    pos = params["position"]
    text = documents.get(uri, "")
    lines = text.splitlines()
    line = pos["line"]
    ch = pos["character"]
    word = ""
    if line < len(lines):
        s = lines[line]
        ch = utf16_col_to_py(s, ch)
        if ch > len(s):
            ch = len(s)
        start = ch
        while start > 0 and (s[start-1].isalnum() or s[start-1] == "_"):
            start -= 1
        end = ch
        while end < len(s) and (s[end].isalnum() or s[end] == "_"):
            end += 1
        word = s[start:end]
    if not word:
        return None
    program = asts.get(uri, None)
    text = documents.get(uri, "")
    defs = find_definitions(program, text)
    for name, kind, dline, dcol in defs:
        if name == word:
            lines = text.splitlines()
            line_text = lines[dline] if dline < len(lines) else ""
            utf16_col = py_col_to_utf16(line_text, dcol)
            utf16_end = py_col_to_utf16(line_text, dcol + len(name))
            return {"uri": uri, "range": {"start": {"line": dline, "character": utf16_col},
                                          "end": {"line": dline, "character": utf16_end}}}
    return None

def handle_document_symbol(params):
    uri = params["textDocument"]["uri"]
    program = asts.get(uri, None)
    defs = find_definitions(program, documents.get(uri, ""))
    out = []
    for name, kind, dline, dcol in defs:
        sk = 12 if kind == "function" else (5 if kind == "class" else 13)
        lines = documents.get(uri, "").splitlines()
        line_text = lines[dline] if dline < len(lines) else ""
        uc = py_col_to_utf16(line_text, dcol)
        ue = py_col_to_utf16(line_text, dcol + len(name))
        out.append({
            "name": name,
            "kind": sk,
            "range": {"start": {"line": dline, "character": uc},
                      "end": {"line": dline, "character": ue}},
            "selectionRange": {"start": {"line": dline, "character": uc},
                               "end": {"line": dline, "character": ue}},
        })
    return out

def handle_formatting(params):
    uri = params["textDocument"]["uri"]
    text = documents.get(uri, "")
    try:
        from .formatter import format_source
        new_text = format_source(text)
    except Exception:
        return []
    # return full-document replace
    lines = text.splitlines()
    last_line = len(lines) - 1 if lines else 0
    last_char_py = len(lines[last_line]) if lines else 0
    last_char = py_col_to_utf16(lines[last_line], last_char_py) if lines else 0
    return [{
        "range": {"start": {"line": 0, "character": 0},
                  "end": {"line": last_line, "character": last_char}},
        "newText": new_text,
    }]

# ---- main loop ----
def main():
    while True:
        msg = read_message()
        if msg is None:
            break
        method = msg.get("method")
        msg_id = msg.get("id")
        params = msg.get("params", {})
        if method == "initialize":
            write_message({"jsonrpc": "2.0", "id": msg_id, "result": handle_initialize(params)})
        elif method == "initialized":
            pass
        elif method == "shutdown":
            write_message({"jsonrpc": "2.0", "id": msg_id, "result": None})
        elif method == "exit":
            sys.exit(0)
        elif method == "textDocument/didOpen":
            uri = params["textDocument"]["uri"]
            text = params["textDocument"]["text"]
            documents[uri] = text
            analyze(uri, text)
            publish_diagnostics(uri)
        elif method == "textDocument/didChange":
            uri = params["textDocument"]["uri"]
            changes = params.get("contentChanges", [])
            text = documents.get(uri, "")
            for ch in changes:
                if "range" in ch:
                    # incremental
                    rng = ch["range"]
                    start_line = rng["start"]["line"]
                    start_col_utf16 = rng["start"]["character"]
                    end_line = rng["end"]["line"]
                    end_col_utf16 = rng["end"]["character"]
                    lines = text.split("\n")
                    # convert UTF-16 columns to Python code-point columns
                    if start_line < len(lines):
                        start_col = utf16_col_to_py(lines[start_line], start_col_utf16)
                    else:
                        start_col = start_col_utf16
                    if end_line < len(lines):
                        end_col = utf16_col_to_py(lines[end_line], end_col_utf16)
                    else:
                        end_col = end_col_utf16
                    # convert to flat index
                    def to_offset(l, c):
                        off = 0
                        for i in range(l):
                            off += len(lines[i]) + 1
                        return off + c
                    s_off = to_offset(start_line, start_col)
                    e_off = to_offset(end_line, end_col)
                    text = text[:s_off] + ch.get("text", "") + text[e_off:]
                else:
                    text = ch.get("text", text)
            documents[uri] = text
            analyze(uri, text)
        elif method == "textDocument/didClose":
            uri = params["textDocument"]["uri"]
            documents.pop(uri, None)
            asts.pop(uri, None)
        elif method == "textDocument/completion":
            res = handle_completion(params)
            write_message({"jsonrpc": "2.0", "id": msg_id, "result": res})
        elif method == "textDocument/hover":
            res = handle_hover(params)
            write_message({"jsonrpc": "2.0", "id": msg_id, "result": res})
        elif method == "textDocument/definition":
            res = handle_definition(params)
            write_message({"jsonrpc": "2.0", "id": msg_id, "result": res})
        elif method == "textDocument/documentSymbol":
            res = handle_document_symbol(params)
            write_message({"jsonrpc": "2.0", "id": msg_id, "result": res})
        elif method == "textDocument/formatting":
            res = handle_formatting(params)
            write_message({"jsonrpc": "2.0", "id": msg_id, "result": res})
        elif method == "textDocument/signatureHelp":
            res = handle_signature_help(params)
            write_message({"jsonrpc": "2.0", "id": msg_id, "result": res})
        elif method == "textDocument/references":
            res = handle_references(params)
            write_message({"jsonrpc": "2.0", "id": msg_id, "result": res})
        elif method == "textDocument/rename":
            res = handle_rename(params)
            write_message({"jsonrpc": "2.0", "id": msg_id, "result": res})
        elif method == "textDocument/codeAction":
            res = handle_code_action(params)
            write_message({"jsonrpc": "2.0", "id": msg_id, "result": res})
        elif method == "workspace/symbol":
            res = handle_workspace_symbol(params)
            write_message({"jsonrpc": "2.0", "id": msg_id, "result": res})
        elif method == "textDocument/semanticTokens/full":
            res = handle_semantic_tokens(params)
            write_message({"jsonrpc": "2.0", "id": msg_id, "result": res})
        else:
            if msg_id is not None:
                write_message({"jsonrpc": "2.0", "id": msg_id, "error": {"code": -32601, "message": "Method not found"}})

if __name__ == "__main__":
    main()
