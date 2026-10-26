import subprocess, json, sys

proc = subprocess.Popen(
    [sys.executable, "-m", "renixx", "lsp"],
    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    cwd=r"C:\Users\Ryzen\Downloads\Новая папка\renixx",
    env={"PYTHONPATH": r"C:\Users\Ryzen\Downloads\Новая папка\renixx\src", "PATH": __import__("os").environ["PATH"]},
)

def send(msg):
    body = json.dumps(msg)
    header = "Content-Length: %d\r\n\r\n" % len(body.encode())
    proc.stdin.write((header + body).encode())
    proc.stdin.flush()

def read_one():
    # read headers
    headers = {}
    while True:
        line = proc.stdout.readline()
        if not line:
            return None
        line = line.decode().rstrip("\r\n")
        if line == "":
            break
        if ":" in line:
            k, v = line.split(":", 1)
            headers[k.strip().lower()] = v.strip()
    n = int(headers.get("content-length", 0))
    if n == 0:
        return None
    body = proc.stdout.read(n)
    return json.loads(body)

send({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"capabilities": {}}})
r = read_one()
print("INIT:", json.dumps(r, indent=2)[:500])

# didOpen
code = "fn fib(n) { if n <= 1 { return n } return fib(n-1)+fib(n-2) }\nprint(fib(10))\n"
send({"jsonrpc": "2.0", "method": "textDocument/didOpen", "params": {"textDocument": {"uri": "file:///test.rn", "languageId": "renixx", "version": 1, "text": code}}})
# read diagnostics notification
import time; time.sleep(0.5)
# try completion
send({"jsonrpc": "2.0", "id": 2, "method": "textDocument/completion", "params": {"textDocument": {"uri": "file:///test.rn"}, "position": {"line": 1, "character": 6}}})
# read until response with id 2
while True:
    r = read_one()
    if r is None:
        break
    if r.get("id") == 2:
        print("COMPLETION count:", len(r["result"]) if r and "result" in r else r)
        break
    # print notifications
    if "method" in r:
        print("NOTIF:", r["method"], r.get("params", {}).get("diagnostics", [])[:1])

send({"jsonrpc": "2.0", "id": 3, "method": "shutdown", "params": {}})
r = read_one()
print("SHUTDOWN:", r)
send({"jsonrpc": "2.0", "method": "exit", "params": {}})
proc.wait(timeout=5)
print("stderr:", proc.stderr.read().decode()[:500])