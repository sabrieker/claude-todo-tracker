#!/usr/bin/env python3
"""SessionStart hook: load the open TODO items linked to this folder, with their IDs."""
import json, os, subprocess, sys

if os.environ.get("TODO_SYNC"):
    sys.exit(0)
HERE = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, HERE)
import config as C
TODO_PY = os.path.join(HERE, "todo.py")
try:
    cwd = json.load(sys.stdin).get("cwd") or os.getcwd()
except Exception:
    cwd = os.getcwd()
r = subprocess.run([sys.executable, TODO_PY, "show", "--cwd", cwd], capture_output=True, text=True)
if r.returncode:
    sys.exit(0)
t = C.todo_cmd()
print("TODO list (open items for this folder; other sections by title). IDs: sN section, tN item.")
print(f"Change it only with the todo command `{t}`, never by editing TODO.md/TODO.json:")
print(f'  {t} done tN [--note "..."] | add sN|tN "text" | note sN|tN "text" | edit ID "text"')
print(f'  {t} move sN Active|Backlog|Blocked [--waits "..."] | new GROUP "title" | show --all')
if C.AUTO_SYNC:
    print("The TODO list is updated from this session automatically (in the background). /todo forces an update now.")
print()
print(r.stdout.strip() or "The TODO list is empty.")
