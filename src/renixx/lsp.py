"""Language Server Protocol server for Renixx."""
import sys
import json
import os
from .parser import parse
from .lexer import tokenize
from .errors import RenixxError, ParseError, LexError
from .ast import *

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
asts = {}       # uri -> (program or None, error)

KEYWORDS = ["let","const","fn","return","if","else","while","for","in","break","continue",
            "match","case","default","class","new","this","import","from","as","export",
            "try","catch","finally","throw","true","false","nil","and","or","not","extends","is"]

BUILTINS = ["print","println","input","len","type","str","int","float","bool","range",
            "abs","min","max","sum","sorted","reversed","enumerate","zip","keys","values",
            "math","random","time","json","os","fs","re","http","collections"]

def analyze(uri, text):
    try:
        program = parse(text)
        asts[uri] = (program, None)
    except RenixxError as e:
        asts[uri] = (None, e)
    except Exception as e:
        asts[uri] = (None, RenixxError(str(e)))

def publish_diagnostics(uri):
    program, err = asts.get(uri, (None, None))
    text = documents.get(uri, "")
    diags = []
    if err is not None:
        line = max(0, (err.line or 1) - 1)
        col = max(0, (err.col or 1) - 1)
        lines = text.splitlines()
        end_col = col
        if line < len(lines):
            # extend to end of token-ish: find end of line or word
            end_col = len(lines[line])
        diags.append({
            "range": {"start": {"line": line, "character": col},
                      "end": {"line": line, "character": end_col}},
            "severity": 1,
            "source": "renixx",
            "message": str(err),
        })
    write_message({
        "jsonrpc": "2.0",
        "method": "textDocument/publishDiagnostics",
        "params": {"uri": uri, "diagnostics": diags},
    })

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
            "textDocumentSync": 1,  # Full
            "completionProvider": {"triggerCharacters": [".", " "]},
            "hoverProvider": True,
            "definitionProvider": True,
            "documentSymbolProvider": True,
            "documentFormattingProvider": True,
        },
        "serverInfo": {"name": "renixx-lsp", "version": "1.0.0"},
    }

def handle_completion(params):
    uri = params["textDocument"]["uri"]
    program, err = asts.get(uri, (None, None))
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
    program, err = asts.get(uri, (None, None))
    defs = find_definitions(program)
    for name, kind, dline, dcol in defs:
        if name == word:
            return {"uri": uri, "range": {"start": {"line": dline, "character": dcol},
                                          "end": {"line": dline, "character": dcol + len(name)}}}
    return None

def handle_document_symbol(params):
    uri = params["textDocument"]["uri"]
    program, err = asts.get(uri, (None, None))
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
            if changes:
                # full sync
                documents[uri] = changes[-1].get("text", documents.get(uri, ""))
            analyze(uri, documents.get(uri, ""))
            publish_diagnostics(uri)
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
        else:
            if msg_id is not None:
                write_message({"jsonrpc": "2.0", "id": msg_id, "error": {"code": -32601, "message": "Method not found"}})

if __name__ == "__main__":
    main()
