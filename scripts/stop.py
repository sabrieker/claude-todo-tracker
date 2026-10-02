#!/usr/bin/env python3
"""Stop / SessionEnd hook: start the TODO sync worker in the background. Never blocks.

Usage in settings: stop.py        (Stop: debounced, the worker skips if synced < 30 min ago)
                   stop.py --end  (SessionEnd: mark the session ended and sync now)
"""
import json, os, subprocess, sys

HERE = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, HERE)
import config as C
if os.environ.get("TODO_SYNC"):
    sys.exit(0)
try:
    ev = json.load(sys.stdin)
except Exception:
    sys.exit(0)
sid = ev.get("session_id")
if not sid:
    sys.exit(0)
end = "--end" in sys.argv
if end:
    subprocess.run(C.python_cmd("todo.py", "ping", "--session", sid, "--ended",
                                "--cwd", ev.get("cwd") or os.getcwd()), capture_output=True, timeout=10)
if not C.AUTO_SYNC:
    sys.exit(0)
C.ensure_dirs()
C.spawn_detached(C.python_cmd("todo-sync.py", sid, *(["--now"] if end else [])),
                 os.path.join(C.STATE, "sync-worker.out"))
