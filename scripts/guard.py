#!/usr/bin/env python3
"""PreToolUse hook (Write|Edit): send Claude to the `todo` command instead of editing TODO files."""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import config as C

try:
    path = (json.load(sys.stdin).get("tool_input") or {}).get("file_path") or ""
except Exception:
    sys.exit(0)
if path and os.path.realpath(path) in (os.path.realpath(C.MD), os.path.realpath(C.DATA)):
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse", "permissionDecision": "deny",
        "permissionDecisionReason": f"TODO.md is generated from TODO.json. Use the todo command `{C.todo_cmd()}` "
        "(todo show --all | done tN --note ... | add sN \"text\" | note ID \"text\" | edit ID \"text\" | move sN GROUP | new GROUP \"title\")."}}))
