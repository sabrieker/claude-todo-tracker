#!/usr/bin/env python3
"""Collect the facts for a daily standup report, as compact markdown.

Usage: daily.py [YYYY-MM-DD]   (default: today)

Sources:
  1. Claude Code transcripts (~/.claude/projects/*/*.jsonl) with activity on that day:
     session title, folder, git branch, MR/PR links, the user's prompts.
  2. Git commits of that day in the folders those sessions used.
  3. TODO.md changes: today's file compared with the latest snapshot before that day
     (snapshots are written by board.py to $TODO_HOME/.state/history/).
"""
import difflib, glob, json, os, subprocess, sys
from datetime import date, datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import config as C
TODO, DONE, HISTORY = C.MD, C.DONE, C.HISTORY
PROJECTS = os.path.expanduser("~/.claude/projects")
AUTHOR = C.git_author()   # git --author filter (matches name or email)
MAX_PROMPTS = 6


def day_bounds(day):
    start = datetime.combine(day, datetime.min.time()).astimezone()
    return start, start + timedelta(days=1)


def prompt_text(msg):
    c = msg.get("content")
    if isinstance(c, list):
        c = " ".join(p.get("text", "") for p in c if isinstance(p, dict) and p.get("type") == "text")
    if not isinstance(c, str):
        return None
    c = c.strip()
    if not c or c.startswith("<") or c.startswith("[Request interrupted"):
        return None
    return " ".join(c.split())[:160]


def sessions(day):
    start, end = day_bounds(day)
    found = []
    for path in glob.glob(os.path.join(PROJECTS, "*", "*.jsonl")):
        if datetime.fromtimestamp(os.path.getmtime(path)).astimezone() < start:
            continue
        s = {"title": None, "cwd": None, "branch": None, "links": set(), "prompts": [], "first": None, "last": None}
        for line in open(path, encoding="utf-8", errors="replace"):
            try:
                d = json.loads(line)
            except Exception:
                continue
            t = d.get("type")
            if t == "ai-title":
                s["title"] = d.get("aiTitle")
            elif t == "pr-link" and d.get("prUrl"):
                s["links"].add(d["prUrl"])
            ts = d.get("timestamp")
            if not ts:
                continue
            when = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            if not (start <= when < end):
                continue
            s["cwd"] = d.get("cwd") or s["cwd"]
            s["branch"] = d.get("gitBranch") or s["branch"]
            if t == "user" and not d.get("isMeta") and not d.get("isSidechain"):
                p = prompt_text(d.get("message") or {})
                if p:
                    s["prompts"].append(p)
                    s["first"] = s["first"] or when
                    s["last"] = when
        if s["prompts"]:
            found.append(s)
    return sorted(found, key=lambda s: s["first"])


def commits(folders, day):
    out, seen = [], set()
    start, end = day_bounds(day)
    for f in folders:
        try:
            top = subprocess.run(["git", "-C", f, "rev-parse", "--show-toplevel"],
                                 capture_output=True, text=True, timeout=5).stdout.strip()
        except Exception:
            continue
        if not top or top in seen:
            continue
        seen.add(top)
        log = subprocess.run(["git", "-C", top, "log", "--all", "--no-merges"] + ([f"--author={AUTHOR}", "-i"] if AUTHOR else []) + [
                              f"--since={start.isoformat()}", f"--until={end.isoformat()}",
                              "--pretty=format:%h %s"], capture_output=True, text=True, timeout=10).stdout.strip()
        if log:
            out.append((top, log.splitlines()))
    return out


def todo_diff(day):
    if not os.path.isfile(TODO):
        return None
    older = sorted(p for p in glob.glob(os.path.join(HISTORY, "*.md"))
                   if os.path.basename(p)[:-3] < day.isoformat())
    if not older:
        return None
    current = open(os.path.join(HISTORY, f"{day.isoformat()}.md"), encoding="utf-8").read() \
        if day != date.today() and os.path.isfile(os.path.join(HISTORY, f"{day.isoformat()}.md")) \
        else open(TODO, encoding="utf-8").read()
    base = open(older[-1], encoding="utf-8").read()
    diff = [l for l in difflib.unified_diff(base.splitlines(), current.splitlines(), lineterm="", n=0)
            if l[:1] in "+-" and not l.startswith(("+++", "---"))]
    return os.path.basename(older[-1])[:-3], diff


def done_items(day):
    if not os.path.isfile(DONE):
        return []
    out, on = [], False
    for line in open(DONE, encoding="utf-8").read().splitlines():
        if line.startswith("## "):
            on = line[3:].strip() == day.isoformat()
        elif on and line.strip():
            out.append(line)
    return out


def main():
    day = date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 else date.today()
    ss = sessions(day)
    print(f"# Facts for {day.isoformat()}\n")
    print(f"Report file: {os.path.join(C.DAILY, day.isoformat() + '.md')}\n")
    print(f"## Claude Code sessions ({len(ss)})\n")
    for s in ss:
        where = s["cwd"].replace(os.path.expanduser("~"), "~") if s["cwd"] else "?"
        print(f"### {s['title'] or '(no title)'}")
        print(f"- folder: `{where}`" + (f", branch `{s['branch']}`" if s["branch"] else ""))
        print(f"- time: {s['first']:%H:%M}–{s['last']:%H:%M}, {len(s['prompts'])} prompts")
        for l in sorted(s["links"]):
            print(f"- link: {l}")
        ps = s["prompts"]
        shown = ps if len(ps) <= MAX_PROMPTS else ps[:3] + ["…"] + ps[-3:]
        for p in shown:
            print(f"  - {p}")
        print()
    cs = commits({s["cwd"] for s in ss if s["cwd"]}, day)
    print("## Git commits\n")
    if not cs:
        print("_None found._\n")
    for top, lines in cs:
        print(f"- `{top.replace(os.path.expanduser('~'), '~')}`")
        for l in lines[:15]:
            print(f"  - {l}")
    print()
    print("## TODO items marked done that day\n")
    print("\n".join(done_items(day)) or "_None._")
    print()
    d = todo_diff(day)
    print("## TODO.md changes\n")
    if d is None:
        print("_No earlier snapshot to compare with yet._")
    else:
        print(f"Compared with snapshot {d[0]}:\n")
        print("\n".join(d[1]) if d[1] else "_No changes._")


if __name__ == "__main__":
    main()
