"""Shared settings. Every value can be changed with an environment variable
(set it in the "env" block of ~/.claude/settings.json so hooks see it too).

  TODO_HOME        folder for your data              default ~/todo
  TODO_AUTO_SYNC   0 turns off the background sync   default 1
  TODO_SYNC_MODEL  model for the sync worker         default claude-sonnet-5
  TODO_GIT_AUTHOR  git --author filter for /daily    default: git config user.email
"""
import os, subprocess

HOME = os.path.expanduser(os.environ.get("TODO_HOME") or "~/todo")
DATA = os.path.join(HOME, "TODO.json")         # source of truth
MD = os.path.join(HOME, "TODO.md")             # generated view; hand edits are imported
HTML = os.path.join(HOME, "TODO.html")         # Kanban board
DONE = os.path.join(HOME, "TODO-done.md")      # archive of done items
DAILY = os.path.join(HOME, "daily")            # /daily reports and /today plans
STATE = os.path.join(HOME, ".state")           # locks, snapshots, logs
HISTORY = os.path.join(STATE, "history")       # one TODO.md snapshot per day
SYNC_DIR = os.path.join(STATE, "sync")         # undo snapshots of the sync worker
SCRIPTS = os.path.dirname(os.path.realpath(__file__))

AUTO_SYNC = os.environ.get("TODO_AUTO_SYNC", "1") != "0"
SYNC_MODEL = os.environ.get("TODO_SYNC_MODEL") or "claude-sonnet-5"


def todo_cmd():
    """How Claude should call the todo tool: `todo` if it is on PATH, else the full path."""
    from shutil import which
    w = which("todo")
    mine = {os.path.join(SCRIPTS, "todo.py"), os.path.realpath(os.path.join(SCRIPTS, "..", "bin", "todo"))}
    if w and os.path.realpath(w) in mine:
        return "todo"
    if os.environ.get("CLAUDE_PLUGIN_ROOT") and not w:
        return "todo"          # the plugin's bin/ is on PATH in the Bash tool, not in hooks
    return f'python3 "{os.path.join(SCRIPTS, "todo.py")}"'


def git_author():
    a = os.environ.get("TODO_GIT_AUTHOR")
    if a:
        return a
    try:
        return subprocess.run(["git", "config", "--global", "user.email"],
                              capture_output=True, text=True, timeout=5).stdout.strip()
    except Exception:
        return ""


def ensure_dirs():
    for d in (HOME, STATE, HISTORY, SYNC_DIR):
        os.makedirs(d, exist_ok=True)
