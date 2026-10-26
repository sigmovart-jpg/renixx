"""Language Server Protocol server for Renixx."""
import sys
import json
import os
from .parser import parse
from .lexer import tokenize
from .errors import RenixxError, ParseError, LexError
from .ast import *
from .semantics import analyze as semantic_analyze

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
    lsp_diags = []
    for d in sem_diags:
        line = max(0, d["line"] - 1)
        col = max(0, d["col"])
        end_col = d.get("end_col", col + 1)
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

def find_definitions(program):
    """Return list of (name, kind, line0, col0, end_col0)."""
    defs = []
    if program is None:
        return defs
    for stmt in program.statements:
        if isinstance(stmt, FnDecl) and stmt.name:
            defs.append((stmt.name, "function", stmt.line - 1, 0))
        if isinstance(stmt, ClassDecl):
            defs.append((stmt.name, "class", stmt.line - 1, 0))
        if isinstance(stmt, LetStmt) and stmt.name:
            defs.append((stmt.name, "variable", stmt.line - 1, 0))
    # walk class methods
    for stmt in program.statements:
        if isinstance(stmt, ClassDecl):
            for m in stmt.methods:
                if m.name:
                    defs.append((m.name, "method", m.line - 1, 0))
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

def handle_completion(params):
    uri = params["textDocument"]["uri"]
    program = asts.get(uri, None)
    items = []
    for kw in KEYWORDS:
        items.append({"label": kw, "kind": 14, "detail": "keyword"})
    for b in BUILTINS:
        items.append({"label": b, "kind": 3, "detail": "builtin"})
    for name in collect_identifiers(program):
        if name and name not in ("this",):
            items.append({"label": name, "kind": 6, "detail": "identifier"})
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
    line = pos["line"]
    ch = pos["character"]
    # find the function name before the last unclosed '('
    # gather text up to cursor
    prefix = ""
    for i in range(line):
        prefix += lines[i] + "\n"
    if line < len(lines):
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
    program = asts.get(uri, None)
    # find function def
    params_list = None
    from .ast import FnDecl, ClassDecl
    def find_fn(prog, target):
        if prog is None:
            return None
        for st in prog.statements:
            if isinstance(st, FnDecl) and st.name == target:
                return st.params
            if isinstance(st, ClassDecl):
                for m in st.methods:
                    if m.name == target:
                        return m.params
        return None
    params_list = find_fn(program, name)
    if params_list is None:
        return None
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
    return {
        "signatures": [{"label": "%s(%s)" % (name, ", ".join(pp["label"] for pp in sig_params)),
                        "parameters": sig_params}],
        "activeSignature": 0,
        "activeParameter": min(commas, len(sig_params) - 1) if sig_params else 0,
    }

def handle_references(params):
    uri = params["textDocument"]["uri"]
    pos = params["position"]
    text = documents.get(uri, "")
    lines = text.splitlines()
    line = pos["line"]
    ch = pos["character"]
    word = ""
    if line < len(lines):
        s = lines[line]
        start = ch
        while start > 0 and (s[start-1].isalnum() or s[start-1] == "_"):
            start -= 1
        end = ch
        while end < len(s) and (s[end].isalnum() or s[end] == "_"):
            end += 1
        word = s[start:end]
    if not word:
        return []
    # search all documents for occurrences
    result = []
    for u, t in documents.items():
        for i, ln in enumerate(t.splitlines()):
            # find all occurrences
            idx = 0
            while True:
                j = ln.find(word, idx)
                if j == -1:
                    break
                # word boundary check
                left_ok = (j == 0) or not (ln[j-1].isalnum() or ln[j-1] == "_")
                right_ok = (j + len(word) >= len(ln)) or not (ln[j+len(word)].isalnum() or ln[j+len(word)] == "_")
                if left_ok and right_ok:
                    result.append({"uri": u, "range": {"start": {"line": i, "character": j},
                                                      "end": {"line": i, "character": j + len(word)}}})
                idx = j + 1
    return result

def handle_rename(params):
    uri = params["textDocument"]["uri"]
    pos = params["position"]
    new_name = params["newName"]
    text = documents.get(uri, "")
    lines = text.splitlines()
    line = pos["line"]
    ch = pos["character"]
    word = ""
    if line < len(lines):
        s = lines[line]
        start = ch
        while start > 0 and (s[start-1].isalnum() or s[start-1] == "_"):
            start -= 1
        end = ch
        while end < len(s) and (s[end].isalnum() or s[end] == "_"):
            end += 1
        word = s[start:end]
    if not word:
        return None
    refs = handle_references({"textDocument": {"uri": uri}, "position": pos})
    # build changes across all docs
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
        defs = find_definitions(program)
        for name, kind, dline, dcol in defs:
            if query.lower() in name.lower():
                sk = 12 if kind == "function" else (5 if kind == "class" else 13)
                result.append({
                    "name": name,
                    "kind": sk,
                    "location": {"uri": uri, "range": {"start": {"line": dline, "character": dcol},
                                                       "end": {"line": dline, "character": dcol + len(name)}}},
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
    defs = find_definitions(program)
    for name, kind, dline, dcol in defs:
        ttype = "function" if kind in ("function","method") else ("class" if kind == "class" else "variable")
        tokens.append((dline, dcol, len(name), ttype))
    # sort by line, col
    tokens.sort(key=lambda t: (t[0], t[1]))
    # encode delta
    prev_line = 0
    prev_col = 0
    out = []
    for line, col, length, ttype in tokens:
        delta_line = line - prev_line
        delta_col = col if delta_line > 0 else col - prev_col
        out.extend([delta_line, delta_col, length, TOKEN_TYPES.get(ttype, 2), 0])
        prev_line = line
        prev_col = col
    return {"data": out}

def handle_hover(params):
    uri = params["textDocument"]["uri"]
    pos = params["position"]
    text = documents.get(uri, "")
    lines = text.splitlines()
    line = pos["line"]
    ch = pos["character"]
    # extract word at position
    word = ""
    if line < len(lines):
        s = lines[line]
        # find word boundaries
        start = ch
        while start > 0 and (s[start-1].isalnum() or s[start-1] == "_"):
            start -= 1
        end = ch
        while end < len(s) and (s[end].isalnum() or s[end] == "_"):
            end += 1
        word = s[start:end]
    if not word:
        return None
    # documentation
    docs = {
        "print": "print(...): print values to stdout",
        "len": "len(x): length of string/list/dict",
        "range": "range(stop) / range(start, stop) / range(start, stop, step)",
        "math": "math module: sqrt, sin, cos, pi, ...",
        "json": "json module: parse, stringify",
    }
    info = docs.get(word, word)
    return {
        "contents": {"kind": "markdown", "value": "```\n%s\n```\n%s" % (word, info)},
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
    defs = find_definitions(program)
    for name, kind, dline, dcol in defs:
        if name == word:
            return {"uri": uri, "range": {"start": {"line": dline, "character": dcol},
                                          "end": {"line": dline, "character": dcol + len(name)}}}
    return None

def handle_document_symbol(params):
    uri = params["textDocument"]["uri"]
    program = asts.get(uri, None)
    defs = find_definitions(program)
    out = []
    for name, kind, dline, dcol in defs:
        sk = 12 if kind == "function" else (5 if kind == "class" else 13)
        out.append({
            "name": name,
            "kind": sk,
            "range": {"start": {"line": dline, "character": dcol},
                      "end": {"line": dline, "character": dcol + len(name)}},
            "selectionRange": {"start": {"line": dline, "character": dcol},
                               "end": {"line": dline, "character": dcol + len(name)}},
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
    last_char = len(lines[last_line]) if lines else 0
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
                    start_col = rng["start"]["character"]
                    end_line = rng["end"]["line"]
                    end_col = rng["end"]["character"]
                    lines = text.split("\n")
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
