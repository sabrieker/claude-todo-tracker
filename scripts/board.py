#!/usr/bin/env python3
"""Render TODO.md as a Kanban board: one column per '## ' group, one card per '### ' section.

Usage: board.py [--open]   (todo.py runs it after every change)
Writes $TODO_HOME/TODO.html and a daily snapshot of TODO.md for /daily.
"""
import html, json, os, re, shutil, subprocess, sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import config as C
TODO, OUT, DONE = C.MD, C.HTML, C.DONE
DONE_DAYS = 7
COLUMN_ORDER = ["Active", "Backlog", "Blocked"]


def inline(text):
    parts = re.split(r"(`[^`]+`)", text)
    out = []
    for p in parts:
        if p.startswith("`") and p.endswith("`") and len(p) > 1:
            out.append(f"<code>{html.escape(p[1:-1])}</code>")
            continue
        p = html.escape(p, quote=False)
        p = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", p)
        p = re.sub(r"(?<![\w*])_(.+?)_(?![\w*])", r"<em>\1</em>", p)
        p = re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)",
                   r'<a href="\2" target="_blank" rel="noopener">\1</a>', p)
        p = re.sub(r'(?<!href=")(?<!">)(https?://[^\s<]+)',
                   lambda m: f'<a href="{m.group(1)}" target="_blank" rel="noopener">{short_url(m.group(1))}</a>', p)
        out.append(p)
    return "".join(out)


def short_url(u):
    u = re.sub(r"^https?://", "", u)
    return u if len(u) <= 48 else u[:45] + "…"


def parse():
    groups, group, card = {}, None, None
    in_code = False
    for raw in open(TODO, encoding="utf-8"):
        line = raw.rstrip("\n")
        if line.startswith("```"):
            in_code = not in_code
            if card is not None:
                card["lines"].append(line)
            continue
        if not in_code and line.startswith("## "):
            group = line[3:].strip()
            groups.setdefault(group, [])
            card = None
        elif not in_code and line.startswith("### ") and group:
            card = {"title": line[4:].strip(), "lines": [], "projects": []}
            groups[group].append(card)
        elif card is not None:
            m = re.match(r"\s*<!--\s*projects:(.*)-->", line)
            if m:
                card["projects"] = [p.strip() for p in m.group(1).split(",") if p.strip()]
            else:
                card["lines"].append(line)
    return groups


def render_body(lines):
    """Split card lines into tasks (checkboxes) and other content."""
    tasks, rest, in_code = [], [], False
    for line in lines:
        if line.startswith("```"):
            rest.append("</pre>" if in_code else "<pre>")
            in_code = not in_code
            continue
        if in_code:
            rest.append(html.escape(line) + "\n")
            continue
        m = re.match(r"(\s*)- \[( |x|X)\] (.*)", line)
        if m:
            tasks.append((len(m.group(1)) > 0, m.group(2).lower() == "x", inline(m.group(3))))
            continue
        if not line.strip():
            continue
        m = re.match(r"(\s*)- (.*)", line)
        if m:
            cls = ' class="sub"' if m.group(1) else ""
            rest.append(f"<li{cls}>{inline(m.group(2))}</li>")
        else:
            rest.append(f"<p>{inline(line.strip())}</p>")
    # wrap consecutive <li> in <ul>
    joined, open_ul = [], False
    for r in rest:
        if r.startswith("<li") and not open_ul:
            joined.append("<ul>"); open_ul = True
        if not r.startswith("<li") and open_ul and not r.endswith("\n"):
            joined.append("</ul>"); open_ul = False
        joined.append(r)
    if open_ul:
        joined.append("</ul>")
    return tasks, "".join(joined)


def parse_done():
    """Recent cards from TODO-done.md: [(date, title, lines)], newest first."""
    if not os.path.isfile(DONE):
        return []
    cards, day, card = [], None, None
    for line in open(DONE, encoding="utf-8").read().splitlines():
        if line.startswith("## "):
            day = line[3:].strip(); card = None
        elif line.startswith("### ") and day:
            card = {"day": day, "title": re.sub(r"\s+\((\w+)\)$", "", line[4:].strip()), "lines": []}
            cards.append(card)
        elif card is not None:
            card["lines"].append(line)
    days = sorted({c["day"] for c in cards}, reverse=True)[:DONE_DAYS]
    return [c for c in cards if c["day"] in days]


def sessions_by_title():
    """Sessions that changed each section (via the todo command), newest first, last 14 days."""
    try:
        db = json.load(open(TODO[:-3] + ".json", encoding="utf-8"))
    except Exception:
        return {}
    cut = (datetime.now() - timedelta(days=14)).isoformat()
    titles = {s["id"]: s["title"] for s in db["sections"]}
    out = {}
    for sid, s in db.get("sessions", {}).items():
        last = s.get("last_prompt") or s.get("last_todo") or ""
        if last < cut:
            continue
        for x in s.get("touched", []):
            if x in titles:
                out.setdefault(titles[x], []).append((last, sid, s.get("cwd") or "~"))
    return {t: sorted(v, reverse=True) for t, v in out.items()}


def load_db():
    try:
        return json.load(open(TODO[:-3] + ".json", encoding="utf-8"))
    except Exception:
        return {"sections": [], "sessions": {}, "log": []}


def transcript_title(path):
    """Last ai-title in a transcript; reads only the end of the file."""
    try:
        with open(path, "rb") as f:
            f.seek(max(0, os.path.getsize(path) - 400_000))
            tail = f.read().decode("utf-8", "replace")
        m = re.findall(r'"aiTitle":\s*"((?:[^"\\]|\\.)*)"', tail)
        return json.loads(f'"{m[-1]}"') if m else None
    except Exception:
        return None


def session_title(sid, s):
    t = s.get("title")
    if not t and s.get("transcript"):
        t = transcript_title(s["transcript"])
    return t or os.path.basename((s.get("cwd") or "").rstrip("/")) or sid[:8]


def ago(iso):
    try:
        m = int((datetime.now() - datetime.fromisoformat(iso)).total_seconds() // 60)
    except Exception:
        return "?"
    return f"{m} min ago" if m < 60 else f"{m // 60} h ago" if m < 48 * 60 else f"{m // 1440} d ago"


def live_panels(db):
    """Sessions strip, recent-changes feed, and {section title: last change}."""
    now = datetime.now()
    ss = db.get("sessions", {})
    titles = {sid: session_title(sid, s) for sid, s in ss.items()}
    rows = []
    for sid, s in ss.items():
        last = s.get("last_prompt") or s.get("first_seen") or ""
        if not last or datetime.fromisoformat(last) < now - timedelta(days=3):
            continue
        idle_min = (now - datetime.fromisoformat(last)).total_seconds() / 60
        state = "ended" if s.get("ended") else "active" if idle_min < 30 else "idle"
        pending = not s.get("synced_until") or (s.get("synced_at") or "") < last
        sync = f"synced {ago(s['synced_at'])}" if s.get("synced_at") else "not synced yet"
        cwd = s.get("cwd") or "~"
        short = os.path.basename(cwd.rstrip("/"))
        flag = ' <span class="pending">update pending</span>' if pending and state != "active" else ""
        rows.append((state != "active", last, f"""<tr class="st-{state}"><td><span class="dot"></span></td>
<td><b>{html.escape(titles[sid])}</b>{flag}</td><td class="m" title="{html.escape(cwd)}">{html.escape(short)}</td>
<td class="m">{state} · {ago(last)}</td><td class="m">{sync}</td>
<td><details><summary>resume</summary><code class="resume">cd {html.escape(cwd)} &amp;&amp; claude --resume {sid}</code></details></td></tr>"""))
    rows.sort(key=lambda r: (r[0], [-ord(ch) for ch in r[1]]))
    rows = [r[2] for r in rows]
    head, rest = rows[:8], rows[8:]
    strip = ("<table class='sess'>" + "".join(head) + "</table>" +
             (f"<details class='more'><summary>Show all ({len(rows)})</summary><table class='sess'>{''.join(rest)}</table></details>" if rest else "")
             ) if rows else '<p class="empty">No sessions in the last 3 days.</p>'
    sec_titles = {x["id"]: x["title"] for x in db.get("sections", [])}
    last_change, feed = {}, []
    for e in reversed(db.get("log", [])):
        who = titles.get(e.get("session")) or ("terminal" if not e.get("session") else e["session"][:8])
        for x in e.get("sections", []):
            if x in sec_titles and sec_titles[x] not in last_change:
                last_change[sec_titles[x]] = (e["t"], e["source"], who)
        if len(feed) < 20:
            feed.append(f"""<li><span class="when">{e['t'][5:16].replace('T', ' ')}</span>
<span class="src src-{e['source']}">{e['source']}</span> {inline(e.get('text') or '')}
<span class="who">· {html.escape(who)}</span></li>""")
    changes = "".join(feed) or '<li class="empty">No changes yet.</li>'
    return strip, changes, last_change


def render(groups):
    by_title = sessions_by_title()
    strip, changes, last_change = live_panels(load_db())
    names = [g for g in COLUMN_ORDER if g in groups] + [g for g in groups if g not in COLUMN_ORDER]
    cols = []
    for g in names:
        cards = []
        for c in groups[g]:
            tasks, notes = render_body(c["lines"])
            done = sum(1 for t in tasks if t[1])
            pct = int(100 * done / len(tasks)) if tasks else 0
            items = "".join(
                f'<li class="{"done" if d else ""}{" sub" if sub else ""}">'
                f'<span class="box">{"✓" if d else ""}</span><span>{t}</span></li>'
                for sub, d, t in tasks)
            tags = "".join(f"<span class=tag title='{html.escape(p)}'>{html.escape(os.path.basename(p.rstrip('/')))}</span>"
                           for p in c["projects"])
            progress = (f'<div class="progress"><div style="width:{pct}%"></div></div>'
                        f'<div class="count">{done}/{len(tasks)} done</div>') if tasks else ""
            details = f"<details><summary>Notes</summary>{notes}</details>" if notes else ""
            ss = by_title.get(c["title"], [])
            if ss:
                rows = "".join(f"<li>{last[5:10]} {last[11:]} · <code>cd {html.escape(cwd)} &amp;&amp; claude --resume {sid}</code></li>"
                               for last, sid, cwd in ss)
                details += f'<details class="sess"><summary>Sessions ({len(ss)})</summary><ul>{rows}</ul></details>'
            lc = last_change.get(c["title"])
            upd = (f'<div class="upd">updated {lc[0][5:16].replace("T", " ")} · {lc[1]} · {html.escape(lc[2])}</div>'
                   if lc else "")
            cards.append(f"""<article class="card">
<h3>{inline(c['title'])}</h3>{upd}{progress}
<ul class="tasks">{items}</ul>{details}
<div class="tags">{tags}</div></article>""")
        empty = '<p class="empty">No items</p>' if not cards else ""
        cols.append(f"""<section class="col col-{g.lower()}">
<header><h2>{html.escape(g)}</h2><span class="n">{len(cards)}</span></header>
{''.join(cards)}{empty}</section>""")

    done = parse_done()
    dcards = []
    for c in done:
        tasks, notes = render_body(c["lines"])
        items = "".join(f'<li class="done{" sub" if sub else ""}"><span class="box">✓</span><span>{t}</span></li>'
                        for sub, d, t in tasks)
        dcards.append(f"""<article class="card donecard"><div class="day">{c['day']}</div>
<h3>{inline(c['title'])}</h3><details><summary>{len(tasks)} done</summary><ul class="tasks">{items}</ul>{notes}</details></article>""")
    cols.append(f"""<section class="col col-done">
<header><h2>Done (last {DONE_DAYS} days)</h2><span class="n">{len(dcards)}</span></header>
{''.join(dcards) or '<p class="empty">No items</p>'}</section>""")
    names = names + ["Done"]

    stamp = datetime.fromtimestamp(os.path.getmtime(TODO)).strftime("%Y-%m-%d %H:%M")
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="30">
<title>TODO Board</title>
<style>
:root {{
  --bg:#f5f5f2; --col:#ebebe6; --card:#fff; --text:#1d1d1b; --muted:#6b6b66;
  --line:#d9d9d3; --accent:#2f6fde; --active:#2f6fde; --backlog:#8a8a84; --blocked:#c8452f;
  --done:#2e8b57; --code:#f0f0ec;
}}
@media (prefers-color-scheme: dark) {{
  :root {{ --bg:#161615; --col:#1f1f1d; --card:#2a2a28; --text:#ececea; --muted:#9a9a94;
    --line:#3a3a37; --accent:#6a9cf0; --active:#6a9cf0; --backlog:#8a8a84; --blocked:#e0735f;
    --done:#5cbf85; --code:#343431; }}
}}
* {{ box-sizing:border-box; }}
body {{ margin:0; background:var(--bg); color:var(--text);
  font:14px/1.45 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }}
.top {{ display:flex; justify-content:space-between; align-items:baseline; padding:20px 24px 8px; }}
.top h1 {{ font-size:20px; margin:0; }}
.top span {{ color:var(--muted); font-size:12px; }}
.board {{ display:grid; grid-template-columns:repeat({len(names)}, minmax(280px, 1fr)); gap:16px;
  padding:12px 24px 32px; align-items:start; }}
@media (max-width: 800px) {{ .board {{ grid-template-columns:1fr; padding:12px 16px; }} .top {{ padding:16px 16px 4px; }} }}
.col {{ background:var(--col); border-radius:10px; padding:12px; border-top:4px solid var(--backlog); }}
.col-active {{ border-top-color:var(--active); }} .col-blocked {{ border-top-color:var(--blocked); }}
.col header {{ display:flex; justify-content:space-between; align-items:center; margin:0 4px 10px; }}
.col h2 {{ font-size:13px; text-transform:uppercase; letter-spacing:.06em; margin:0; }}
.n {{ color:var(--muted); font-size:12px; }}
.card {{ background:var(--card); border:1px solid var(--line); border-radius:8px; padding:12px 14px; margin-bottom:10px; }}
.card h3 {{ font-size:15px; margin:0 0 8px; }}
.progress {{ height:4px; background:var(--line); border-radius:2px; overflow:hidden; }}
.progress div {{ height:100%; background:var(--done); }}
.count {{ color:var(--muted); font-size:11px; margin:4px 0 6px; }}
ul {{ margin:4px 0; padding-left:18px; }}
.tasks {{ list-style:none; padding:0; }}
.tasks li {{ display:flex; gap:8px; padding:3px 0; }}
.tasks li.sub {{ padding-left:22px; }}
.box {{ flex:none; width:15px; height:15px; margin-top:2px; border:1.5px solid var(--muted); border-radius:3px;
  font-size:11px; line-height:12px; text-align:center; color:#fff; }}
.tasks li.done .box {{ background:var(--done); border-color:var(--done); }}
.tasks li.done > span:last-child {{ color:var(--muted); text-decoration:line-through; }}
li.sub {{ margin-left:14px; }}
details {{ margin-top:8px; border-top:1px solid var(--line); padding-top:6px; }}
summary {{ cursor:pointer; color:var(--muted); font-size:12px; }}
details p {{ margin:6px 0; }}
a {{ color:var(--accent); word-break:break-all; }}
code {{ background:var(--code); padding:1px 4px; border-radius:3px; font-size:12px; }}
pre {{ background:var(--code); padding:8px; border-radius:6px; font-size:12px; overflow-x:auto; }}
.tags {{ display:flex; flex-wrap:wrap; gap:4px; margin-top:8px; }}
.tag {{ font-size:11px; color:var(--muted); border:1px solid var(--line); border-radius:10px; padding:0 7px; }}
.sess code {{ word-break:break-all; font-size:11px; }}
.sessions {{ padding:4px 24px 0; }}
.sessions h2, .changes h2 {{ font-size:13px; text-transform:uppercase; letter-spacing:.06em; margin:8px 0; }}
table.sess {{ width:100%; border-collapse:collapse; background:var(--card); border:1px solid var(--line); border-radius:8px; font-size:13px; }}
table.sess td {{ padding:5px 10px; border-bottom:1px solid var(--line); vertical-align:top; }}
table.sess td.m {{ color:var(--muted); font-size:12px; white-space:nowrap; }}
table.sess td:first-child {{ width:12px; padding-top:9px; }}
table.sess .dot {{ display:inline-block; }}
table.sess details {{ border:none; margin:0; padding:0; }}
table.sess summary {{ color:var(--muted); font-size:12px; cursor:pointer; }}
details.more > summary {{ color:var(--muted); font-size:12px; cursor:pointer; margin:6px 0; }}
@media (max-width: 800px) {{ table.sess td.m {{ white-space:normal; }} }}
.sess-grid {{ display:grid; grid-template-columns:repeat(auto-fill, minmax(300px, 1fr)); gap:10px; }}
.sess-card {{ background:var(--card); border:1px solid var(--line); border-radius:8px; padding:10px 12px; }}
.sess-head {{ display:flex; gap:8px; align-items:center; }}
.dot {{ width:9px; height:9px; border-radius:50%; background:var(--backlog); flex:none; }}
.st-active .dot {{ background:var(--done); }} .st-idle .dot {{ background:#d9a13b; }}
.sess-meta {{ color:var(--muted); font-size:12px; margin-top:3px; }}
.pending {{ color:var(--blocked); }}
code.resume {{ display:block; margin-top:6px; font-size:11px; word-break:break-all; user-select:all; }}
.upd {{ color:var(--muted); font-size:11px; margin:-4px 0 6px; }}
.changes {{ padding:0 24px 32px; }}
.changes ul {{ list-style:none; padding:0; background:var(--card); border:1px solid var(--line); border-radius:8px; }}
.changes li {{ padding:6px 12px; border-bottom:1px solid var(--line); font-size:13px; }}
.changes li:last-child {{ border-bottom:none; }}
.when {{ color:var(--muted); font-size:12px; margin-right:6px; }}
.src {{ font-size:11px; border-radius:8px; padding:0 6px; margin-right:4px; border:1px solid var(--line); }}
.src-auto {{ color:var(--accent); border-color:var(--accent); }}
.who {{ color:var(--muted); font-size:12px; }}
@media (max-width: 800px) {{ .sessions, .changes {{ padding-left:16px; padding-right:16px; }} }}
.col-done {{ border-top-color:var(--done); }}
.donecard h3 {{ color:var(--muted); font-size:14px; margin-bottom:2px; }}
.day {{ font-size:11px; color:var(--muted); }}
.empty {{ color:var(--muted); font-style:italic; margin:4px; }}
</style></head>
<body>
<div class="top"><h1>TODO Board</h1><span>TODO.md changed {stamp} · page reloads every 30 s</span></div>
<section class="sessions"><h2>Sessions (last 3 days)</h2>{strip}</section>
<main class="board">{''.join(cols)}</main>
<section class="changes"><h2>Recent changes</h2><ul>{changes}</ul></section>
</body></html>
"""


def main():
    if not os.path.isfile(TODO):
        return
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(render(parse()))
    # Daily snapshot (last state of each day) for daily.py to compare with.
    os.makedirs(C.HISTORY, exist_ok=True)
    shutil.copyfile(TODO, os.path.join(C.HISTORY, datetime.now().strftime("%Y-%m-%d") + ".md"))
    if "--open" in sys.argv:
        import webbrowser
        webbrowser.open("file://" + OUT)


if __name__ == "__main__":
    main()
