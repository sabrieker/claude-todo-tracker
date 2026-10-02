#!/usr/bin/env python3
"""UserPromptSubmit hook: follow sessions that stay open for days.

On every prompt it records the session's last activity in TODO.json (`todo ping`).
When the user comes back after a break (new day, or idle > IDLE_HOURS):
  - tells the user (systemMessage) and syncs the earlier work to the TODO list (todo-sync.py);
  - gives Claude the current open TODO items for this folder, because other
    sessions may have changed them in the meantime.
Never blocks the prompt.
"""
import json, os, subprocess, sys
from datetime import datetime

HERE = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, HERE)
import config as C
TODO_PY = os.path.join(HERE, "todo.py")
IDLE_HOURS = 6


def main():
    try:
        ev = json.load(sys.stdin)
    except Exception:
        return
    sid, cwd = ev.get("session_id"), ev.get("cwd") or os.getcwd()
    if not sid or os.environ.get("TODO_SYNC"):
        return
    prompt = (ev.get("prompt") or "").strip()
    is_todo = prompt.startswith("/todo")
    args = [sys.executable, TODO_PY, "ping", "--session", sid, "--cwd", cwd] + (["--is-todo"] if is_todo else []) \
        + (["--transcript", ev["transcript_path"]] if ev.get("transcript_path") else [])
    r = subprocess.run(args, capture_output=True, text=True, timeout=10)
    try:
        before = json.loads(r.stdout.strip().splitlines()[-1])
    except Exception:
        return
    if not before.get("last_prompt") or is_todo:
        return
    now = datetime.now()
    prev = datetime.fromisoformat(before["last_prompt"])
    last_todo = datetime.fromisoformat(before["last_todo"]) if before.get("last_todo") else None
    gap_h = (now - prev).total_seconds() / 3600
    if prev.date() == now.date() and gap_h < IDLE_HOURS:
        return

    msg = f"Session resumed. Last prompt here: {prev:%a %d %b %H:%M} ({gap_h:.0f} h ago)."
    if C.AUTO_SYNC and (last_todo is None or last_todo < prev):
        # record the work before the break, in the background
        log = open(os.path.join(C.STATE, "sync-worker.out"), "a")
        subprocess.Popen([sys.executable, os.path.join(HERE, "todo-sync.py"), sid, "--now"],
                         stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True)
        msg += " The TODO list is being updated from the earlier work in the background."
    r = subprocess.run([sys.executable, TODO_PY, "show", "--cwd", cwd], capture_output=True, text=True, timeout=10)
    ctx = (f"Background only: the user returns to this session after {gap_h:.0f} hours. "
           "Other sessions may have changed the TODO list. Current open items for this folder "
           "(do not act on them unless the user asks; answer the user's prompt):\n" + r.stdout.strip())
    print(json.dumps({"systemMessage": msg,
                      "hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": ctx}}))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
