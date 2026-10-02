# claude-todo-tracker

[![test](https://github.com/sabrieker/claude-todo-tracker/actions/workflows/test.yml/badge.svg)](https://github.com/sabrieker/claude-todo-tracker/actions/workflows/test.yml)

A Claude Code plugin that keeps one TODO list for all your projects. The list updates itself from your Claude Code sessions.

- **One list, many projects.** Each section is linked to project folders. A session sees the open items of its own folder at start. Other sections show as titles only.
- **Updates itself.** A background worker reads what a session did and ticks, adds or notes items. You do not have to remember to update the list.
- **Short commands.** Claude changes the list with `todo done t12`, not by editing a Markdown file.
- **Kanban board.** `TODO.html` shows Active, Backlog, Blocked and Done columns, your recent sessions, and a feed of recent changes.
- **Standup and plan.** `/daily` writes what you did today, the plan for tomorrow, and blockers. `/today` writes the plan for this morning.
- **Long-open sessions.** When you come back to a session after a break, the session gets the current list, and the work before the break is synced.

## Install

In Claude Code:

```
/plugin marketplace add sabrieker/claude-todo-tracker
/plugin install todo-tracker@claude-todo-tracker
```

Start a new session after the install. Hooks load at session start.

Requirements:
- macOS, Linux or Windows.
- Python 3.9 or newer. The launcher finds it as `python3`, `python` or `py -3`.
- On Windows: Git for Windows. Claude Code runs hooks and its Bash tool in Git Bash. `bin/todo.cmd` also works from cmd.exe and PowerShell.
- The `claude` CLI on your PATH. The sync worker uses it.

## Commands

The skills:

| Command | What it does |
|---|---|
| `/todo-tracker:todo` | Sync this session to the list now, in the background |
| `/todo-tracker:todo show` | Show the open items for this folder |
| `/todo-tracker:todo undo` | Undo the last automatic sync of this session |
| `/todo-tracker:daily [YYYY-MM-DD \| yesterday]` | Write the daily standup report |
| `/todo-tracker:today` | Write the plan for today |

The `todo` command (Claude uses it from the Bash tool; IDs: `sN` is a section, `tN` is an item):

```
todo show [--cwd DIR] [--all] [--brief]
todo new Active "Payments API" --projects ~/code/payments
todo add s1 "Add retry to the webhook client"
todo add t2 "Sub-task"
todo note t2 "PR #41 opened."
todo done t2 t3 --note "Merged in PR #41."
todo edit t2 "New text"
todo move s1 Blocked --waits "security review"
todo link s1 ~/code/payments-worker
todo rm t4
todo sessions [--days N]
todo undo SESSION_ID
todo render
```

`todo` is on the PATH inside Claude Code only. In your own terminal, call `<plugin folder>/bin/todo` (or `bin\todo.cmd` on Windows), or link it:
`ln -s "<plugin folder>/bin/todo" ~/.local/bin/todo`.

The same launcher runs the helper scripts: `todo sync`, `todo daily`, `todo plan` and `todo hook <name>`.

## Files

All your data lives in one folder, `~/todo` by default:

| File | What it is |
|---|---|
| `TODO.json` | The data. The source of truth. |
| `TODO.md` | Generated from the JSON file. You can edit it by hand. The next `todo` call imports your edit. |
| `TODO.html` | The Kanban board. It reloads every 30 seconds. |
| `TODO-done.md` | Done items move here at once. Sessions never load this file, so the context stays small. |
| `daily/` | `/daily` reports and `/today` plans. |
| `.state/` | Locks, daily snapshots, undo snapshots and the sync log. |

A hook blocks Claude from editing `TODO.md` or `TODO.json` directly, and points it to the `todo` command.

## Settings

Set these in the `env` block of `~/.claude/settings.json`, so the hooks see them too:

```json
{ "env": { "TODO_HOME": "~/Desktop", "TODO_AUTO_SYNC": "1" } }
```

| Variable | Default | Meaning |
|---|---|---|
| `TODO_HOME` | `~/todo` | Folder for your data |
| `TODO_AUTO_SYNC` | `1` | `0` turns off the background sync worker |
| `TODO_SYNC_MODEL` | `claude-sonnet-5` | Model the sync worker uses |
| `TODO_GIT_AUTHOR` | `git config user.email` | Author filter for the commits in `/daily` |

## How the automatic sync works

1. The `Stop` hook runs after each Claude turn. It starts the worker in the background, at most once every 30 minutes per session. `SessionEnd` and a return after a break also start it.
2. The worker reads the new part of the session transcript: your prompts and Claude's answers. It skips tool output.
3. It sends that text and the open items to `claude -p` with no tools and no hooks. The model returns `todo` commands as JSON.
4. The worker checks each command and runs it. Each change is logged as `auto` with its session.
5. Before each sync it saves a snapshot, so `todo undo SESSION_ID` can revert it.

**Cost.** Each sync is one `claude -p` call, usually 10k to 20k input tokens. With a busy day of sessions, expect 30 to 40 calls. On a subscription this uses your usage limits. On an API key it costs money. Set `TODO_AUTO_SYNC=0` to turn it off and use `/todo-tracker:todo` by hand.

**Privacy.** The worker sends your session text to the same Claude account your Claude Code uses. Nothing goes anywhere else. All data stays in `TODO_HOME`.

## Hooks

| Event | Script | What it does |
|---|---|---|
| `SessionStart` | `session-start.py` | Gives Claude the open items for this folder |
| `UserPromptSubmit` | `heartbeat.py` | Records activity; after a break, gives Claude the current list and syncs the earlier work |
| `PreToolUse` (Write, Edit) | `guard.py` | Blocks direct edits of `TODO.md` and `TODO.json` |
| `Stop` | `stop.py` | Starts the sync worker in the background |
| `SessionEnd` | `stop.py --end` | Marks the session ended and syncs it |

## Tests

```
python -m unittest discover -s tests -v
```

GitHub Actions runs them on Linux, macOS and Windows, with Python 3.9 and 3.13.

## License

MIT
