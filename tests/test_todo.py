"""End-to-end tests for the todo scripts. No Claude call is made.

Run: python -m unittest discover -s tests -v
"""
import json, os, subprocess, sys, tempfile, unittest
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "scripts")


class TodoTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = os.path.join(self.tmp.name, "todo home")      # a space, on purpose
        self.proj = os.path.join(self.tmp.name, "Proj")
        os.makedirs(os.path.join(self.proj, "sub"))
        self.env = dict(os.environ, TODO_HOME=self.home, TODO_AUTO_SYNC="0", TODO_NO_BOARD="0")
        self.env.pop("CLAUDE_CODE_SESSION_ID", None)
        self.env.pop("PYTHONUTF8", None)        # prove the scripts set UTF-8 themselves

    def tearDown(self):
        self.tmp.cleanup()

    def run_py(self, script, *args, stdin=None, env=None, ok=True):
        r = subprocess.run([sys.executable, os.path.join(SCRIPTS, script)] + list(args),
                           input=stdin, capture_output=True, env=env or self.env,
                           cwd=self.proj, timeout=60)
        out, err = r.stdout.decode("utf-8"), r.stderr.decode("utf-8", "replace")
        if ok:
            self.assertEqual(r.returncode, 0, f"{script} {args}\nstdout: {out}\nstderr: {err}")
        return out

    def todo(self, *args, **kw):
        return self.run_py("todo.py", *args, **kw)

    def test_commands_and_files(self):
        self.assertIn("new section s1", self.todo("new", "Active", "Demo ✓ ünïcode", "--projects", self.proj))
        self.todo("add", "s1", "First task · with a dot")
        self.todo("add", "s1", "Second task")
        self.todo("add", "t2", "Sub-task")
        self.todo("note", "t3", "Started.")
        self.todo("edit", "t3", "Second task, renamed")
        out = self.todo("show", "--all")
        self.assertIn("Demo ✓ ünïcode", out)
        self.assertIn("First task · with a dot", out)
        self.todo("done", "t4", "--note", "Finished.")
        self.todo("done", "t2", "t3")
        for f in ("TODO.json", "TODO.md", "TODO.html", "TODO-done.md"):
            self.assertTrue(os.path.isfile(os.path.join(self.home, f)), f)
        done = open(os.path.join(self.home, "TODO-done.md"), encoding="utf-8").read()
        self.assertIn("Sub-task", done)
        self.assertEqual(json.load(open(os.path.join(self.home, "TODO.json"), encoding="utf-8"))["sections"], [])

    def test_hand_edit_is_imported(self):
        self.todo("new", "Backlog", "Edited by hand", "--projects", self.proj)
        self.todo("add", "s1", "Keep me")
        md = os.path.join(self.home, "TODO.md")
        text = open(md, encoding="utf-8").read().replace("- [ ] Keep me", "- [ ] Keep me\n- [ ] Added in the editor")
        open(md, "w", encoding="utf-8").write(text)
        out = self.todo("show", "--all")
        self.assertIn("t2 [ ] Keep me", out)        # the old ID stays
        self.assertIn("Added in the editor", out)

    def test_folder_links(self):
        self.todo("new", "Active", "Mine", "--projects", self.proj)
        self.todo("new", "Active", "Other", "--projects", os.path.join(self.tmp.name, "elsewhere"))
        out = self.todo("show", "--cwd", os.path.join(self.proj, "sub"))
        self.assertIn("[s1] Mine", out)
        self.assertIn("Other sections: [s2] Other", out)
        if os.name == "nt":                        # Git Bash style path and other case
            drive, rest = os.path.splitdrive(self.proj)
            bash = "/" + drive[0].lower() + rest.replace("\\", "/")
            self.assertIn("[s1] Mine", self.todo("show", "--cwd", bash))
            self.assertIn("[s1] Mine", self.todo("show", "--cwd", self.proj.upper()))

    def test_parallel_changes_do_not_lose_items(self):
        self.todo("new", "Active", "Busy", "--projects", self.proj)
        with ThreadPoolExecutor(8) as ex:
            list(ex.map(lambda i: self.todo("add", "s1", f"task {i}"), range(16)))
        out = self.todo("show", "--all")
        for i in range(16):
            self.assertIn(f"task {i}", out)

    def test_hooks(self):
        self.todo("new", "Active", "Hooked", "--projects", self.proj)
        out = self.run_py("session-start.py", stdin=json.dumps({"cwd": self.proj}).encode())
        self.assertIn("[s1] Hooked", out)
        deny = self.run_py("guard.py", stdin=json.dumps(
            {"tool_input": {"file_path": os.path.join(self.home, "TODO.md")}}).encode())
        self.assertEqual(json.loads(deny)["hookSpecificOutput"]["permissionDecision"], "deny")
        allow = self.run_py("guard.py", stdin=json.dumps(
            {"tool_input": {"file_path": os.path.join(self.proj, "x.md")}}).encode())
        self.assertEqual(allow.strip(), "")
        ev = json.dumps({"session_id": "sess-1", "cwd": self.proj, "prompt": "hello"}).encode()
        self.run_py("heartbeat.py", stdin=ev)
        self.assertIn("sess-1", self.todo("sessions"))
        self.run_py("stop.py", "--end", stdin=ev)
        db = json.load(open(os.path.join(self.home, "TODO.json"), encoding="utf-8"))
        self.assertIn("ended", db["sessions"]["sess-1"])

    def test_session_link_and_undo_guard(self):
        self.todo("new", "Active", "Linked", "--projects", self.proj)
        env = dict(self.env, CLAUDE_CODE_SESSION_ID="sess-2")
        self.todo("add", "s1", "from a session", env=env)
        self.assertIn("sections s1", self.todo("sessions"))
        self.todo("undo", "sess-2", ok=False)       # no automatic sync to undo

    def test_reports_run(self):
        self.todo("new", "Active", "Report", "--projects", self.proj)
        self.assertIn("Report file:", self.run_py("daily.py"))
        self.assertIn("Plan file:", self.run_py("plan.py"))
        out = self.run_py("todo-sync.py", "no-such-session", "--now")
        self.assertIn("no transcript", out)

    def test_native_path(self):
        sys.path.insert(0, SCRIPTS)
        import config
        if os.name == "nt":
            self.assertEqual(config.native_path("/c/Users/x"), "C:\\Users\\x")
        else:
            self.assertEqual(config.native_path("/c/Users/x"), "/c/Users/x")


if __name__ == "__main__":
    unittest.main()
