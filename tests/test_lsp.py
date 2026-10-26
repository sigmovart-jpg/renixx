"""Automated tests for the Renixx LSP server."""
import json
import os
import subprocess
import sys
import threading
import time
import queue

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC = os.path.join(ROOT, "src")
PYTHON = sys.executable


def run_session(messages, wait=1.0, text=None):
    proc = subprocess.Popen(
        [PYTHON, "-m", "renixx", "lsp"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        cwd=ROOT,
        env={"PYTHONPATH": SRC, "PATH": os.environ["PATH"]},
    )
    q = queue.Queue()

    def reader():
        while True:
            line = proc.stdout.readline()
            if not line:
                break
            headers = {}
            cur = line.decode().rstrip("\r\n")
            if ":" in cur:
                k, v = cur.split(":", 1)
                headers[k.strip().lower()] = v.strip()
            while True:
                l = proc.stdout.readline().decode().rstrip("\r\n")
                if l == "":
                    break
                if ":" in l:
                    k, v = l.split(":", 1)
                    headers[k.strip().lower()] = v.strip()
            n = int(headers.get("content-length", 0))
            if n == 0:
                continue
            body = proc.stdout.read(n)
            try:
                q.put(json.loads(body))
            except Exception:
                q.put({"_raw": body.decode(errors="replace")})

    threading.Thread(target=reader, daemon=True).start()
    time.sleep(0.2)
    for m in messages:
        body = json.dumps(m)
        proc.stdin.write(("Content-Length: %d\r\n\r\n" % len(body.encode()) + body).encode())
        proc.stdin.flush()
        time.sleep(0.2)
    time.sleep(wait)
    proc.stdin.close()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
    msgs = []
    while not q.empty():
        msgs.append(q.get())
    stderr = proc.stderr.read().decode(errors="replace")
    return msgs, stderr


def init_msg():
    return {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"capabilities": {}}}


def open_msg(uri, text):
    return {"jsonrpc": "2.0", "method": "textDocument/didOpen",
            "params": {"textDocument": {"uri": uri, "languageId": "renixx", "version": 1, "text": text}}}


def find(msgs, **kw):
    for m in msgs:
        ok = True
        for k, v in kw.items():
            if m.get(k) != v:
                ok = False
                break
        if ok:
            return m
    return None


# ---------- Tests ----------

def test_initialize():
    msgs, err = run_session([init_msg()])
    m = find(msgs, id=1)
    assert m is not None and "result" in m
    caps = m["result"]["capabilities"]
    assert caps["textDocumentSync"] == 2
    assert caps["completionProvider"] is not None
    assert caps["hoverProvider"] is True


def test_diagnostics_syntax_error():
    code = "let x = \n"
    msgs, err = run_session([init_msg(), open_msg("file:///a.rn", code)])
    notifs = [m for m in msgs if m.get("method") == "textDocument/publishDiagnostics"]
    assert notifs, "no diagnostics published"
    diags = notifs[-1]["params"]["diagnostics"]
    assert len(diags) >= 1
    assert diags[0]["severity"] == 1


def test_diagnostics_undefined_variable():
    code = "print(y)\n"
    msgs, err = run_session([init_msg(), open_msg("file:///b.rn", code)])
    notifs = [m for m in msgs if m.get("method") == "textDocument/publishDiagnostics"]
    assert notifs
    diags = notifs[-1]["params"]["diagnostics"]
    assert any("Undefined variable" in d["message"] and "y" in d["message"] for d in diags)


def test_diagnostics_clean():
    code = "let x = 5\nprint(x)\n"
    msgs, err = run_session([init_msg(), open_msg("file:///c.rn", code)])
    notifs = [m for m in msgs if m.get("method") == "textDocument/publishDiagnostics"]
    assert notifs
    diags = notifs[-1]["params"]["diagnostics"]
    assert diags == [], "expected no diagnostics, got %r" % diags


def test_diagnostics_empty_file():
    msgs, err = run_session([init_msg(), open_msg("file:///empty.rn", "")])
    notifs = [m for m in msgs if m.get("method") == "textDocument/publishDiagnostics"]
    assert notifs
    diags = notifs[-1]["params"]["diagnostics"]
    assert diags == []


def test_completion():
    code = "let foo = 1\nprint(f)\n"
    msgs, err = run_session([
        init_msg(),
        open_msg("file:///d.rn", code),
        {"jsonrpc": "2.0", "id": 2, "method": "textDocument/completion",
         "params": {"textDocument": {"uri": "file:///d.rn"}, "position": {"line": 1, "character": 7}}},
    ])
    m = find(msgs, id=2)
    assert m is not None and "result" in m
    labels = [it["label"] for it in m["result"]]
    assert "foo" in labels
    assert "print" in labels
    assert "let" in labels


def test_hover():
    code = "print(1)\n"
    msgs, err = run_session([
        init_msg(),
        open_msg("file:///e.rn", code),
        {"jsonrpc": "2.0", "id": 2, "method": "textDocument/hover",
         "params": {"textDocument": {"uri": "file:///e.rn"}, "position": {"line": 0, "character": 2}}},
    ])
    m = find(msgs, id=2)
    assert m is not None and m.get("result") is not None
    assert "print" in m["result"]["contents"]["value"]


def test_hover_empty_word():
    code = "   \n"
    msgs, err = run_session([
        init_msg(),
        open_msg("file:///f.rn", code),
        {"jsonrpc": "2.0", "id": 2, "method": "textDocument/hover",
         "params": {"textDocument": {"uri": "file:///f.rn"}, "position": {"line": 0, "character": 1}}},
    ])
    m = find(msgs, id=2)
    assert m is not None
    assert m.get("result") is None


def test_signature_help():
    code = "fn add(a: int, b: int) -> int { return a + b }\nprint(add(1, 2))\n"
    msgs, err = run_session([
        init_msg(),
        open_msg("file:///g.rn", code),
        {"jsonrpc": "2.0", "id": 2, "method": "textDocument/signatureHelp",
         "params": {"textDocument": {"uri": "file:///g.rn"}, "position": {"line": 1, "character": 11}}},
    ])
    m = find(msgs, id=2)
    assert m is not None and m.get("result") is not None
    sigs = m["result"]["signatures"]
    assert len(sigs) == 1
    assert "add" in sigs[0]["label"]
    assert len(sigs[0]["parameters"]) == 2


def test_signature_help_no_function():
    code = "print(1)\n"
    msgs, err = run_session([
        init_msg(),
        open_msg("file:///h.rn", code),
        {"jsonrpc": "2.0", "id": 2, "method": "textDocument/signatureHelp",
         "params": {"textDocument": {"uri": "file:///h.rn"}, "position": {"line": 0, "character": 6}}},
    ])
    m = find(msgs, id=2)
    assert m is not None
    # print is not a user fn; may return None or signature-less
    # accept None or result without signatures
    r = m.get("result")
    assert r is None or (isinstance(r, dict) and (r.get("signatures") in (None, [])))


def test_definition():
    code = "fn foo() { return 1 }\nprint(foo())\n"
    msgs, err = run_session([
        init_msg(),
        open_msg("file:///i.rn", code),
        {"jsonrpc": "2.0", "id": 2, "method": "textDocument/definition",
         "params": {"textDocument": {"uri": "file:///i.rn"}, "position": {"line": 1, "character": 7}}},
    ])
    m = find(msgs, id=2)
    assert m is not None and m.get("result") is not None
    res = m["result"]
    assert res["range"]["start"]["line"] == 0


def test_definition_unknown():
    code = "print(bar())\n"
    msgs, err = run_session([
        init_msg(),
        open_msg("file:///j.rn", code),
        {"jsonrpc": "2.0", "id": 2, "method": "textDocument/definition",
         "params": {"textDocument": {"uri": "file:///j.rn"}, "position": {"line": 0, "character": 7}}},
    ])
    m = find(msgs, id=2)
    assert m is not None
    assert m.get("result") is None


def test_references():
    code = "let x = 5\nlet y = x + 1\nprint(x)\n"
    msgs, err = run_session([
        init_msg(),
        open_msg("file:///k.rn", code),
        {"jsonrpc": "2.0", "id": 2, "method": "textDocument/references",
         "params": {"textDocument": {"uri": "file:///k.rn"}, "position": {"line": 0, "character": 4},
                    "context": {"includeDeclaration": True}}},
    ])
    m = find(msgs, id=2)
    assert m is not None and isinstance(m.get("result"), list)
    # x appears on lines 0, 1, 2
    lines = sorted(set(r["range"]["start"]["line"] for r in m["result"]))
    assert 0 in lines and 1 in lines and 2 in lines


def test_references_not_in_string():
    code = 'let x = 5\nprint("x")\n'
    msgs, err = run_session([
        init_msg(),
        open_msg("file:///l.rn", code),
        {"jsonrpc": "2.0", "id": 2, "method": "textDocument/references",
         "params": {"textDocument": {"uri": "file:///l.rn"}, "position": {"line": 0, "character": 4},
                    "context": {"includeDeclaration": True}}},
    ])
    m = find(msgs, id=2)
    assert m is not None
    res = m.get("result", [])
    # only the declaration on line 0, not inside string on line 1
    assert len(res) == 1
    assert res[0]["range"]["start"]["line"] == 0


def test_rename():
    code = "let x = 5\nlet y = x + 1\n"
    msgs, err = run_session([
        init_msg(),
        open_msg("file:///m.rn", code),
        {"jsonrpc": "2.0", "id": 2, "method": "textDocument/rename",
         "params": {"textDocument": {"uri": "file:///m.rn"}, "position": {"line": 0, "character": 4},
                    "newName": "z"}},
    ])
    m = find(msgs, id=2)
    assert m is not None and m.get("result") is not None
    changes = m["result"]["changes"]
    assert "file:///m.rn" in changes
    edits = changes["file:///m.rn"]
    assert len(edits) == 2
    assert all(e["newText"] == "z" for e in edits)


def test_rename_not_string():
    code = 'let x = 5\nprint("x")\n'
    msgs, err = run_session([
        init_msg(),
        open_msg("file:///n.rn", code),
        {"jsonrpc": "2.0", "id": 2, "method": "textDocument/rename",
         "params": {"textDocument": {"uri": "file:///n.rn"}, "position": {"line": 0, "character": 4},
                    "newName": "z"}},
    ])
    m = find(msgs, id=2)
    assert m is not None and m.get("result") is not None
    changes = m["result"]["changes"]
    edits = changes.get("file:///n.rn", [])
    # only declaration, not the "x" inside string
    assert len(edits) == 1


def test_rename_bad_position():
    code = "let x = 5\n"
    msgs, err = run_session([
        init_msg(),
        open_msg("file:///o.rn", code),
        {"jsonrpc": "2.0", "id": 2, "method": "textDocument/rename",
         "params": {"textDocument": {"uri": "file:///o.rn"}, "position": {"line": 0, "character": 100},
                    "newName": "z"}},
    ])
    m = find(msgs, id=2)
    assert m is not None
    # should return None (no word at position)
    assert m.get("result") is None


def test_document_symbol():
    code = "fn foo() { return 1 }\nclass Bar { fn baz() {} }\nlet x = 5\n"
    msgs, err = run_session([
        init_msg(),
        open_msg("file:///p.rn", code),
        {"jsonrpc": "2.0", "id": 2, "method": "textDocument/documentSymbol",
         "params": {"textDocument": {"uri": "file:///p.rn"}}},
    ])
    m = find(msgs, id=2)
    assert m is not None and isinstance(m.get("result"), list)
    names = [s["name"] for s in m["result"]]
    assert "foo" in names and "Bar" in names and "baz" in names and "x" in names


def test_workspace_symbol():
    code = "fn hello() { return 1 }\n"
    msgs, err = run_session([
        init_msg(),
        open_msg("file:///q.rn", code),
        {"jsonrpc": "2.0", "id": 2, "method": "workspace/symbol",
         "params": {"query": "hel"}},
    ])
    m = find(msgs, id=2)
    assert m is not None and isinstance(m.get("result"), list)
    assert any(s["name"] == "hello" for s in m["result"])


def test_workspace_symbol_empty_query():
    code = "fn foo() {}\n"
    msgs, err = run_session([
        init_msg(),
        open_msg("file:///r.rn", code),
        {"jsonrpc": "2.0", "id": 2, "method": "workspace/symbol",
         "params": {"query": ""}},
    ])
    m = find(msgs, id=2)
    assert m is not None and isinstance(m.get("result"), list)
    assert any(s["name"] == "foo" for s in m["result"])


def test_semantic_tokens():
    code = "let x = 5\nprint(x)\n"
    msgs, err = run_session([
        init_msg(),
        open_msg("file:///s.rn", code),
        {"jsonrpc": "2.0", "id": 2, "method": "textDocument/semanticTokens/full",
         "params": {"textDocument": {"uri": "file:///s.rn"}}},
    ])
    m = find(msgs, id=2)
    assert m is not None
    data = m["result"]["data"]
    assert isinstance(data, list) and len(data) > 0
    assert len(data) % 5 == 0


def test_formatting():
    code = "fn f(){return 1}\n"
    msgs, err = run_session([
        init_msg(),
        open_msg("file:///t.rn", code),
        {"jsonrpc": "2.0", "id": 2, "method": "textDocument/formatting",
         "params": {"textDocument": {"uri": "file:///t.rn"}, "options": {"tabSize": 2, "insertSpaces": True}}},
    ])
    m = find(msgs, id=2)
    assert m is not None and isinstance(m.get("result"), list)
    assert len(m["result"]) == 1
    assert "fn f" in m["result"][0]["newText"]


def test_formatting_invalid():
    code = "let x = \n"
    msgs, err = run_session([
        init_msg(),
        open_msg("file:///u.rn", code),
        {"jsonrpc": "2.0", "id": 2, "method": "textDocument/formatting",
         "params": {"textDocument": {"uri": "file:///u.rn"}, "options": {"tabSize": 2, "insertSpaces": True}}},
    ])
    m = find(msgs, id=2)
    assert m is not None
    # should return empty list on parse failure
    assert m.get("result") == []


def test_incremental_sync():
    code = "let x = 5\n"
    msgs, err = run_session([
        init_msg(),
        open_msg("file:///v.rn", code),
        {"jsonrpc": "2.0", "method": "textDocument/didChange",
         "params": {"textDocument": {"uri": "file:///v.rn", "version": 2},
                    "contentChanges": [{"range": {"start": {"line": 0, "character": 8},
                                                  "end": {"line": 0, "character": 9}},
                                       "text": "9"}]}},
        {"jsonrpc": "2.0", "id": 2, "method": "textDocument/hover",
         "params": {"textDocument": {"uri": "file:///v.rn"}, "position": {"line": 0, "character": 4}}},
    ])
    m = find(msgs, id=2)
    assert m is not None and m.get("result") is not None
    # no diagnostics for valid code
    notifs = [m for m in msgs if m.get("method") == "textDocument/publishDiagnostics"]
    if notifs:
        assert notifs[-1]["params"]["diagnostics"] == []


def test_multifile():
    code1 = "fn foo() { return 1 }\n"
    code2 = "print(foo())\n"
    msgs, err = run_session([
        init_msg(),
        open_msg("file:///a.rn", code1),
        open_msg("file:///b.rn", code2),
        {"jsonrpc": "2.0", "id": 2, "method": "workspace/symbol",
         "params": {"query": "foo"}},
    ])
    m = find(msgs, id=2)
    assert m is not None
    assert any(s["name"] == "foo" for s in m.get("result", []))


def test_unicode():
    code = 'let café = 5\nprint(café)\n'
    msgs, err = run_session([
        init_msg(),
        open_msg("file:///u.rn", code),
        {"jsonrpc": "2.0", "id": 2, "method": "textDocument/hover",
         "params": {"textDocument": {"uri": "file:///u.rn"}, "position": {"line": 1, "character": 6}}},
    ])
    m = find(msgs, id=2)
    assert m is not None
    notifs = [m for m in msgs if m.get("method") == "textDocument/publishDiagnostics"]
    if notifs:
        # no undefined variable errors
        diags = notifs[-1]["params"]["diagnostics"]
        assert not any("Undefined" in d["message"] for d in diags)


def test_bad_cursor_position():
    code = "let x = 5\n"
    msgs, err = run_session([
        init_msg(),
        open_msg("file:///w.rn", code),
        {"jsonrpc": "2.0", "id": 2, "method": "textDocument/hover",
         "params": {"textDocument": {"uri": "file:///w.rn"}, "position": {"line": 100, "character": 0}}},
        {"jsonrpc": "2.0", "id": 3, "method": "textDocument/definition",
         "params": {"textDocument": {"uri": "file:///w.rn"}, "position": {"line": 0, "character": 100}}},
    ])
    # should not crash; responses present
    m2 = find(msgs, id=2)
    m3 = find(msgs, id=3)
    assert m2 is not None and m3 is not None


def test_unknown_method():
    msgs, err = run_session([
        init_msg(),
        {"jsonrpc": "2.0", "id": 2, "method": "textDocument/nonexistent", "params": {}},
    ])
    m = find(msgs, id=2)
    assert m is not None and "error" in m


def test_shutdown_exit():
    msgs, err = run_session([
        init_msg(),
        {"jsonrpc": "2.0", "id": 2, "method": "shutdown", "params": {}},
    ], wait=0.5)
    m = find(msgs, id=2)
    assert m is not None and m.get("result") is None


def test_code_action():
    code = "let x = 5\n"
    msgs, err = run_session([
        init_msg(),
        open_msg("file:///ca.rn", code),
        {"jsonrpc": "2.0", "id": 2, "method": "textDocument/codeAction",
         "params": {"textDocument": {"uri": "file:///ca.rn"},
                    "range": {"start": {"line": 0, "character": 0}, "end": {"line": 0, "character": 5}},
                    "context": {"diagnostics": []}}},
    ])
    m = find(msgs, id=2)
    assert m is not None and isinstance(m.get("result"), list)
    assert len(m["result"]) >= 1


def test_diagnostics_type_error():
    code = "let x: int = \"hi\"\n"
    msgs, err = run_session([init_msg(), open_msg("file:///te.rn", code)])
    notifs = [m for m in msgs if m.get("method") == "textDocument/publishDiagnostics"]
    assert notifs
    diags = notifs[-1]["params"]["diagnostics"]
    assert any("Type error" in d["message"] for d in diags)