"""Automated tests for the Renixx LSP server."""
import json
import os
import subprocess
import sys
import threading
import time
import queue
import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC = os.path.join(ROOT, "src")
PYTHON = sys.executable


def run_session(messages, timeout=5.0):
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
    expected = []
    for m in messages:
        body = json.dumps(m)
        proc.stdin.write(("Content-Length: %d\r\n\r\n" % len(body.encode()) + body).encode())
        proc.stdin.flush()
        if m.get("id") is not None:
            expected.append(("id", m["id"]))
        elif m.get("method") in ("textDocument/didOpen", "textDocument/didChange"):
            expected.append(("diagnostics", m["params"]["textDocument"]["uri"]))

    msgs = []
    for kind, value in expected:
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            try:
                response = q.get(timeout=remaining)
            except queue.Empty:
                break
            msgs.append(response)
            if kind == "id" and response.get("id") == value:
                break
            if (kind == "diagnostics"
                    and response.get("method") == "textDocument/publishDiagnostics"
                    and response.get("params", {}).get("uri") == value):
                break

    proc.stdin.close()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)
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

def test_hover_shows_inferred_variable_type_and_utf16_range():
    code = 'let text = "😀"; let count = 1; print(count)\n'
    line = code.splitlines()[0]
    target_col = line.rindex("count")
    target_cursor = target_col + 2
    target_utf16_cursor = len(line[:target_cursor].encode("utf-16-le")) // 2
    msgs, err = run_session([
        init_msg(),
        open_msg("file:///hover-type.rn", code),
        {"jsonrpc": "2.0", "id": 2, "method": "textDocument/hover",
         "params": {"textDocument": {"uri": "file:///hover-type.rn"},
                    "position": {"line": 0, "character": target_utf16_cursor}}},
    ])
    result = find(msgs, id=2)["result"]
    assert "count: int" in result["contents"]["value"]
    utf16_col = len(line[:target_col].encode("utf-16-le")) // 2
    assert result["range"]["start"] == {"line": 0, "character": utf16_col}
    assert result["range"]["end"] == {"line": 0, "character": utf16_col + len("count")}


def test_hover_shows_parameterized_variable_and_function_signatures():
    code = (
        "let values: list[dict[string, int]] = []\n"
        "fn lookup(items: list[dict[string, int]]) -> list[dict[string, int]] { return items }\n"
        "print(values)\n"
        "lookup([])\n"
    )
    msgs, err = run_session([
        init_msg(),
        open_msg("file:///hover-generics.rn", code),
        {"jsonrpc": "2.0", "id": 2, "method": "textDocument/hover",
         "params": {"textDocument": {"uri": "file:///hover-generics.rn"},
                    "position": {"line": 2, "character": 7}},
        },
        {"jsonrpc": "2.0", "id": 3, "method": "textDocument/hover",
         "params": {"textDocument": {"uri": "file:///hover-generics.rn"},
                    "position": {"line": 3, "character": 2}},
        },
    ])
    variable = find(msgs, id=2)["result"]["contents"]["value"]
    function = find(msgs, id=3)["result"]["contents"]["value"]
    assert "values: list[dict[string, int]]" in variable
    expected_signature = (
        "fn lookup(items: list[dict[string, int]]) -> list[dict[string, int]]"
    )
    assert expected_signature in function


def test_signature_help_includes_parameterized_types_and_active_parameter():
    code = (
        "fn consume(items: list[dict[string, int]], count: int) -> bool { return true }\n"
        'let marker = "😀"; consume([], )\n'
    )
    msgs, err = run_session([
        init_msg(),
        open_msg("file:///signature-generics.rn", code),
        {"jsonrpc": "2.0", "id": 2, "method": "textDocument/signatureHelp",
         "params": {"textDocument": {"uri": "file:///signature-generics.rn"},
                    "position": {"line": 1, "character": (
                        len('let marker = "😀"; consume([], '.encode("utf-16-le")) // 2
                    )}}},
    ])
    result = find(msgs, id=2)["result"]
    signature = result["signatures"][0]
    assert signature["label"] == (
        "fn consume(items: list[dict[string, int]], count: int) -> bool"
    )
    assert signature["parameters"][0]["label"] == "items: list[dict[string, int]]"
    assert signature["parameters"][1]["label"] == "count: int"
    assert result["activeParameter"] == 1


def test_completion_contains_only_symbols_visible_in_current_function_scope():
    code = (
        "let global_value = 1\n"
        "fn outer(arg: string) {\n"
        "  let local_value = 2\n"
        "  let items: list[int] = []\n"
        "  for item in items {\n"
        "    if true {\n"
        "      let branch_value: list[int] = []\n"
        "      print()\n"
        "    }\n"
        "  }\n"
        "  try {\n"
        "    print()\n"
        "  } catch problem {\n"
        "    print()\n"
        "  }\n"
        "}\n"
        "fn other() { let hidden_value = 3 }\n"
    )
    msgs, err = run_session([
        init_msg(),
        open_msg("file:///completion-scope.rn", code),
        {"jsonrpc": "2.0", "id": 2, "method": "textDocument/completion",
         "params": {"textDocument": {"uri": "file:///completion-scope.rn"},
                    "position": {"line": 7, "character": 12}}},
        {"jsonrpc": "2.0", "id": 3, "method": "textDocument/completion",
         "params": {"textDocument": {"uri": "file:///completion-scope.rn"},
                    "position": {"line": 13, "character": 10}}},
    ])
    items = find(msgs, id=2)["result"]
    labels = {item["label"] for item in items}
    assert {
        "global_value", "outer", "arg", "local_value", "items", "item",
        "branch_value", "print",
    } <= labels
    assert "hidden_value" not in labels
    local_item = next(item for item in items if item["label"] == "local_value")
    assert local_item["detail"] == "variable: int"
    branch_item = next(item for item in items if item["label"] == "branch_value")
    assert branch_item["detail"] == "variable: list[int]"
    loop_item = next(item for item in items if item["label"] == "item")
    assert loop_item["detail"] == "variable: int"
    catch_items = find(msgs, id=3)["result"]
    catch_labels = {item["label"] for item in catch_items}
    assert {"global_value", "outer", "arg", "local_value", "items", "problem"} <= catch_labels
    assert "item" not in catch_labels
    assert "branch_value" not in catch_labels


def test_signature_help_recovers_prior_declarations_before_incomplete_call():
    code = "fn identity(value: list[int]) -> list[int] { return value }\nidentity("
    msgs, err = run_session([
        init_msg(),
        open_msg("file:///signature-incomplete.rn", code),
        {"jsonrpc": "2.0", "id": 2, "method": "textDocument/signatureHelp",
         "params": {"textDocument": {"uri": "file:///signature-incomplete.rn"},
                    "position": {"line": 1, "character": len("identity(")}}},
        {"jsonrpc": "2.0", "id": 3, "method": "textDocument/completion",
         "params": {"textDocument": {"uri": "file:///signature-incomplete.rn"},
                    "position": {"line": 1, "character": len("identity(")}}},
    ])
    signature = find(msgs, id=2)["result"]
    assert signature["signatures"][0]["label"] == "fn identity(value: list[int]) -> list[int]"
    assert signature["activeParameter"] == 0
    assert isinstance(find(msgs, id=3)["result"], list)


def test_hover_and_completion_do_not_crash_on_syntax_errors():
    code = "let value = \n"
    msgs, err = run_session([
        init_msg(),
        open_msg("file:///features-invalid.rn", code),
        {"jsonrpc": "2.0", "id": 2, "method": "textDocument/hover",
         "params": {"textDocument": {"uri": "file:///features-invalid.rn"},
                    "position": {"line": 0, "character": 4}}},
        {"jsonrpc": "2.0", "id": 3, "method": "textDocument/completion",
         "params": {"textDocument": {"uri": "file:///features-invalid.rn"},
                    "position": {"line": 0, "character": 4}}},
    ])
    assert find(msgs, id=2)["result"] is None
    assert isinstance(find(msgs, id=3)["result"], list)
    assert err == ""


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
    ])
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


def test_lsp_type_checker_var_mismatch():
    # Type checker: variable type mismatch
    code = 'let x: int = "hello"\n'
    msgs, err = run_session([init_msg(), open_msg("file:///tc1.rn", code)])
    notifs = [m for m in msgs if m.get("method") == "textDocument/publishDiagnostics"]
    assert notifs
    diags = notifs[-1]["params"]["diagnostics"]
    assert any("Type error" in d["message"] for d in diags)


def test_lsp_type_checker_func_arg():
    # Type checker: function argument type mismatch
    code = 'fn add(a: int, b: int) -> int { return a + b }\nlet y = add(1, "a")\n'
    msgs, err = run_session([init_msg(), open_msg("file:///tc2.rn", code)])
    notifs = [m for m in msgs if m.get("method") == "textDocument/publishDiagnostics"]
    assert notifs
    diags = notifs[-1]["params"]["diagnostics"]
    assert any("Type error" in d["message"] for d in diags)


def test_lsp_type_checker_func_return():
    # Type checker: function return type mismatch
    code = 'fn f() -> int { return "hello" }\n'
    msgs, err = run_session([init_msg(), open_msg("file:///tc3.rn", code)])
    notifs = [m for m in msgs if m.get("method") == "textDocument/publishDiagnostics"]
    assert notifs
    diags = notifs[-1]["params"]["diagnostics"]
    assert any("Type error" in d["message"] for d in diags)


def test_lsp_type_checker_valid_code():
    # Type checker: valid code produces no type errors
    code = 'let x: int = 5\nfn add(a: int, b: int) -> int { return a + b }\nlet y: int = add(1, 2)\n'
    msgs, err = run_session([init_msg(), open_msg("file:///tc4.rn", code)])
    notifs = [m for m in msgs if m.get("method") == "textDocument/publishDiagnostics"]
    assert notifs
    diags = notifs[-1]["params"]["diagnostics"]
    # No type errors (may have no diagnostics at all)
    type_errors = [d for d in diags if "Type error" in d["message"]]
    assert type_errors == [], "unexpected type errors: %r" % type_errors


def test_lsp_parameterized_types_accept_valid_values():
    code = (
        "let items: list[int] = [1, 2]\n"
        'let counts: dict[string, int] = {"a": 1}\n'
        'let nested: list[dict[string, int]] = [{"a": 1}]\n'
    )
    msgs, err = run_session([
        init_msg(),
        open_msg("file:///generic-valid.rn", code),
    ])
    notifs = [m for m in msgs if m.get("method") == "textDocument/publishDiagnostics"]

    assert notifs
    assert notifs[-1]["params"]["diagnostics"] == []


def test_lsp_parameterized_function_annotations_do_not_report_unknown_type():
    code = (
        "fn identity(items: list[int]) -> list[int] {\n"
        "  return items\n"
        "}\n"
    )
    msgs, err = run_session([
        init_msg(),
        open_msg("file:///generic-function.rn", code),
    ])
    notifs = [m for m in msgs if m.get("method") == "textDocument/publishDiagnostics"]

    assert notifs
    assert notifs[-1]["params"]["diagnostics"] == []


@pytest.mark.parametrize(
    ("uri", "code", "expected_col", "expected_message"),
    [
        (
            "file:///generic-list-mismatch.rn",
            'let data: list[int] = "bad"\n',
            4,
            "Type error: expected list[int], got string",
        ),
        (
            "file:///generic-dict-mismatch.rn",
            'let data: dict[string, int] = "bad"\n',
            4,
            "Type error: expected dict[string, int], got string",
        ),
        (
            "file:///generic-dict-element-mismatch.rn",
            'let data: dict[string, int] = {"a": "bad"}\n',
            36,
            "Type error: expected int, got string",
        ),
        (
            "file:///generic-nested-mismatch.rn",
            'let data: list[dict[string, int]] = "bad"\n',
            4,
            "Type error: expected list[dict[string, int]], got string",
        ),
        (
            "file:///generic-nested-element-mismatch.rn",
            'let data: list[dict[string, int]] = [{"a": "bad"}]\n',
            43,
            "Type error: expected int, got string",
        ),
    ],
)
def test_lsp_parameterized_type_errors_have_precise_ranges(
    uri, code, expected_col, expected_message
):
    msgs, err = run_session([init_msg(), open_msg(uri, code)])
    notifs = [m for m in msgs if m.get("method") == "textDocument/publishDiagnostics"]
    assert notifs
    diags = notifs[-1]["params"]["diagnostics"]
    matching = [d for d in diags if d["message"] == expected_message]

    assert len(matching) == 1
    assert matching[0]["range"]["start"] == {"line": 0, "character": expected_col}
    assert matching[0]["range"]["end"]["character"] > matching[0]["range"]["start"]["character"]

def test_lsp_parameterized_diagnostic_range_uses_utf16_after_emoji():
    code = 'let s = "😀"; let data: list[int] = "bad"\n'
    data_col = code.index("data")
    msgs, err = run_session([
        init_msg(),
        open_msg("file:///generic-emoji.rn", code),
    ])
    notifs = [m for m in msgs if m.get("method") == "textDocument/publishDiagnostics"]
    assert notifs
    diags = notifs[-1]["params"]["diagnostics"]
    mismatch = [
        d for d in diags
        if d["message"] == "Type error: expected list[int], got string"
    ]

    assert len(mismatch) == 1
    assert mismatch[0]["range"]["start"] == {
        "line": 0,
        "character": data_col + 1,
    }
    assert mismatch[0]["range"]["end"] == {
        "line": 0,
        "character": data_col + 1 + len("data"),
    }

def test_lsp_unknown_non_generic_type_uses_utf16_range():
    code = 'let s = "😀"; let x: Foo = 1\n'
    py_col = code.index("Foo")
    utf16_col = len(code[:py_col].encode("utf-16-le")) // 2
    msgs, err = run_session([
        init_msg(),
        open_msg("file:///unknown-type-emoji.rn", code),
    ])
    notifs = [m for m in msgs if m.get("method") == "textDocument/publishDiagnostics"]
    assert notifs
    matches = [
        diagnostic
        for diagnostic in notifs[-1]["params"]["diagnostics"]
        if diagnostic["message"] == "Unknown type 'Foo'"
    ]

    assert len(matches) == 1
    assert matches[0]["range"]["start"] == {"line": 0, "character": utf16_col}
    assert matches[0]["range"]["end"] == {
        "line": 0,
        "character": utf16_col + len("Foo"),
    }


@pytest.mark.parametrize(
    ("uri", "code", "unknown_col"),
    [
        pytest.param(
            "file:///unknown-list-type.rn",
            "let xs: list[Foo] = []\n",
            13,
        ),
        pytest.param(
            "file:///unknown-dict-parameter.rn",
            "fn f(a: dict[string, Bar]) {}\n",
            21,
        ),
    ],
)
def test_lsp_unknown_generic_argument_has_precise_diagnostic(uri, code, unknown_col):
    msgs, err = run_session([init_msg(), open_msg(uri, code)])
    notifs = [m for m in msgs if m.get("method") == "textDocument/publishDiagnostics"]
    assert notifs
    unknown_types = [
        diagnostic
        for diagnostic in notifs[-1]["params"]["diagnostics"]
        if diagnostic["message"].startswith("Unknown type")
    ]

    assert len(unknown_types) == 1
    assert unknown_types[0]["range"]["start"] == {
        "line": 0,
        "character": unknown_col,
    }
    assert unknown_types[0]["range"]["end"] == {
        "line": 0,
        "character": unknown_col + 3,
    }


def test_lsp_hover_shows_full_generic_type_with_unknown_argument():
    code = "let xs: list[Foo] = []\nprint(xs)\n"
    msgs, err = run_session([
        init_msg(),
        open_msg("file:///hover-unknown-generic.rn", code),
        {"jsonrpc": "2.0", "id": 2, "method": "textDocument/hover",
         "params": {"textDocument": {"uri": "file:///hover-unknown-generic.rn"},
                    "position": {"line": 1, "character": 7}}},
    ])
    hover = find(msgs, id=2)["result"]

    assert "xs: list[Foo]" in hover["contents"]["value"]


def test_lsp_type_checker_no_crash_on_bad_code():
    # Type checker should not crash LSP on malformed input
    code = 'let x: int = \n'
    msgs, err = run_session([init_msg(), open_msg("file:///tc5.rn", code)])
    notifs = [m for m in msgs if m.get("method") == "textDocument/publishDiagnostics"]
    assert notifs  # should still publish (syntax error)


def test_lsp_dedup_same_message_different_cols():
    # Regression: same message on same line with different columns should NOT be deduped.
    code = "let y = x + x\n"
    msgs, err = run_session([init_msg(), open_msg("file:///dedup1.rn", code)])
    notifs = [m for m in msgs if m.get("method") == "textDocument/publishDiagnostics"]
    assert notifs
    diags = notifs[-1]["params"]["diagnostics"]
    assert len(diags) == 2, "expected 2 diagnostics, got %d" % len(diags)


def test_lsp_dedup_cross_source():
    # Regression: semantic + typechecker same message on same line should be deduped.
    code = 'let x: int = "hi"\n'
    msgs, err = run_session([init_msg(), open_msg("file:///dedup2.rn", code)])
    notifs = [m for m in msgs if m.get("method") == "textDocument/publishDiagnostics"]
    assert notifs
    diags = notifs[-1]["params"]["diagnostics"]
    type_errors = [d for d in diags if "Type error" in d["message"]]
    assert len(type_errors) == 1, "expected 1 type error, got %d" % len(type_errors)


def test_lsp_dedup_different_lines_preserved():
    # Regression: different errors on different lines should be preserved.
    code = 'let x: int = "hi"\nlet y: float = "bye"\n'
    msgs, err = run_session([init_msg(), open_msg("file:///dedup3.rn", code)])
    notifs = [m for m in msgs if m.get("method") == "textDocument/publishDiagnostics"]
    assert notifs
    diags = notifs[-1]["params"]["diagnostics"]
    assert len(diags) == 2, "expected 2 diagnostics, got %d" % len(diags)


def test_lsp_type_checker_exception_no_hide():
    # Type checker exception should not hide semantic diagnostics.
    code = "let z = unknown_var\n"
    msgs, err = run_session([init_msg(), open_msg("file:///dedup4.rn", code)])
    notifs = [m for m in msgs if m.get("method") == "textDocument/publishDiagnostics"]
    assert notifs
    diags = notifs[-1]["params"]["diagnostics"]
    assert any("Undefined variable" in d["message"] for d in diags)


def test_diagnostic_column_accuracy():
    # Regression test: two identical identifiers on one line should produce
    # diagnostics at their respective columns, not both at the first occurrence.
    code = "let y = x + x\n"
    msgs, err = run_session([init_msg(), open_msg("file:///col.rn", code)])
    notifs = [m for m in msgs if m.get("method") == "textDocument/publishDiagnostics"]
    assert notifs
    diags = notifs[-1]["params"]["diagnostics"]
    assert len(diags) == 2, "expected 2 diagnostics, got %d" % len(diags)
    cols = sorted(d["range"]["start"]["character"] for d in diags)
    # "let y = x + x": first x at col 8, second x at col 12
    assert cols == [8, 12], "expected columns [8, 12], got %r" % cols


def test_diagnostic_column_string_not_matched():
    # Regression: identifier inside string literal must not be selected.
    code = 'let x = "x" + x\n'
    msgs, err = run_session([init_msg(), open_msg("file:///colstr.rn", code)])
    notifs = [m for m in msgs if m.get("method") == "textDocument/publishDiagnostics"]
    assert notifs
    diags = notifs[-1]["params"]["diagnostics"]
    assert len(diags) == 1
    assert diags[0]["range"]["start"]["character"] == 14


def test_diagnostic_column_usage_not_declaration():
    # Regression: diagnostic for undefined var must point to usage, not declaration.
    code = "if (true) { let x; } print(x)\n"
    msgs, err = run_session([init_msg(), open_msg("file:///coluse.rn", code)])
    notifs = [m for m in msgs if m.get("method") == "textDocument/publishDiagnostics"]
    assert notifs
    diags = notifs[-1]["params"]["diagnostics"]
    assert len(diags) == 1
    assert diags[0]["range"]["start"]["character"] == 27


def test_diagnostic_column_redeclaration():
    # Regression: "already defined" must point to declaration name, not usage.
    code = "let x = x; let x = x\n"
    msgs, err = run_session([init_msg(), open_msg("file:///colredecl.rn", code)])
    notifs = [m for m in msgs if m.get("method") == "textDocument/publishDiagnostics"]
    assert notifs
    diags = notifs[-1]["params"]["diagnostics"]
    redecl = [d for d in diags if "already defined" in d["message"]]
    assert redecl
    assert redecl[0]["range"]["start"]["character"] == 15


def test_diagnostic_column_interpolation():
    # Regression: identifier inside string interpolation must get correct position.
    code = 'let x = "prefix {missing}"\n'
    msgs, err = run_session([init_msg(), open_msg("file:///colinterp.rn", code)])
    notifs = [m for m in msgs if m.get("method") == "textDocument/publishDiagnostics"]
    assert notifs
    diags = notifs[-1]["params"]["diagnostics"]
    assert len(diags) == 1
    assert diags[0]["range"]["start"]["character"] == 17


def test_diagnostic_column_const_type_error():
    # Regression: const with type annotation error points to type name.
    code = 'const x: int = "hi"\n'
    msgs, err = run_session([init_msg(), open_msg("file:///colconst.rn", code)])
    notifs = [m for m in msgs if m.get("method") == "textDocument/publishDiagnostics"]
    assert notifs
    diags = notifs[-1]["params"]["diagnostics"]
    assert any("Type error" in d["message"] for d in diags)
    te = [d for d in diags if "Type error" in d["message"]][0]
    # Type checker points to variable name (col 6), not type annotation (col 9)
    assert te["range"]["start"]["character"] == 6


def test_diagnostic_column_const_redeclaration():
    # Regression: const redeclaration points to second declaration name.
    code = "const x = 1\nconst x = 2\n"
    msgs, err = run_session([init_msg(), open_msg("file:///colconstre.rn", code)])
    notifs = [m for m in msgs if m.get("method") == "textDocument/publishDiagnostics"]
    assert notifs
    diags = notifs[-1]["params"]["diagnostics"]
    redecl = [d for d in diags if "already defined" in d["message"]]
    assert redecl
    assert redecl[0]["range"]["start"]["line"] == 1
    assert redecl[0]["range"]["start"]["character"] == 6


def _decode_semantic_tokens(data):
    """Decode delta-encoded semantic tokens into list of (line, col, length)."""
    result = []
    line = 0
    col = 0
    i = 0
    while i < len(data):
        dl, dc, length, ttype, mods = data[i:i+5]
        line += dl
        col = col + dc if dl == 0 else dc
        result.append((line, col, length, ttype))
        i += 5
    return result


def test_semantic_tokens_no_double_utf16():
    # Regression: semantic token for x after emoji should be at UTF-16 col 18, not 19.
    code = 'let s = "😀"; let x = 1\n'
    msgs, err = run_session([
        init_msg(),
        open_msg("file:///semutf.rn", code),
        {"jsonrpc": "2.0", "id": 2, "method": "textDocument/semanticTokens/full",
         "params": {"textDocument": {"uri": "file:///semutf.rn"}}},
    ])
    m = find(msgs, id=2)
    assert m is not None and m.get("result") is not None
    decoded = _decode_semantic_tokens(m["result"]["data"])
    # find token with length 1 at col 18 (the 'x')
    x_tokens = [t for t in decoded if t[2] == 1 and t[1] == 18]
    assert x_tokens, "expected semantic token for x at UTF-16 col 18, got %r" % decoded


def test_rename_after_emoji():
    # Regression: rename at UTF-16 position after two emoji should find x.
    code = 'let s = "😀😀"; let x = 1\n'
    msgs, err = run_session([
        init_msg(),
        open_msg("file:///renemoji.rn", code),
        {"jsonrpc": "2.0", "id": 2, "method": "textDocument/rename",
         "params": {"textDocument": {"uri": "file:///renemoji.rn"}, "position": {"line": 0, "character": 20},
                    "newName": "y"}},
    ])
    m = find(msgs, id=2)
    assert m is not None and m.get("result") is not None
    changes = m["result"]["changes"]
    assert "file:///renemoji.rn" in changes
    edits = changes["file:///renemoji.rn"]
    assert len(edits) >= 1
    assert edits[0]["range"]["start"]["character"] == 20


def test_diagnostic_multiline_param_type():
    # Regression: unknown type in multi-line param must report correct line and col.
    code = "fn f(\n  x: Wrong\n) {}\n"
    msgs, err = run_session([init_msg(), open_msg("file:///mlparam.rn", code)])
    notifs = [m for m in msgs if m.get("method") == "textDocument/publishDiagnostics"]
    assert notifs
    diags = notifs[-1]["params"]["diagnostics"]
    ut = [d for d in diags if "Unknown type" in d["message"]]
    assert ut, "expected Unknown type diagnostic"
    assert ut[0]["range"]["start"]["line"] == 1
    assert ut[0]["range"]["start"]["character"] == 5


def test_diagnostic_multiline_return_type():
    # Regression: unknown return type on second line must report correct line and col.
    code = "fn f() ->\n  Wrong {}\n"
    msgs, err = run_session([init_msg(), open_msg("file:///mlret.rn", code)])
    notifs = [m for m in msgs if m.get("method") == "textDocument/publishDiagnostics"]
    assert notifs
    diags = notifs[-1]["params"]["diagnostics"]
    ut = [d for d in diags if "Unknown type" in d["message"]]
    assert ut, "expected Unknown type diagnostic"
    assert ut[0]["range"]["start"]["line"] == 1
    assert ut[0]["range"]["start"]["character"] == 2


def test_definition_not_in_string():
    # Regression: find_definitions must not pick identifier inside string.
    code = 'let s = "f"; fn f(a) {}\n'
    msgs, err = run_session([
        init_msg(),
        open_msg("file:///defstr.rn", code),
        {"jsonrpc": "2.0", "id": 2, "method": "textDocument/definition",
         "params": {"textDocument": {"uri": "file:///defstr.rn"}, "position": {"line": 0, "character": 16}}},
    ])
    m = find(msgs, id=2)
    assert m is not None and m.get("result") is not None
    # f function should be at col 16, not col 9 (inside string)
    assert m["result"]["range"]["start"]["character"] == 16


def test_class_definition_not_in_string():
    # Regression: class definition must not pick name inside string.
    code = 'let s = "Foo"; class Foo {}\n'
    msgs, err = run_session([
        init_msg(),
        open_msg("file:///defcls.rn", code),
        {"jsonrpc": "2.0", "id": 2, "method": "textDocument/definition",
         "params": {"textDocument": {"uri": "file:///defcls.rn"}, "position": {"line": 0, "character": 22}}},
    ])
    m = find(msgs, id=2)
    assert m is not None and m.get("result") is not None
    # Foo class should be at col 21, not col 9 (inside string)
    assert m["result"]["range"]["start"]["character"] == 21


def test_lsp_dedup_same_message_at_distinct_locations():
    code = "fn f(x: Weird) {} let y: Weird = 1\n"
    msgs, err = run_session([
        init_msg(),
        open_msg("file:///dedup-locations.rn", code),
    ])
    notifs = [m for m in msgs if m.get("method") == "textDocument/publishDiagnostics"]
    assert notifs
    unknown_types = [
        d for d in notifs[-1]["params"]["diagnostics"]
        if d["message"] == "Unknown type 'Weird'"
    ]

    assert len(unknown_types) == 2
    assert sorted(d["range"]["start"]["character"] for d in unknown_types) == [8, 25]


def test_lsp_dedup_identical_unknown_type_from_both_analyzers():
    code = "fn f(x: Weird) {}\n"
    msgs, err = run_session([
        init_msg(),
        open_msg("file:///dedup-identical.rn", code),
    ])
    notifs = [m for m in msgs if m.get("method") == "textDocument/publishDiagnostics"]
    assert notifs
    unknown_types = [
        d for d in notifs[-1]["params"]["diagnostics"]
        if d["message"] == "Unknown type 'Weird'"
    ]

    assert len(unknown_types) == 1
    assert unknown_types[0]["range"]["start"]["character"] == 8


def test_definition_finds_nested_function():
    code = "fn outer() { fn inner() { return 1 } return inner() }\n"
    call_col = code.rindex("inner")
    msgs, err = run_session([
        init_msg(),
        open_msg("file:///nested-def.rn", code),
        {"jsonrpc": "2.0", "id": 2, "method": "textDocument/definition",
         "params": {"textDocument": {"uri": "file:///nested-def.rn"},
                    "position": {"line": 0, "character": call_col}}},
    ])
    response = find(msgs, id=2)

    assert response is not None and response.get("result") is not None
    assert response["result"]["range"]["start"] == {"line": 0, "character": 16}
    assert response["result"]["range"]["end"] == {"line": 0, "character": 21}


def test_definition_finds_each_list_destructured_name():
    code = "let [a, b] = [1, 2]\nprint(a, b)\n"
    msgs, err = run_session([
        init_msg(),
        open_msg("file:///list-destructure-def.rn", code),
        {"jsonrpc": "2.0", "id": 2, "method": "textDocument/definition",
         "params": {"textDocument": {"uri": "file:///list-destructure-def.rn"},
                    "position": {"line": 1, "character": 6}}},
        {"jsonrpc": "2.0", "id": 3, "method": "textDocument/definition",
         "params": {"textDocument": {"uri": "file:///list-destructure-def.rn"},
                    "position": {"line": 1, "character": 9}}},
    ])
    first = find(msgs, id=2)
    second = find(msgs, id=3)

    assert first is not None and first.get("result") is not None
    assert second is not None and second.get("result") is not None
    assert first["result"]["range"]["start"] == {"line": 0, "character": 5}
    assert second["result"]["range"]["start"] == {"line": 0, "character": 8}
    assert first["result"]["range"]["end"] == {"line": 0, "character": 6}
    assert second["result"]["range"]["end"] == {"line": 0, "character": 9}



def test_definition_finds_each_dict_destructured_name():
    code = 'let {a, b} = {"a": 1, "b": 2}\nprint(a, b)\n'
    msgs, err = run_session([
        init_msg(),
        open_msg("file:///dict-destructure-def.rn", code),
        {"jsonrpc": "2.0", "id": 2, "method": "textDocument/definition",
         "params": {"textDocument": {"uri": "file:///dict-destructure-def.rn"},
                    "position": {"line": 1, "character": 6}}},
        {"jsonrpc": "2.0", "id": 3, "method": "textDocument/definition",
         "params": {"textDocument": {"uri": "file:///dict-destructure-def.rn"},
                    "position": {"line": 1, "character": 9}}},
    ])
    first = find(msgs, id=2)
    second = find(msgs, id=3)

    assert first is not None and first.get("result") is not None
    assert second is not None and second.get("result") is not None
    assert first["result"]["range"]["start"] == {"line": 0, "character": 5}
    assert second["result"]["range"]["start"] == {"line": 0, "character": 8}
    assert first["result"]["range"]["end"] == {"line": 0, "character": 6}
    assert second["result"]["range"]["end"] == {"line": 0, "character": 9}