#!/usr/bin/env python3
"""todo — edit the TODO list with one short command instead of editing markdown.

Files, in $TODO_HOME (default ~/todo):
  TODO.json     source of truth
  TODO.md       generated; hand edits are imported on the next call
  TODO.html     Kanban board, via board.py
  TODO-done.md  done items move here at once; sessions never load it

Commands (IDs: sN = section, tN = item):
  show [--cwd DIR] [--all]          open items with IDs (default: sections linked to DIR)
  add  sN|tN "text"                 new item in a section, or a child under an item
  done tN [tN ...] [--note "text"]  mark done and move to TODO-done.md
  note sN|tN "text"                 add a note line to a section or item
  edit tN|sN "text"                 replace an item's text or a section's title
  move sN Active|Backlog|Blocked [--waits "who/what"]
  new  Active|Backlog|Blocked "title" [--projects dir1,dir2]   prints the new sN
  rm   sN|tN                        delete without marking done
  link sN DIR [DIR ...]             link project folders to a section (session start shows it there)
  render                            rebuild TODO.md, the board and today's snapshot
  sessions [--days N]               Claude Code sessions with their linked sections
  ping --session ID --cwd DIR       (hooks) record a prompt, or --ended
  undo SESSION                      undo the last automatic sync of that session

Every change is linked to the Claude Code session that made it (CLAUDE_CODE_SESSION_ID).
"""
import argparse, fcntl, hashlib, json, os, re, shutil, subprocess, sys
from datetime import date, datetime, timedelta

HERE = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, HERE)
import config as C
DATA, MD, DONE = C.DATA, C.MD, C.DONE
LOCK = os.path.join(C.STATE, ".todo.lock")
GROUPS = ["Active", "Backlog", "Blocked"]
TASK = re.compile(r"(\s*)- \[( |x|X)\] (.*)")


# ---------- storage ----------

def empty():
    return {"last_updated": date.today().isoformat(), "next_id": 1, "md_hash": "", "sections": []}


def load():
    if os.path.isfile(DATA):
        return json.load(open(DATA, encoding="utf-8"))
    return empty()


def save(db, bump=True):
    if bump:
        db["last_updated"] = date.today().isoformat()
    tmp = DATA + ".tmp"
    json.dump(db, open(tmp, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    os.replace(tmp, DATA)


def new_id(db, prefix):
    n = db["next_id"]; db["next_id"] += 1
    return f"{prefix}{n}"


def md_hash():
    return hashlib.sha1(open(MD, "rb").read()).hexdigest() if os.path.isfile(MD) else ""


# ---------- lookup ----------

def walk(items, parent=None):
    for it in items:
        yield it, parent, items
        yield from walk(it["children"], it)


def find(db, ref):
    for s in db["sections"]:
        if s["id"] == ref:
            return s, None, db["sections"]
        for it, parent, lst in walk(s["items"]):
            if it["id"] == ref:
                return it, s, lst
    sys.exit(f"todo: no item or section with id {ref}. Run: todo show --all")


def has_open(items):
    return any(not it["done"] or has_open(it["children"]) for it in items)


# ---------- markdown import (hand edits, first migration) ----------

def import_md(db):
    """Rebuild sections from TODO.md, keeping existing IDs where titles/texts match."""
    old_sec = {s["title"]: s["id"] for s in db["sections"]}
    old_item = {}
    for s in db["sections"]:
        for it, _, _ in walk(s["items"]):
            old_item[it["text"]] = it["id"]
    sections, group, sec, stack, in_code = [], None, None, [], False
    for line in open(MD, encoding="utf-8").read().splitlines():
        if line.startswith("```"):
            in_code = not in_code
        if not in_code and line.startswith("## "):
            group, sec = line[3:].strip(), None
            continue
        if not in_code and line.startswith("### ") and group:
            title = line[4:].strip()
            sec = {"id": old_sec.get(title) or new_id(db, "s"), "title": title, "group": group,
                   "projects": [], "waits_for": None, "notes": [], "items": []}
            sections.append(sec); stack = []
            continue
        if sec is None:
            continue
        m = re.match(r"\s*<!--\s*projects:(.*)-->", line)
        if m:
            sec["projects"] = [p.strip() for p in m.group(1).split(",") if p.strip()]
            continue
        if line.startswith("Waits for:"):
            sec["waits_for"] = line[len("Waits for:"):].strip()
            continue
        m = TASK.match(line) if not in_code else None
        if m:
            ind, text = len(m.group(1)), m.group(3).strip()
            it = {"id": old_item.get(text) or new_id(db, "t"), "text": text,
                  "done": m.group(2).lower() == "x", "notes": [], "children": []}
            while stack and stack[-1][0] >= ind:
                stack.pop()
            (stack[-1][1]["children"] if stack else sec["items"]).append(it)
            stack.append((ind, it))
            continue
        if not line.strip():
            if not in_code:
                stack = [] if not sec["items"] else stack
            continue
        ind = len(line) - len(line.lstrip())
        if stack and ind > stack[-1][0] and not in_code:
            stack[-1][1]["notes"].append(line.strip().removeprefix("- ").strip())
        else:
            sec["notes"].append(line)
    db["sections"] = [s for s in sections if s["group"] != "Done"]
    return db


# ---------- rendering ----------

def render_items(items, depth, out):
    for it in items:
        pad = "  " * depth
        out.append(f"{pad}- [{'x' if it['done'] else ' '}] {it['text']}")
        for n in it["notes"]:
            out.append(f"{pad}  - {n}")
        render_items(it["children"], depth + 1, out)


def render_md(db):
    out = ["---", "name: Daily-ToDo-List",
           "description: Generated from TODO.json by the todo command. Hand edits are imported on the next todo call.",
           "---", "", "# TODO", "", f"Last updated: {db['last_updated']}", ""]
    for g in GROUPS + sorted({s["group"] for s in db["sections"]} - set(GROUPS)):
        out += [f"## {g}", ""]
        for s in [s for s in db["sections"] if s["group"] == g]:
            out.append(f"### {s['title']}")
            if s["projects"]:
                out.append(f"<!-- projects: {', '.join(s['projects'])} -->")
            if s["waits_for"]:
                out.append(f"Waits for: {s['waits_for']}")
            out += s["notes"]
            render_items(s["items"], 0, out)
            out.append("")
        if not any(s["group"] == g for s in db["sections"]):
            out += ["_None right now._", ""]
    open(MD, "w", encoding="utf-8").write(re.sub(r"\n{3,}", "\n\n", "\n".join(out)).rstrip() + "\n")


def render_all(db):
    render_md(db)
    db["md_hash"] = md_hash()
    save(db)
    if os.environ.get("TODO_NO_BOARD") != "1":
        subprocess.run([sys.executable, os.path.join(HERE, "board.py")], stdin=subprocess.DEVNULL)


# ---------- done archive ----------

def archive(title, group, lines):
    today = date.today().isoformat()
    block = [f"### {title}   ({group})"] + lines
    old = open(DONE, encoding="utf-8").read() if os.path.isfile(DONE) else \
        "# TODO done\n\nItems moved here from TODO.md when ticked. Sessions do not load this file.\n"
    head, sep, rest = old.partition("\n## ")
    if sep and rest.startswith(today + "\n"):
        first, _, remainder = rest.partition("\n")
        new = head + sep + first + "\n\n" + "\n".join(block) + "\n" + remainder
    else:
        new = head.rstrip() + f"\n\n## {today}\n\n" + "\n".join(block) + "\n" + ("\n## " + rest if sep else "")
    open(DONE, "w", encoding="utf-8").write(re.sub(r"\n{3,}", "\n\n", new).rstrip() + "\n")


def as_lines(it):
    out = []
    render_items([dict(it, done=True)], 0, out)
    return [re.sub(r"- \[ \]", "- [x]", l) for l in out]


def sweep(db):
    """Archive sections with no open item left (unless waiting); archive done items."""
    keep = []
    for s in db["sections"]:
        done_items = [it for it in s["items"] if it["done"] and not has_open(it["children"])]
        waiting = s["group"] == "Blocked" or s["waits_for"]
        if s["items"] and not has_open(s["items"]) and not waiting:
            archive(s["title"], s["group"], sum((as_lines(i) for i in s["items"]), []) +
                    [n for n in s["notes"] if n.strip()])
            continue
        if done_items:
            archive(s["title"], s["group"], sum((as_lines(i) for i in done_items), []))
            s["items"] = [it for it in s["items"] if it not in done_items]
        for it, parent, lst in list(walk(s["items"])):
            gone = [c for c in it["children"] if c["done"] and not has_open(c["children"])]
            if gone:
                archive(s["title"], s["group"], sum((as_lines(c) for c in gone), []))
                it["children"] = [c for c in it["children"] if c not in gone]
        keep.append(s)
    db["sections"] = keep


# ---------- show ----------

def show_items(items, depth, out, notes=True):
    for it in items:
        if it["done"] and not has_open(it["children"]):
            continue
        out.append(f"{'  ' * depth}  {it['id']} [{'x' if it['done'] else ' '}] {it['text']}")
        if notes:
            for n in it["notes"]:
                out.append(f"{'  ' * depth}       · {n}")
        show_items(it["children"], depth + 1, out, notes)


def linked(s, cwd):
    cwd = os.path.realpath(cwd)
    for p in s["projects"]:
        p = os.path.realpath(os.path.expanduser(p))
        if cwd == p or cwd.startswith(p + os.sep):
            return True
    return False


def show(db, cwd=None, all_=False, full_notes=True):
    out = []
    mine = [s for s in db["sections"] if all_ or (cwd and linked(s, cwd))]
    for s in mine:
        out.append(f"[{s['id']}] {s['title']} · {s['group']}")
        if s["waits_for"]:
            out.append(f"    waits for: {s['waits_for']}")
        if full_notes:
            out += [f"    {n}" for n in s["notes"] if n.strip()]
        show_items(s["items"], 1, out, full_notes)
        out.append("")
    others = [s for s in db["sections"] if s not in mine]
    if others:
        out.append("Other sections: " + "; ".join(f"[{s['id']}] {s['title']} ({s['group']})" for s in others))
    return "\n".join(out)


# ---------- sessions ----------
# db["sessions"][session_id] = {cwd, first_seen, last_prompt, prompts, last_todo, touched: [sN]}
# Filled by `todo ping` (UserPromptSubmit hook) and by every change command, which reads
# CLAUDE_CODE_SESSION_ID (subagents and forks of a session share it).

SESSION_DAYS = 30
now_s = lambda: datetime.now().isoformat(timespec="minutes")


def session(db, sid, cwd=None):
    ss = db.setdefault("sessions", {})
    s = ss.setdefault(sid, {"cwd": cwd, "first_seen": now_s(), "last_prompt": None,
                            "prompts": 0, "last_todo": None, "touched": []})
    if cwd:
        s["cwd"] = cwd
    return s


LOG_KEEP = 300


def record_change(db, section_ids, text=""):
    sid = os.environ.get("CLAUDE_CODE_SESSION_ID")
    if not section_ids:                     # e.g. `todo render` changes nothing
        return
    db.setdefault("log", []).append({"t": now_s(), "session": sid, "text": text, "sections": list(section_ids),
                                     "source": "auto" if os.environ.get("TODO_SYNC") else "manual"})
    db["log"] = db["log"][-LOG_KEEP:]
    if not sid:
        return
    s = session(db, sid)
    s["cwd"] = s.get("cwd") or os.getcwd()   # the hook knows the real folder; keep it
    s["last_todo"] = now_s()
    for x in section_ids:
        if x not in s["touched"]:
            s["touched"].append(x)


def sections_hash(db):
    return hashlib.sha1(json.dumps(db["sections"], sort_keys=True).encode()).hexdigest()


def prune_sessions(db):
    cut = (datetime.now() - timedelta(days=SESSION_DAYS)).isoformat()
    live = {x["id"] for x in db["sections"]}
    for sid, s in list(db.get("sessions", {}).items()):
        if (s.get("last_prompt") or s.get("last_todo") or s["first_seen"]) < cut:
            del db["sessions"][sid]
        else:
            s["touched"] = [x for x in s["touched"] if x in live]


def linked_sections(db, s):
    out = list(s["touched"])
    for sec in db["sections"]:
        if s.get("cwd") and linked(sec, s["cwd"]) and sec["id"] not in out:
            out.append(sec["id"])
    return out


def list_sessions(db, days):
    cut = (datetime.now() - timedelta(days=days)).isoformat()
    rows = []
    for sid, s in db.get("sessions", {}).items():
        last = s.get("last_prompt") or s.get("last_todo") or s["first_seen"]
        if last < cut:
            continue
        pending = s.get("last_prompt") and (not s.get("last_todo") or s["last_todo"] < s["last_prompt"][:10])
        rows.append((last, f"{sid}  last {last}  {'todo pending' if pending else 'todo ok'}  "
                           f"sections {','.join(linked_sections(db, s)) or '-'}  cwd {s.get('cwd')}"))
    return "\n".join(r for _, r in sorted(rows, reverse=True))


# ---------- main ----------

def main():
    ap = argparse.ArgumentParser(prog="todo", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd")
    p = sub.add_parser("show"); p.add_argument("--cwd"); p.add_argument("--all", action="store_true")
    p.add_argument("--brief", action="store_true", help="items only, no notes")
    p = sub.add_parser("add"); p.add_argument("ref"); p.add_argument("text")
    p = sub.add_parser("done"); p.add_argument("refs", nargs="+"); p.add_argument("--note")
    p = sub.add_parser("note"); p.add_argument("ref"); p.add_argument("text")
    p = sub.add_parser("edit"); p.add_argument("ref"); p.add_argument("text")
    p = sub.add_parser("move"); p.add_argument("ref"); p.add_argument("group", choices=GROUPS); p.add_argument("--waits")
    p = sub.add_parser("new"); p.add_argument("group", choices=GROUPS); p.add_argument("title"); p.add_argument("--projects")
    p = sub.add_parser("rm"); p.add_argument("ref")
    p = sub.add_parser("link", help="add project folders to a section"); p.add_argument("ref"); p.add_argument("dirs", nargs="+")
    sub.add_parser("render")
    p = sub.add_parser("ping", help="(hook) record a prompt in a session")
    p.add_argument("--session", required=True); p.add_argument("--cwd"); p.add_argument("--is-todo", action="store_true")
    p.add_argument("--transcript"); p.add_argument("--ended", action="store_true")
    p = sub.add_parser("sync-mark", help="(sync worker) store sync progress of a session")
    p.add_argument("--session", required=True); p.add_argument("--until", required=True); p.add_argument("--title")
    p = sub.add_parser("undo", help="undo the last automatic sync of a session"); p.add_argument("session")
    p = sub.add_parser("sessions", help="sessions of the last N days with their linked sections")
    p.add_argument("--days", type=int, default=4)
    a = ap.parse_args()
    if not a.cmd:
        ap.print_help(); return

    C.ensure_dirs()
    with open(LOCK, "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        db = load()
        if os.path.isfile(MD) and md_hash() != db.get("md_hash"):
            import_md(db)            # hand edit (or first run): take TODO.md as the truth
            changed = True
        else:
            changed = False

        if a.cmd == "ping":
            s = session(db, a.session, a.cwd)
            before = {"last_prompt": s["last_prompt"], "last_todo": s["last_todo"]}
            if a.transcript:
                s["transcript"] = a.transcript
            if a.ended:
                s["ended"] = now_s()
            else:
                s["last_prompt"] = now_s(); s["prompts"] += 1; s.pop("ended", None)
            if a.is_todo:
                s["last_todo"] = now_s()
            prune_sessions(db)
            if not changed:
                save(db, bump=False)          # no render: the list itself did not change
            else:
                sweep(db); render_all(db)
            print(json.dumps(before))
            return
        if a.cmd == "sync-mark":
            s = session(db, a.session)
            s["synced_until"], s["synced_at"] = a.until, now_s()
            if a.title:
                s["title"] = a.title
            save(db, bump=False)
            print("marked")
            return
        if a.cmd == "undo":
            snap = os.path.join(C.SYNC_DIR, a.session + ".json")
            if not os.path.isfile(snap):
                sys.exit(f"todo: no automatic sync to undo for session {a.session}.")
            sn = json.load(open(snap))
            if sections_hash(db) != sn["after"]:
                sys.exit("todo: the list changed after that sync, so undo would lose newer changes. "
                         "Fix it by hand with todo commands.")
            db["sections"] = sn["before"]
            db.setdefault("log", []).append({"t": now_s(), "session": a.session, "source": "manual",
                                             "text": f"undo sync of {sn['time']}"})
            os.remove(snap)
            render_all(db)
            print(f"undone sync of {sn['time']}")
            return
        if a.cmd == "sessions":
            print(list_sessions(db, a.days))
            return
        if a.cmd == "show":
            if changed:
                sweep(db); render_all(db)
            print(show(db, a.cwd or os.getcwd(), a.all, not a.brief))
            return
        if a.cmd == "add":
            obj, sec, _ = find(db, a.ref)
            it = {"id": new_id(db, "t"), "text": a.text, "done": False, "notes": [], "children": []}
            (obj["items"] if sec is None else obj["children"]).append(it)
            touched = [(sec or obj)["id"]]
            msg = f"added {it['id']}"
        elif a.cmd == "done":
            touched = []
            for r in a.refs:
                obj, sec, _ = find(db, r)
                if sec is None:
                    sys.exit("todo: done takes item ids (tN). To finish a whole section, mark its items done.")
                obj["done"] = True
                touched.append(sec["id"])
                if a.note:
                    obj["notes"].append(a.note)
            msg = "done " + " ".join(a.refs)
        elif a.cmd == "note":
            obj, sec, _ = find(db, a.ref)
            obj["notes"].append(a.text)
            touched = [(sec or obj)["id"]]
            msg = f"noted {a.ref}"
        elif a.cmd == "edit":
            obj, sec, _ = find(db, a.ref)
            obj["title" if sec is None else "text"] = a.text
            touched = [(sec or obj)["id"]]
            msg = f"edited {a.ref}"
        elif a.cmd == "move":
            obj, sec, _ = find(db, a.ref)
            if sec is not None:
                sys.exit("todo: move takes a section id (sN).")
            obj["group"] = a.group
            obj["waits_for"] = a.waits if a.group == "Blocked" else (a.waits or None)
            touched = [obj["id"]]
            msg = f"moved {a.ref} to {a.group}"
        elif a.cmd == "new":
            projects = [p.strip() for p in (a.projects or os.getcwd().replace(os.path.expanduser("~"), "~")).split(",")]
            s = {"id": new_id(db, "s"), "title": a.title, "group": a.group, "projects": projects,
                 "waits_for": None, "notes": [], "items": []}
            db["sections"].append(s)
            touched = [s["id"]]
            msg = f"new section {s['id']}"
        elif a.cmd == "link":
            obj, sec, _ = find(db, a.ref)
            if sec is not None:
                sys.exit("todo: link takes a section id (sN).")
            for d in a.dirs:
                d = os.path.abspath(os.path.expanduser(d)).replace(os.path.expanduser("~"), "~")
                if d not in obj["projects"]:
                    obj["projects"].append(d)
            touched = [obj["id"]]
            msg = f"linked {a.ref}: {', '.join(obj['projects'])}"
        elif a.cmd == "rm":
            obj, sec, lst = find(db, a.ref)
            lst.remove(obj)
            touched = [(sec or obj)["id"]]
            msg = f"removed {a.ref}"
        else:
            touched = []
            msg = "rendered"
        detail = getattr(a, "note", None) or getattr(a, "text", None) or getattr(a, "title", None) or ""
        record_change(db, touched, msg + (f": {detail[:120]}" if detail else ""))
        sweep(db)
        render_all(db)
        print(msg)


if __name__ == "__main__":
    main()
