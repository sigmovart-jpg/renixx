---
name: review-task
description: Review a Renixx task implementation. Use when asked to review a task.
---

# Review Renixx Task

You are reviewing a task implementation in the Renixx project.

## Steps

1. Read `.agent/status.json` to find the current task ID.
2. Read `.agent/tasks/{task_id}.md` for the task description and acceptance criteria.
3. Run `git diff` to see all changes.
4. Run `python -m pytest -q` to check tests.
5. Analyze the code for bugs, style issues, and missing tests.
6. Write your review to `.agent/reviews/REVIEW-{task_number}.md` using the template.
7. Update `.agent/status.json` with the verdict (review or changes-requested).
8. Update `.agent/handoff.md` with findings.

## Output Format

Use the REVIEW-TEMPLATE.md format. Include:
- Critical issues (block acceptance)
- Warnings (should fix)
- Suggestions (nice to have)
- Test results
- Verdict: APPROVED / CHANGES_REQUESTED / BLOCKED

Be specific with file paths and line numbers. Do not modify source code.