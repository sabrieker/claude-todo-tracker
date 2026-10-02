#!/usr/bin/env python3
"""Sync worker: update the TODO list from what a Claude Code session did. Replaces manual /todo.

Usage: todo-sync.py SESSION_ID [--now] [--dry-run]
       todo-sync.py --current [--now]   (session from $CLAUDE_CODE_SESSION_ID)

1. Reads the part of the session transcript after `synced_until` (TODO.json sessions):
   the user's prompts, Claude's answers and MR/PR links. Tool output is skipped.
2. Asks headless Claude ($TODO_SYNC_MODEL, no tools, hooks off, no transcript saved) which
   `todo` commands follow from that work. Claude only returns JSON.
3. Checks each command and runs it with CLAUDE_CODE_SESSION_ID=SESSION_ID and TODO_SYNC=1,
   so the changes link to the session and are logged as "auto".
4. Saves a snapshot for `todo undo SESSION_ID` and moves `synced_until` forward.

Without --now it does nothing if the last sync of this session is younger than MIN_GAP_MIN.
"""
import glob, json, os, re, subprocess, sys
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, HERE)
import config as C
TODO_PY = os.path.join(HERE, "todo.py")
SNAP_DIR = C.SYNC_DIR
LOG = os.path.join(C.STATE, "sync.log")
MODEL = C.SYNC_MODEL
MIN_GAP_MIN = 30
MAX_CHARS = 40000          # transcript part sent to the model
PART_CHARS = 1500          # per prompt / answer
ALLOWED = {"done", "note", "add", "edit", "move", "new", "link"}

import todo as T


def log(msg):
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(f"{datetime.now():%Y-%m-%d %H:%M} {msg}\n")


def transcript_path(sid, db):
    p = db.get("sessions", {}).get(sid, {}).get("transcript")
    if p and os.path.isfile(p):
        return p
    hits = glob.glob(os.path.expanduser(f"~/.claude/projects/*/{sid}.jsonl"))
    return hits[0] if hits else None


def text_of(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") == "text")
    return ""


def read_delta(path, since):
    """Return (parts, last_ts, title, cwd) for records after `since` (ISO, UTC 'Z' strings compare fine)."""
    parts, last_ts, title, cwd = [], since, None, None
    for line in open(path, encoding="utf-8", errors="replace"):
        try:
            d = json.loads(line)
        except Exception:
            continue
        t = d.get("type")
        if t == "ai-title":
            title = d.get("aiTitle")
        ts = d.get("timestamp")
        if t == "pr-link" and ts and (not since or ts > since):
            parts.append(f"[MR/PR link] {d.get('prUrl')}")
            continue
        if t not in ("user", "assistant") or not ts or (since and ts <= since) or d.get("isSidechain"):
            continue
        if t == "user" and d.get("isMeta"):
            continue
        body = text_of((d.get("message") or {}).get("content")).strip()
        if not body or (t == "user" and body.startswith("<")):
            continue
        cwd = d.get("cwd") or cwd
        last_ts = ts
        who = "USER" if t == "user" else "CLAUDE"
        body = " ".join(body.split())
        parts.append(f"{who} ({ts[:16].replace('T', ' ')}): {body[:PART_CHARS]}")
    text = "\n".join(parts)
    if len(text) > MAX_CHARS:
        text = "[earlier part cut]\n" + text[-MAX_CHARS:]
    return text, last_ts, title, cwd


PROMPT = """You keep a developer's TODO list up to date from their Claude Code session.
Below: (A) the open TODO items with IDs, (B) what happened in the session since the last sync.
Return ONLY a JSON object: {{"commands": [[...], ...], "summary": "<one line>"}}.
Each command is an argument list for the `todo` tool:
  ["done", "tN", "--note", "<result, max 25 words>"]   finished (the note is optional)
  ["note", "tN", "<progress, max 25 words>"]            progress, not finished
  ["add", "sN", "<task>"] or ["add", "tN", "<sub-task>"] new task that came up
  ["edit", "tN", "<new text>"]                          task changed
  ["move", "sN", "Blocked", "--waits", "<who/what>"]    state changed (or "Active", "Backlog")
  ["new", "Active", "<title>"] then ["add", "$new1", "<task>"]   a new topic; $new1 = first new section
  ["link", "sN", "{cwd}"]                               this folder works on section sN
Rules:
- IDs: sN is a section, tN is an item. Use them exactly as listed in (A).
- Record only real work shown in (B): something built, fixed, merged, decided, sent, or found out.
- Mark done only when (B) shows it finished (merged, pushed, answered, decided). Otherwise use note.
- Do not repeat a note an item already has. Do not change items (B) does not touch.
- Small questions, chat and tooling setup produce no commands.
- If nothing to record, return {{"commands": [], "summary": "nothing to record"}}.
- Use short sentences and common words. Keep real names: MR numbers, ticket IDs.

Session folder: {cwd}

(A) Open TODO items:
{items}

(B) Session since last sync:
{delta}
"""


def ask_claude(prompt):
    env = dict(os.environ, TODO_SYNC="1")
    env.pop("CLAUDE_CODE_SESSION_ID", None)
    r = subprocess.run([C.claude_bin(), "-p", "--model", MODEL, "--tools", "", "--no-session-persistence",
                        "--settings", '{"disableAllHooks": true}', "--output-format", "text"],
                       input=prompt, capture_output=True, text=True, timeout=600, env=env,
                       cwd=C.STATE)
    if r.returncode:
        raise RuntimeError(f"claude -p failed: {r.stderr.strip()[:300]}")
    m = re.search(r"\{.*\}", r.stdout, re.S)
    if not m:
        raise RuntimeError(f"no JSON in answer: {r.stdout[:200]}")
    return json.loads(m.group(0))


def normalize(cmd):
    """Fix common shapes: ["done", "tN", "<note>"] -> ["done", "tN", "--note", "<note>"]."""
    if cmd and cmd[0] == "done":
        ids = [x for x in cmd[1:] if re.fullmatch(r"t\d+", x)]
        rest = [x for x in cmd[1:] if not re.fullmatch(r"t\d+", x) and x != "--note"]
        return ["done"] + ids + (["--note", " ".join(rest)] if rest else [])
    return cmd


def valid(cmd):
    return (isinstance(cmd, list) and cmd and all(isinstance(x, str) for x in cmd)
            and cmd[0] in ALLOWED and len(cmd) >= 2)


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    sid, now_flag, dry = sys.argv[1], "--now" in sys.argv, "--dry-run" in sys.argv
    if sid == "--current":
        sid = os.environ.get("CLAUDE_CODE_SESSION_ID") or sys.exit("no CLAUDE_CODE_SESSION_ID")
    os.makedirs(SNAP_DIR, exist_ok=True)
    # one worker per session at a time
    try:
        with C.locked(os.path.join(SNAP_DIR, f".{sid}.lock"), blocking=False):
            run(sid, now_flag, dry)
    except BlockingIOError:
        print("sync already running for this session")


def run(sid, now_flag, dry):
    db = T.load()
    s = db.get("sessions", {}).get(sid, {})
    if not now_flag and s.get("synced_at"):
        if datetime.now() - datetime.fromisoformat(s["synced_at"]) < timedelta(minutes=MIN_GAP_MIN):
            return
    path = transcript_path(sid, db)
    if not path:
        print("no transcript for session"); return
    delta, last_ts, title, cwd = read_delta(path, s.get("synced_until"))
    cwd = cwd or s.get("cwd") or HERE
    if not delta.strip():
        print("nothing new since last sync"); return

    items = subprocess.run([sys.executable, TODO_PY, "show", "--all", "--brief"],
                           capture_output=True, text=True).stdout
    try:
        ans = ask_claude(PROMPT.format(cwd=cwd, items=items, delta=delta))
    except Exception as e:
        log(f"{sid[:8]} ERROR {e}"); print(f"sync failed: {e}"); return
    cmds = [normalize(c) for c in ans.get("commands", []) if valid(c)]
    if dry:
        print(json.dumps(ans, indent=1, ensure_ascii=False)); return

    before = T.load()["sections"]
    env = dict(os.environ, TODO_SYNC="1", CLAUDE_CODE_SESSION_ID=sid)
    new_ids, done_lines = [], []
    for c in cmds:
        c = [re.sub(r"\$new(\d+)", lambda m: new_ids[int(m.group(1)) - 1] if int(m.group(1)) <= len(new_ids) else m.group(0), x)
             for x in c]
        r = subprocess.run([sys.executable, TODO_PY] + c, capture_output=True, text=True, env=env, cwd=cwd)
        out = (r.stdout or r.stderr).strip()
        if r.returncode and "no item or section with id t" in out and c[1].startswith("t"):
            c[1] = "s" + c[1][1:]              # model wrote tN for a section
            r = subprocess.run([sys.executable, TODO_PY] + c, capture_output=True, text=True, env=env, cwd=cwd)
            out = (r.stdout or r.stderr).strip()
        m = re.match(r"new section (s\d+)", out)
        if m:
            new_ids.append(m.group(1))
        done_lines.append(f"{' '.join(c[:2])} -> {out[:100]}")
    if cmds:
        db2 = T.load()
        json.dump({"time": T.now_s(), "before": before, "after": T.sections_hash(db2)},
                  open(os.path.join(SNAP_DIR, sid + ".json"), "w", encoding="utf-8"), ensure_ascii=False)
    subprocess.run([sys.executable, TODO_PY, "sync-mark", "--session", sid, "--until", last_ts]
                   + (["--title", title] if title else []), capture_output=True, env=dict(os.environ, TODO_SYNC="1"))
    log(f"{sid[:8]} {len(cmds)} commands. {ans.get('summary', '')}")
    print(f"{ans.get('summary', '')}\n" + "\n".join(done_lines))


if __name__ == "__main__":
    main()
