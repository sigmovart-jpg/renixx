"""Unit tests for the Renixx agent orchestrator (tools/agent.py)."""
import json
import os
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import agent


@pytest.fixture
def agent_env(tmp_path, monkeypatch):
    """Set up a temporary .agent/ directory structure and configure agent module."""
    agent_dir = tmp_path / ".agent"
    (agent_dir / "tasks").mkdir(parents=True)
    (agent_dir / "reviews").mkdir(parents=True)
    (agent_dir / "templates").mkdir(parents=True)

    real_root = Path(__file__).resolve().parent.parent
    templates_src = real_root / ".agent" / "templates"
    for f in templates_src.glob("*.md"):
        (agent_dir / "templates" / f.name).write_text(f.read_text(encoding="utf-8"), encoding="utf-8")

    (agent_dir / "status.json").write_text(
        json.dumps({"version": 1, "status": "idle", "current_task": None,
                    "assigned_to": None, "branch": None, "last_updated": None,
                    "last_action": None, "notes": ""}, indent=2),
        encoding="utf-8",
    )
    (agent_dir / "handoff.md").write_text("# Handoff\n", encoding="utf-8")
    (agent_dir / "decisions.md").write_text("# Decisions\n", encoding="utf-8")

    agent.configure(tmp_path)
    monkeypatch.setattr(agent, "run_opencode", lambda desc, tid: (True, "mock output"))
    return tmp_path


def make_task(env, task_id, status="todo", name="Test task"):
    template = (env / ".agent" / "templates" / "TASK-TEMPLATE.md").read_text(encoding="utf-8")
    content = template.replace("TASK-XXX", task_id).replace("Краткое название задачи", name)
    content = content.replace("**Статус:** idle | todo | in-progress | review | changes-requested | done | blocked",
                             "**Статус:** " + status)
    (env / ".agent" / "tasks" / (task_id + ".md")).write_text(content, encoding="utf-8")
    return env / ".agent" / "tasks" / (task_id + ".md")


def make_review(env, task_id, verdict="CHANGES_REQUESTED", findings=None):
    if findings is None:
        findings = ["- [ ] **Файл:** src/foo.py:10 — bug"]
    num = task_id.split("-")[1]
    content = "# REVIEW\n\n## Найденные проблемы\n\n### Критические\n" + "\n".join(findings) + "\n\n## Вердикт\n" + verdict + "\n"
    (env / ".agent" / "reviews" / ("REVIEW-" + num + ".md")).write_text(content, encoding="utf-8")


# ---------- review_verdict ----------

def test_review_verdict_approved():
    assert agent.review_verdict("## Вердикт\nAPPROVED") == "APPROVED"

def test_review_verdict_changes_requested():
    assert agent.review_verdict("## Вердикт\nCHANGES_REQUESTED") == "CHANGES_REQUESTED"

def test_review_verdict_blocked():
    assert agent.review_verdict("## Вердикт\nBLOCKED") == "BLOCKED"

def test_review_verdict_none():
    assert agent.review_verdict("no verdict here") is None

def test_review_verdict_unknown():
    assert agent.review_verdict("maybe ok") is None

def test_review_verdict_changes_requested_with_spaces():
    assert agent.review_verdict("CHANGES REQUESTED") == "CHANGES_REQUESTED"


# ---------- next_task_id ----------

def test_next_task_id_empty(agent_env):
    assert agent.next_task_id() == "TASK-001"

def test_next_task_id_existing(agent_env):
    make_task(agent_env, "TASK-001")
    make_task(agent_env, "TASK-003")
    assert agent.next_task_id() == "TASK-004"

def test_next_task_id_single(agent_env):
    make_task(agent_env, "TASK-005")
    assert agent.next_task_id() == "TASK-006"


# ---------- get_todo_tasks / get_changes_requested_tasks ----------

def test_get_todo_tasks(agent_env):
    make_task(agent_env, "TASK-001", status="todo")
    make_task(agent_env, "TASK-002", status="review")
    make_task(agent_env, "TASK-003", status="changes-requested")
    todos = agent.get_todo_tasks()
    assert len(todos) == 1
    assert todos[0].name == "TASK-001.md"

def test_get_changes_requested_tasks(agent_env):
    make_task(agent_env, "TASK-001", status="todo")
    make_task(agent_env, "TASK-002", status="changes-requested")
    cr = agent.get_changes_requested_tasks()
    assert len(cr) == 1
    assert cr[0].name == "TASK-002.md"

def test_no_overlap(agent_env):
    make_task(agent_env, "TASK-001", status="todo")
    make_task(agent_env, "TASK-002", status="changes-requested")
    todos = agent.get_todo_tasks()
    cr = agent.get_changes_requested_tasks()
    todo_ids = {t.name for t in todos}
    cr_ids = {t.name for t in cr}
    assert todo_ids.isdisjoint(cr_ids)


# ---------- cmd_fix: protection ----------

def test_cmd_fix_no_review_file(agent_env, capsys):
    make_task(agent_env, "TASK-001", status="changes-requested")
    agent.cmd_fix()
    out = capsys.readouterr().out
    assert "No review file found" in out

def test_cmd_fix_approved_skips(agent_env, capsys):
    make_task(agent_env, "TASK-001", status="changes-requested")
    make_review(agent_env, "TASK-001", verdict="APPROVED")
    agent.cmd_fix()
    out = capsys.readouterr().out
    assert "APPROVED" in out
    assert agent._task_status(agent.TASKS_DIR / "TASK-001.md") == "changes-requested"

def test_cmd_fix_blocked_skips(agent_env, capsys):
    make_task(agent_env, "TASK-001", status="changes-requested")
    make_review(agent_env, "TASK-001", verdict="BLOCKED")
    agent.cmd_fix()
    out = capsys.readouterr().out
    assert "BLOCKED" in out

def test_cmd_fix_no_verdict_skips(agent_env, capsys):
    make_task(agent_env, "TASK-001", status="changes-requested")
    (agent_env / ".agent" / "reviews" / "REVIEW-001.md").write_text("# Review\nNo verdict\n", encoding="utf-8")
    agent.cmd_fix()
    out = capsys.readouterr().out
    assert "no clear verdict" in out

def test_cmd_fix_no_findings_skips(agent_env, capsys):
    make_task(agent_env, "TASK-001", status="changes-requested")
    (agent_env / ".agent" / "reviews" / "REVIEW-001.md").write_text(
        "# Review\n## Вердикт\nCHANGES_REQUESTED\n", encoding="utf-8")
    agent.cmd_fix()
    out = capsys.readouterr().out
    assert "No findings" in out

def test_cmd_fix_stale_report_skips(agent_env, capsys):
    make_task(agent_env, "TASK-001", status="changes-requested")
    make_review(agent_env, "TASK-001", verdict="CHANGES_REQUESTED")
    review_path = agent_env / ".agent" / "reviews" / "REVIEW-001.md"
    task_path = agent_env / ".agent" / "tasks" / "TASK-001.md"
    import time
    time.sleep(0.05)
    task_path.write_text(task_path.read_text(encoding="utf-8"), encoding="utf-8")
    agent.cmd_fix()
    out = capsys.readouterr().out
    assert "stale" in out.lower() or "older" in out.lower()


# ---------- cmd_done ----------

def test_cmd_done_requires_approved(agent_env, capsys):
    make_task(agent_env, "TASK-001", status="review")
    make_review(agent_env, "TASK-001", verdict="CHANGES_REQUESTED")
    agent.cmd_done("TASK-001")
    out = capsys.readouterr().out
    assert "not APPROVED" in out
    assert agent._task_status(agent.TASKS_DIR / "TASK-001.md") == "review"

def test_cmd_done_approved(agent_env, capsys):
    make_task(agent_env, "TASK-001", status="review")
    make_review(agent_env, "TASK-001", verdict="APPROVED")
    agent.cmd_done("TASK-001")
    out = capsys.readouterr().out
    assert "done" in out.lower()
    assert agent._task_status(agent.TASKS_DIR / "TASK-001.md") == "done"
    st = agent.load_status()
    assert st["status"] == "done"

def test_cmd_done_no_review(agent_env, capsys):
    make_task(agent_env, "TASK-001", status="review")
    agent.cmd_done("TASK-001")
    out = capsys.readouterr().out
    assert "No review found" in out

def test_cmd_done_missing_task(agent_env, capsys):
    agent.cmd_done("TASK-999")
    out = capsys.readouterr().out
    assert "not found" in out


# ---------- wait_for_review ----------

def test_wait_for_review_timeout(agent_env, monkeypatch):
    monkeypatch.setattr(agent.time, "sleep", lambda x: None)
    monkeypatch.setattr(agent, "MAX_REVIEW_WAIT", 3)
    result = agent.wait_for_review("TASK-999")
    assert result is None

def test_wait_for_review_found(agent_env, monkeypatch):
    monkeypatch.setattr(agent.time, "sleep", lambda x: None)
    make_review(agent_env, "TASK-001", verdict="APPROVED")
    result = agent.wait_for_review("TASK-001")
    assert result is not None
    assert result.exists()


# ---------- cmd_run protection ----------

def test_cmd_run_no_tasks(agent_env, capsys):
    agent.cmd_run()
    out = capsys.readouterr().out
    assert "No pending tasks" in out

def test_cmd_run_skips_changes_requested(agent_env, capsys, monkeypatch):
    make_task(agent_env, "TASK-001", status="changes-requested")
    calls = []
    monkeypatch.setattr(agent, "run_opencode", lambda desc, tid: (calls.append(tid) or True, "mock"))
    agent.cmd_run()
    out = capsys.readouterr().out
    assert "No pending tasks" in out
    assert calls == [], "cmd_run should not process changes-requested tasks"


# ---------- lock ----------

def test_lock_acquire_release(agent_env):
    assert agent.acquire_lock() is True
    assert agent.acquire_lock() is False
    agent.release_lock()
    assert agent.acquire_lock() is True
    agent.release_lock()

def test_lock_file_contains_pid(agent_env):
    agent.acquire_lock()
    content = (agent_env / ".agent" / ".lock").read_text()
    assert "pid=" in content
    agent.release_lock()


# ---------- run_opencode completion semantics ----------

def test_run_opencode_success_with_report(agent_env, monkeypatch):
    make_task(agent_env, "TASK-001", status="todo")
    task_path = agent_env / ".agent" / "tasks" / "TASK-001.md"
    text = task_path.read_text(encoding="utf-8")
    text = text.replace("_Что было сделано. Какие файлы изменены. Какие тесты добавлены._",
                        "Implemented feature X. Changed foo.py. Added 2 tests.")
    task_path.write_text(text, encoding="utf-8")
    monkeypatch.setattr(agent, "run_opencode", lambda desc, tid: (True, "ok"))
    agent.cmd_run()
    assert agent._task_status(task_path) == "review"


def test_run_opencode_exit_minus_one_with_report(agent_env, monkeypatch):
    make_task(agent_env, "TASK-001", status="todo")
    task_path = agent_env / ".agent" / "tasks" / "TASK-001.md"
    text = task_path.read_text(encoding="utf-8")
    text = text.replace("_Что было сделано. Какие файлы изменены. Какие тесты добавлены._",
                        "Partial result written before crash.")
    task_path.write_text(text, encoding="utf-8")
    monkeypatch.setattr(agent, "run_opencode", lambda desc, tid: (False, "crashed"))
    agent.cmd_run()
    assert agent._task_status(task_path) == "blocked"
    assert "Partial result written before crash." in task_path.read_text(encoding="utf-8")


def test_run_opencode_exit_minus_one_no_report(agent_env, monkeypatch):
    make_task(agent_env, "TASK-001", status="todo")
    task_path = agent_env / ".agent" / "tasks" / "TASK-001.md"
    monkeypatch.setattr(agent, "run_opencode", lambda desc, tid: (False, "crashed"))
    agent.cmd_run()
    assert agent._task_status(task_path) == "blocked"


def test_run_opencode_timeout_preserves_partial(agent_env, monkeypatch):
    make_task(agent_env, "TASK-001", status="todo")
    task_path = agent_env / ".agent" / "tasks" / "TASK-001.md"
    text = task_path.read_text(encoding="utf-8")
    text = text.replace("_Что было сделано. Какие файлы изменены. Какие тесты добавлены._",
                        "Partial work done before timeout.")
    task_path.write_text(text, encoding="utf-8")
    monkeypatch.setattr(agent, "run_opencode", lambda desc, tid: (False, "Timeout after 100.0s"))
    agent.cmd_run()
    assert agent._task_status(task_path) == "blocked"
    assert "Partial work done before timeout." in task_path.read_text(encoding="utf-8")


def test_has_valid_report_true(agent_env):
    make_task(agent_env, "TASK-001", status="todo")
    task_path = agent_env / ".agent" / "tasks" / "TASK-001.md"
    text = task_path.read_text(encoding="utf-8")
    text = text.replace("_Что было сделано. Какие файлы изменены. Какие тесты добавлены._",
                        "Real result here.")
    task_path.write_text(text, encoding="utf-8")
    assert agent.has_valid_report(task_path) is True


def test_has_valid_report_false_placeholder(agent_env):
    make_task(agent_env, "TASK-001", status="todo")
    task_path = agent_env / ".agent" / "tasks" / "TASK-001.md"
    assert agent.has_valid_report(task_path) is False


def test_has_valid_report_false_missing_file(agent_env):
    assert agent.has_valid_report(agent_env / ".agent" / "tasks" / "NONEXISTENT.md") is False
