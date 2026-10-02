#!/usr/bin/env python3
"""Collect the facts for "what is the plan for today", as compact markdown.

Usage: plan.py [DAYS]   (look back DAYS days for open sessions, default 4)

Sources:
  1. The latest daily report before today ($TODO_HOME/daily/YYYY-MM-DD.md): its Tomorrow and Blockers parts.
  2. Claude Code sessions active in the last DAYS days: title, folder, last activity,
     last prompt, whether /todo ran after the last work, and the linked TODO sections (from TODO.json).
  3. All open TODO items (todo show --all).
"""
import glob, json, os, re, subprocess, sys
from datetime import date, datetime, timedelta

HERE = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, HERE)
import config as C
DAILY = C.DAILY
PROJECTS = os.path.expanduser("~/.claude/projects")
import todo as T   # TODO.json sessions and section links


def last_report():
    today = date.today().isoformat()
    files = sorted(f for f in glob.glob(os.path.join(DAILY, "????-??-??.md"))
                   if os.path.basename(f)[:10] < today)
    if not files:
        return None, ""
    text = open(files[-1], encoding="utf-8").read()
    parts = re.split(r"(?m)^## ", text)
    keep = [p for p in parts if p.startswith(("Tomorrow", "Blockers"))]
    return os.path.basename(files[-1])[:10], "\n".join("## " + p.strip() for p in keep)


def prompt_text(msg):
    c = msg.get("content")
    if isinstance(c, list):
        c = " ".join(p.get("text", "") for p in c if isinstance(p, dict) and p.get("type") == "text")
    if not isinstance(c, str) or not c.strip() or c.lstrip().startswith("<"):
        return None
    return " ".join(c.split())[:140]


def sessions(days):
    since = datetime.now() - timedelta(days=days)
    db = T.load()
    state = db.get("sessions", {})
    out = []
    for path in glob.glob(os.path.join(PROJECTS, "*", "*.jsonl")):
        if datetime.fromtimestamp(os.path.getmtime(path)) < since:
            continue
        sid = os.path.basename(path)[:-6]
        s = {"id": sid, "title": None, "cwd": None, "last": None, "prompt": None}
        for line in open(path, encoding="utf-8", errors="replace"):
            try:
                d = json.loads(line)
            except Exception:
                continue
            if d.get("type") == "ai-title":
                s["title"] = d.get("aiTitle")
            if d.get("type") == "user" and not d.get("isMeta") and not d.get("isSidechain"):
                p = prompt_text(d.get("message") or {})
                if p:
                    s["prompt"], s["cwd"] = p, d.get("cwd") or s["cwd"]
                    s["last"] = d.get("timestamp")
        if not s["last"]:
            continue
        s["last"] = datetime.fromisoformat(s["last"].replace("Z", "+00:00")).astimezone()
        st = state.get(sid, {"cwd": s["cwd"], "touched": []})
        s["todo"] = st.get("last_todo")
        s["sections"] = T.linked_sections(db, dict(st, cwd=st.get("cwd") or s["cwd"]))
        out.append(s)
    return sorted(out, key=lambda s: s["last"], reverse=True)


def main():
    days = int(sys.argv[1]) if len(sys.argv) > 1 else 4
    print(f"# Facts for the plan of {date.today().isoformat()}\n")
    print(f"Plan file: {os.path.join(DAILY, date.today().isoformat() + '-plan.md')}\n")
    day, rep = last_report()
    print(f"## From the last daily report ({day or 'none'})\n")
    print(rep or "_No earlier report._")
    print(f"\n## Sessions active in the last {days} days\n")
    home = os.path.expanduser("~")
    for s in sessions(days):
        rec = f"TODO updated {s['todo']}" if s["todo"] else "no TODO changes yet"
        print(f"- **{s['title'] or '(no title)'}** — `{(s['cwd'] or '?').replace(home, '~')}`, "
              f"last {s['last']:%a %H:%M}, {rec}, TODO sections: {', '.join(s['sections']) or 'none'}")
        print(f"  - last prompt: {s['prompt']}")
        print(f"  - resume: `cd {s['cwd']} && claude --resume {s['id']}`")
    print("\n## Open TODO items\n")
    r = subprocess.run([sys.executable, os.path.join(HERE, "todo.py"), "show", "--all"],
                       capture_output=True, text=True)
    print(r.stdout.strip())


if __name__ == "__main__":
    main()
