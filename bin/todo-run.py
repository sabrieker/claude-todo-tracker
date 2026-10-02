"""Entry point behind bin/todo and bin/todo.cmd.

  todo <command> ...        the TODO list (scripts/todo.py)
  todo sync|daily|plan ...  the sync worker, the /daily facts, the /today facts
  todo hook <name> ...      a hook script (session-start, heartbeat, guard, stop)
"""
import os, runpy, sys

SCRIPTS = os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))), "scripts")
sys.path.insert(0, SCRIPTS)
ALIAS = {"sync": "todo-sync", "daily": "daily", "plan": "plan"}
HOOKS = {"session-start", "heartbeat", "guard", "stop"}

args = sys.argv[1:]
if args[:1] == ["hook"] and len(args) > 1 and args[1] in HOOKS:
    name, rest = args[1], args[2:]
elif args[:1] and args[0] in ALIAS:
    name, rest = ALIAS[args[0]], args[1:]
else:
    name, rest = "todo", args
path = os.path.join(SCRIPTS, name + ".py")
sys.argv = [path] + rest
runpy.run_path(path, run_name="__main__")
