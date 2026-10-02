---
name: todo
description: Update the TODO list now from this session's work (the list also updates by itself in the background). Use when the user runs /todo.
disable-model-invocation: true
argument-hint: "[show | undo]"
---

`/todo` is a side task. It must not change the focus of this session.

The TODO list updates by itself: a background worker reads this session's transcript and runs `todo` commands. `/todo` only forces that worker to run now.

If `$ARGUMENTS` is `show`, run `todo show --cwd "$PWD"`, show the open items as a short list, and stop.
If `$ARGUMENTS` is `undo`, run `todo undo "$CLAUDE_CODE_SESSION_ID"`, relay the result, and stop.

Otherwise:
1. Run this with the Bash tool, with `run_in_background: true`:
   `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/todo-sync.py" --current --now`
2. Reply with one line: `TODO sync is running in the background.` Then continue the task that was in progress before `/todo`. If nothing was in progress, stop.
3. When the command finishes, relay its output in one short message (the summary line and one line per change). Then continue the earlier task. Do not start new work because of the TODO content.
