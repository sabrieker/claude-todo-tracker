"""Shared settings. Every value can be changed with an environment variable
(set it in the "env" block of ~/.claude/settings.json so hooks see it too).

  TODO_HOME        folder for your data              default ~/todo
  TODO_AUTO_SYNC   0 turns off the background sync   default 1
  TODO_SYNC_MODEL  model for the sync worker         default claude-sonnet-5
  TODO_GIT_AUTHOR  git --author filter for /daily    default: git config user.email
"""
import contextlib, os, re, subprocess, sys, time

# UTF-8 everywhere, also on Windows (cp1252 consoles and files).
os.environ.setdefault("PYTHONUTF8", "1")            # child Python processes
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
WINDOWS = os.name == "nt"

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


def native_path(p):
    """Git Bash on Windows gives /c/Users/x. Python needs C:\\Users\\x."""
    if WINDOWS and p:
        m = re.match(r"^/([a-zA-Z])(/.*)?$", p)
        if m:
            p = m.group(1).upper() + ":" + (m.group(2) or "/")
        p = os.path.normpath(p)
    return p


def same_or_inside(path, root):
    path = os.path.normcase(os.path.realpath(native_path(path)))
    root = os.path.normcase(os.path.realpath(os.path.expanduser(native_path(root))))
    return path == root or path.startswith(root.rstrip(os.sep) + os.sep)


@contextlib.contextmanager
def locked(path, blocking=True):
    """Exclusive lock on a file, on Unix and Windows. Raises BlockingIOError when
    blocking=False and another process holds it."""
    f = open(path, "a+")
    try:
        if WINDOWS:
            import msvcrt
            while True:
                try:
                    f.seek(0)
                    msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except OSError:
                    if not blocking:
                        raise BlockingIOError(path)
                    time.sleep(0.1)
        else:
            import fcntl
            fcntl.flock(f, fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
        yield f
    finally:
        if WINDOWS:
            try:
                import msvcrt
                f.seek(0)
                msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
            except OSError:
                pass
        f.close()


def python_cmd(script, *args):
    return [sys.executable, "-X", "utf8", os.path.join(SCRIPTS, script)] + list(args)


def spawn_detached(cmd, log_path):
    """Start a background process that outlives the hook and never blocks it."""
    log = open(log_path, "a", encoding="utf-8")
    kw = {"creationflags": 0x00000008 | 0x00000200} if WINDOWS else {"start_new_session": True}
    subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=log, stderr=log, close_fds=True, **kw)


def claude_bin():
    from shutil import which
    return which("claude") or "claude"


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
