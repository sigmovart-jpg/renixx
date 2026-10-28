#!/usr/bin/env python3
"""Renixx Agent Orchestrator - bridges OpenCode and GitHub Copilot.

Usage:
    python tools/agent.py task "description"     Create a new task
    python tools/agent.py status                 Show current status
    python tools/agent.py run                    Run OpenCode on pending (todo) tasks
    python tools/agent.py fix                    Apply fixes from reviews (changes-requested)
    python tools/agent.py done TASK-XXX          Mark task as done after approved review
    python tools/agent.py cycle                  Full cycle: run -> wait for review -> fix
    python tools/agent.py lock                    Acquire processing lock
    python tools/agent.py unlock                  Release processing lock
"""
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AGENT_DIR = ROOT / ".agent"
TASKS_DIR = AGENT_DIR / "tasks"
REVIEWS_DIR = AGENT_DIR / "reviews"
TEMPLATES_DIR = AGENT_DIR / "templates"
STATUS_FILE = AGENT_DIR / "status.json"
HANDOFF_FILE = AGENT_DIR / "handoff.md"
DECISIONS_FILE = AGENT_DIR / "decisions.md"
LOCK_FILE = AGENT_DIR / ".lock"
LOG_FILE = AGENT_DIR / "agent.log"

MAX_RETRIES = 3
MAX_REVIEW_WAIT = 10  # max polls waiting for Copilot review
REVIEW_POLL_INTERVAL = 30  # seconds between polls

PYTHON = sys.executable


def configure(root):
    """Override root directory for testing. Recomputes all derived paths."""
    global ROOT, AGENT_DIR, TASKS_DIR, REVIEWS_DIR, TEMPLATES_DIR
    global STATUS_FILE, HANDOFF_FILE, DECISIONS_FILE, LOCK_FILE, LOG_FILE
    ROOT = Path(root)
    AGENT_DIR = ROOT / ".agent"
    TASKS_DIR = AGENT_DIR / "tasks"
    REVIEWS_DIR = AGENT_DIR / "reviews"
    TEMPLATES_DIR = AGENT_DIR / "templates"
    STATUS_FILE = AGENT_DIR / "status.json"
    HANDOFF_FILE = AGENT_DIR / "handoff.md"
    DECISIONS_FILE = AGENT_DIR / "decisions.md"
    LOCK_FILE = AGENT_DIR / ".lock"
    LOG_FILE = AGENT_DIR / "agent.log"


def log(msg):
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    line = f"[{ts}] {msg}"
    print(line)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def load_status():
    if STATUS_FILE.exists():
        return json.loads(STATUS_FILE.read_text(encoding="utf-8"))
    return {"version": 1, "status": "idle", "current_task": None,
            "assigned_to": None, "branch": None, "last_updated": None,
            "last_action": None, "notes": ""}


def save_status(status):
    status["last_updated"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    STATUS_FILE.write_text(json.dumps(status, indent=2, ensure_ascii=False), encoding="utf-8")


def next_task_id():
    ids = []
    for f in TASKS_DIR.glob("TASK-*.md"):
        try:
            num = int(f.stem.split("-")[1])
            ids.append(num)
        except (ValueError, IndexError):
            pass
    return "TASK-%03d" % (max(ids, default=0) + 1)


def acquire_lock():
    if LOCK_FILE.exists():
        content = LOCK_FILE.read_text(encoding="utf-8").strip()
        log(f"Lock exists: {content}. Another process may be running.")
        return False
    LOCK_FILE.write_text(f"pid={os.getpid()} time={datetime.now(timezone.utc).isoformat()}", encoding="utf-8")
    return True


def release_lock():
    if LOCK_FILE.exists():
        LOCK_FILE.unlink()


def cmd_task(description):
    """Create a new task."""
    task_id = next_task_id()
    task_file = TASKS_DIR / f"{task_id}.md"
    template = (TEMPLATES_DIR / "TASK-TEMPLATE.md").read_text(encoding="utf-8")
    content = template.replace("TASK-XXX", task_id).replace("Краткое название задачи", description)
    content = content.replace("**Статус:** idle | todo | in-progress | review | changes-requested | done | blocked",
                             "**Статус:** todo")
    content = content.replace("**Назначено:** opencode | copilot | human", "**Назначено:** opencode")
    content = content.replace("**Создано:** opencode | copilot | human", "**Создано:** human")
    content = content.replace("**Дата создания:** YYYY-MM-DD", "**Дата создания:** %s" % datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    task_file.write_text(content, encoding="utf-8")
    log(f"Created task {task_id}: {description}")
    print(f"Task created: {task_id}")
    print(f"File: {task_file}")
    print(f"Next: python tools/agent.py run")


def cmd_status():
    """Show current status."""
    status = load_status()
    print(json.dumps(status, indent=2, ensure_ascii=False))
    print()
    tasks = sorted(TASKS_DIR.glob("TASK-*.md"))
    if tasks:
        print("Tasks:")
        for t in tasks:
            text = t.read_text(encoding="utf-8")
            status_line = "unknown"
            for line in text.splitlines():
                if "**Статус:**" in line:
                    status_line = line.split("**Статус:**")[-1].strip()
                    break
            print(f"  {t.stem}: {status_line}")
    else:
        print("No tasks found.")
    reviews = sorted(REVIEWS_DIR.glob("REVIEW-*.md"))
    if reviews:
        print("Reviews:")
        for r in reviews:
            print(f"  {r.stem}")


def _task_status(task_file):
    """Read status from task file."""
    text = task_file.read_text(encoding="utf-8")
    for line in text.splitlines():
        if "**Статус:**" in line:
            return line.split("**Статус:**")[-1].strip().lower()
    return "unknown"


def get_todo_tasks():
    """Return task files with status 'todo' only."""
    result = []
    for t in sorted(TASKS_DIR.glob("TASK-*.md")):
        if _task_status(t) == "todo":
            result.append(t)
    return result


def get_changes_requested_tasks():
    """Return task files with status 'changes-requested'."""
    result = []
    for t in sorted(TASKS_DIR.glob("TASK-*.md")):
        if _task_status(t) == "changes-requested":
            result.append(t)
    return result


def get_task_description(task_file):
    text = task_file.read_text(encoding="utf-8")
    lines = text.splitlines()
    desc_lines = []
    in_desc = False
    for line in lines:
        if line.startswith("## Описание"):
            in_desc = True
            continue
        if in_desc and line.startswith("## "):
            break
        if in_desc:
            desc_lines.append(line)
    desc = "\n".join(desc_lines).strip()
    if not desc or desc.startswith("_"):
        for line in lines:
            if line.startswith("# TASK-"):
                desc = line.replace("# ", "")
                break
    return desc


def set_task_status(task_file, new_status):
    text = task_file.read_text(encoding="utf-8")
    lines = text.splitlines()
    new_lines = []
    for line in lines:
        if "**Статус:**" in line:
            new_lines.append(line.split("**Статус:**")[0] + "**Статус:** " + new_status)
        else:
            new_lines.append(line)
    task_file.write_text("\n".join(new_lines) + "\n", encoding="utf-8")


def set_task_result(task_file, result_text):
    text = task_file.read_text(encoding="utf-8")
    marker = "## Результат (заполняет исполнитель)"
    if marker in text:
        idx = text.index(marker) + len(marker)
        next_section = text.find("\n## ", idx)
        if next_section == -1:
            next_section = len(text)
        new_text = text[:idx] + "\n\n" + result_text + "\n" + text[next_section:]
        task_file.write_text(new_text, encoding="utf-8")


def has_valid_report(task_file):
    """Check if the task file's result section was filled in (not just placeholder)."""
    if not task_file.exists():
        return False
    text = task_file.read_text(encoding="utf-8")
    marker = "## Результат (заполняет исполнитель)"
    if marker not in text:
        return False
    idx = text.index(marker) + len(marker)
    next_section = text.find("\n## ", idx)
    if next_section == -1:
        next_section = len(text)
    result_text = text[idx:next_section].strip()
    # Check it's not just the placeholder
    placeholder = "_Что было сделано. Какие файлы изменены. Какие тесты добавлены._"
    if not result_text or result_text == placeholder:
        return False
    return True


def run_opencode(task_description, task_id):
    import time as _time
    log(f"Running OpenCode for {task_id}: {task_description[:80]}...")
    start_time = _time.time()
    task_file = TASKS_DIR / f"{task_id}.md"
    mtime_before = task_file.stat().st_mtime if task_file.exists() else 0
    # Narrow context: only the specific task, avoid full project analysis
    prompt = (
        f"Task {task_id}: {task_description}. "
        f"Scope: only files directly related to this task. "
        f"Do not analyze the entire project. "
        f"Implement, run 'python -m pytest -q' (Windows: no tail/grep), write result to .agent/tasks/{task_id}.md. "
        f"Do not commit or push."
    )
    try:
        result = subprocess.run(
            ["opencode.cmd", "run", prompt, "--auto"],
            capture_output=True, text=True, timeout=1800,
            cwd=str(ROOT),
            env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
        )
        elapsed = _time.time() - start_time
        output = result.stdout + result.stderr
        # Only exit code 0 is success. Non-zero (including -1) is failure.
        # Preserve output and report for diagnostics, but do not mask errors.
        success = (result.returncode == 0)
        log(f"OpenCode finished for {task_id}, exit code: {result.returncode}, elapsed: {elapsed:.1f}s")
        log(f"OpenCode stdout ({len(result.stdout)} bytes): {result.stdout[:300]}")
        log(f"OpenCode stderr ({len(result.stderr)} bytes): {result.stderr[:300]}")
        return success, output
    except subprocess.TimeoutExpired:
        elapsed = _time.time() - start_time
        log(f"OpenCode TIMED OUT for {task_id} after {elapsed:.1f}s")
        return False, "Timeout after %.1fs" % elapsed
    except Exception as e:
        elapsed = _time.time() - start_time
        log(f"OpenCode error for {task_id} after {elapsed:.1f}s: {e}")
        return False, str(e)


def cmd_run():
    """Run OpenCode on todo tasks only (not changes-requested)."""
    if not acquire_lock():
        print("Cannot acquire lock. Another process may be running.")
        return
    try:
        tasks = get_todo_tasks()
        if not tasks:
            print("No pending tasks (status: todo).")
            return
        for task_file in tasks:
            task_id = task_file.stem
            desc = get_task_description(task_file)
            log(f"Processing {task_id}")
            set_task_status(task_file, "in-progress")
            st = load_status()
            st["status"] = "in-progress"
            st["current_task"] = task_id
            st["assigned_to"] = "opencode"
            save_status(st)

            success, output = run_opencode(desc, task_id)

            # Verify report was written even on success
            report_ok = has_valid_report(task_file)
            if success and not report_ok:
                log(f"{task_id}: OpenCode exited 0 but no valid report written")
                print(f"Warning: OpenCode exited 0 but did not write a valid report.")

            if success and report_ok:
                set_task_status(task_file, "review")
                st = load_status()
                st["status"] = "review"
                st["last_action"] = f"opencode: implemented {task_id}"
                save_status(st)
                result_summary = f"OpenCode completed implementation.\n\nExit: success\n\nOutput (truncated):\n```\n{output[:2000]}\n```"
                set_task_result(task_file, result_summary)
                log(f"{task_id} -> review (ready for Copilot review)")
                print(f"\n{task_id} -> review (ready for Copilot review)")
                print(f"Next: trigger Copilot review, then run: python tools/agent.py fix")
            else:
                set_task_status(task_file, "blocked")
                st = load_status()
                st["status"] = "blocked"
                st["last_action"] = f"opencode: failed {task_id}"
                save_status(st)
                # Preserve output and report for diagnostics
                log(f"{task_id} blocked. Output: {output[:1000]}")
                print(f"\n{task_id} -> blocked")
                print(f"Output (first 500 chars): {output[:500]}")
                if has_valid_report(task_file):
                    print("Note: a partial report was written to the task file.")
    finally:
        release_lock()


def review_verdict(review_text):
    """Extract verdict from review text. Returns APPROVED, CHANGES_REQUESTED, BLOCKED, or None."""
    for line in review_text.splitlines():
        if "APPROVED" in line.upper() and "CHANGES" not in line.upper():
            return "APPROVED"
        if "CHANGES_REQUESTED" in line.upper() or "CHANGES REQUESTED" in line.upper():
            return "CHANGES_REQUESTED"
        if "BLOCKED" in line.upper():
            return "BLOCKED"
    return None


def cmd_fix():
    """Apply fixes from reviews with CHANGES_REQUESTED verdict."""
    if not acquire_lock():
        print("Cannot acquire lock.")
        return
    try:
        tasks = get_changes_requested_tasks()
        if not tasks:
            print("No tasks with changes-requested status.")
            return

        for task_file in tasks:
            task_id = task_file.stem
            review_file = REVIEWS_DIR / f"REVIEW-{task_id.split('-')[1]}.md"
            if not review_file.exists():
                review_file = REVIEWS_DIR / f"REVIEW-{task_id}.md"
            if not review_file.exists():
                print(f"No review file found for {task_id}. Skipping.")
                continue

            review_text = review_file.read_text(encoding="utf-8")
            verdict = review_verdict(review_text)
            if verdict is None:
                print(f"Review for {task_id} has no clear verdict. Skipping (not applying stale report).")
                continue
            if verdict == "APPROVED":
                print(f"Review for {task_id} is APPROVED. Use 'done {task_id}' to mark complete.")
                continue
            if verdict == "BLOCKED":
                print(f"Review for {task_id} is BLOCKED. Skipping.")
                continue
            # verdict == CHANGES_REQUESTED

            # Check staleness: review must be newer than task file
            if review_file.stat().st_mtime < task_file.stat().st_mtime:
                print(f"Review for {task_id} is older than task file. Skipping (stale report).")
                continue

            # Extract findings
            findings = []
            in_findings = False
            for line in review_text.splitlines():
                if "Критические" in line or "Предупреждения" in line or "Critical" in line or "Warning" in line:
                    in_findings = True
                    continue
                if in_findings and (line.startswith("### ") or line.startswith("## ")):
                    in_findings = False
                    continue
                if in_findings and line.strip().startswith("- [ ]"):
                    findings.append(line.strip())

            if not findings:
                print(f"No findings in review for {task_id}. Skipping.")
                continue

            log(f"Applying fixes for {task_id}: {len(findings)} findings")
            set_task_status(task_file, "in-progress")
            st = load_status()
            st["status"] = "in-progress"
            st["current_task"] = task_id
            st["assigned_to"] = "opencode"
            save_status(st)

            desc = get_task_description(task_file)
            fix_prompt = (
                f"Task {task_id}: {desc}. "
                f"Review findings to fix:\n" + "\n".join(findings) + "\n"
                f"Fix all issues, run tests (python -m pytest -q), update task file."
            )
            success, output = run_opencode(fix_prompt, task_id)

            if success:
                set_task_status(task_file, "review")
                st = load_status()
                st["status"] = "review"
                st["last_action"] = f"opencode: fixed {task_id}"
                save_status(st)
                print(f"{task_id} -> review (fixed, ready for re-review)")
            else:
                set_task_status(task_file, "blocked")
                st = load_status()
                st["status"] = "blocked"
                save_status(st)
                print(f"{task_id} -> blocked")
    finally:
        release_lock()


def cmd_done(task_id):
    """Mark task as done only if review is APPROVED."""
    task_file = TASKS_DIR / f"{task_id}.md"
    if not task_file.exists():
        print(f"Task {task_id} not found.")
        return
    review_file = REVIEWS_DIR / f"REVIEW-{task_id.split('-')[1]}.md"
    if not review_file.exists():
        review_file = REVIEWS_DIR / f"REVIEW-{task_id}.md"
    if not review_file.exists():
        print(f"No review found for {task_id}. Cannot mark done without review.")
        return
    review_text = review_file.read_text(encoding="utf-8")
    verdict = review_verdict(review_text)
    if verdict != "APPROVED":
        print(f"Review verdict is {verdict}, not APPROVED. Cannot mark done.")
        return
    set_task_status(task_file, "done")
    st = load_status()
    st["status"] = "done"
    st["current_task"] = task_id
    st["assigned_to"] = None
    st["last_action"] = f"task {task_id} completed and approved"
    save_status(st)
    log(f"{task_id} marked as done (approved)")
    print(f"{task_id} -> done (approved by review)")


def wait_for_review(task_id, max_polls=MAX_REVIEW_WAIT, interval=REVIEW_POLL_INTERVAL):
    """Wait for Copilot review file to appear. Returns review file path or None."""
    review_file = REVIEWS_DIR / f"REVIEW-{task_id.split('-')[1]}.md"
    if not review_file.exists():
        review_file = REVIEWS_DIR / f"REVIEW-{task_id}.md"
    for attempt in range(max_polls):
        if review_file.exists():
            return review_file
        log(f"Waiting for review of {task_id} (attempt {attempt+1}/{max_polls})")
        print(f"Waiting for Copilot review... ({attempt+1}/{max_polls})")
        time.sleep(interval)
    return None


def cmd_cycle():
    """Full cycle: run -> wait for review -> fix. Repeats up to MAX_RETRIES."""
    retries = 0
    while retries < MAX_RETRIES:
        tasks = get_todo_tasks()
        if not tasks:
            # check if there are changes-requested tasks
            cr_tasks = get_changes_requested_tasks()
            if not cr_tasks:
                print("No pending tasks. Create one with: python tools/agent.py task \"description\"")
                return
            # fix existing
            cmd_fix()
            retries += 1
            status = load_status()
            if status.get("status") == "done":
                print("Task completed!")
                return
            continue

        cmd_run()
        status = load_status()
        if status.get("status") != "review":
            print("No tasks in review. Stopping.")
            return

        print("\n=== Waiting for Copilot review ===")
        task_id = status.get("current_task")
        review_file = wait_for_review(task_id)
        if review_file is None:
            print(f"No review received for {task_id} after {MAX_REVIEW_WAIT} attempts. Stopping.")
            return

        # Check verdict
        review_text = review_file.read_text(encoding="utf-8")
        verdict = review_verdict(review_text)
        if verdict == "APPROVED":
            cmd_done(task_id)
            print("Task completed!")
            return
        if verdict == "BLOCKED":
            print(f"Review blocked for {task_id}. Stopping.")
            return
        # CHANGES_REQUESTED -> fix
        cmd_fix()
        retries += 1
        status = load_status()
        if status.get("status") == "done":
            print("Task completed!")
            return
    print(f"Max retries ({MAX_RETRIES}) reached.")


def cmd_lock():
    if acquire_lock():
        print("Lock acquired.")
    else:
        print("Lock already held.")

def cmd_unlock():
    release_lock()
    print("Lock released.")

def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return
    cmd = sys.argv[1]
    if cmd == "task":
        if len(sys.argv) < 3:
            print("Usage: python tools/agent.py task \"description\"")
            return
        cmd_task(" ".join(sys.argv[2:]))
    elif cmd == "status":
        cmd_status()
    elif cmd == "run":
        cmd_run()
    elif cmd == "fix":
        cmd_fix()
    elif cmd == "done":
        if len(sys.argv) < 3:
            print("Usage: python tools/agent.py done TASK-XXX")
            return
        cmd_done(sys.argv[2])
    elif cmd == "cycle":
        cmd_cycle()
    elif cmd == "lock":
        cmd_lock()
    elif cmd == "unlock":
        cmd_unlock()
    else:
        print(f"Unknown command: {cmd}")
        print(__doc__)

if __name__ == "__main__":
    main()