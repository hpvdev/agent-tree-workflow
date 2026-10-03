import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SOURCE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SOURCE / "templates"))
spec = importlib.util.spec_from_file_location("monitor", SOURCE / "templates/monitor.py")
monitor = importlib.util.module_from_spec(spec)
spec.loader.exec_module(monitor)


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "project with spaces"
        self.root.mkdir()

    def cli(self, action, *flags, success=True):
        result = subprocess.run([sys.executable, str(SOURCE / "install.py"), action,
                                 "--project", str(self.root), *flags], capture_output=True, text=True)
        self.assertEqual(result.returncode == 0, success, result.stdout + result.stderr)
        return result

    def test_install_reinstall_uninstall_preserves_existing_files(self):
        original = b"# Existing rules\r\nKeep this.\r\n"
        (self.root / "AGENTS.md").write_bytes(original)
        (self.root / ".codex").mkdir()
        config = self.root / ".codex/config.toml"
        config.write_text('model = "existing-model"\n')
        self.cli("install")
        first = (self.root / "AGENTS.md").read_bytes()
        self.cli("install")
        self.assertEqual(first, (self.root / "AGENTS.md").read_bytes())
        (self.root / "AGENTS.md").write_bytes(first + b"\nLater project note.\n")
        self.cli("uninstall")
        self.assertEqual((self.root / "AGENTS.md").read_bytes(), original + b"\nLater project note.\n")
        self.assertEqual(config.read_text(), 'model = "existing-model"\n')

    def test_model_changes_update_roles_and_launcher(self):
        self.cli("install", "--main-effort", "low")
        self.cli("configure", "--main-model", "future-main", "--worker-model", "future-worker",
                 "--worker-effort", "high", "--max-agents", "2")
        settings = json.loads((self.root / ".agent-tree/settings.json").read_text())
        self.assertEqual(settings["main_model"], "future-main")
        self.assertEqual(settings["main_effort"], "low")
        self.assertEqual(settings["max_agents"], 2)
        role = (self.root / ".codex/agents/agent_tree_worker.toml").read_text()
        self.assertIn('model = "future-worker"', role)
        self.assertIn('model_reasoning_effort = "high"', role)
        result = subprocess.run([sys.executable, str(self.root / ".agent-tree/run.py"),
                                 "--watch", "--print-command", "Do a task"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("future-main", result.stdout)
        self.assertIn("exec --json", result.stdout)
        self.assertIn("--approve-for-me", result.stdout)
        self.assertNotIn("bypass", result.stdout)
        self.cli("uninstall")
        self.assertFalse((self.root / "AGENTS.md").exists())

    def test_collision_and_symlink_do_not_mutate_project(self):
        (self.root / ".codex/agents").mkdir(parents=True)
        role = self.root / ".codex/agents/agent_tree_worker.toml"
        role.write_text("existing role")
        self.cli("install", success=False)
        self.assertFalse((self.root / "AGENTS.md").exists())
        self.assertFalse((self.root / ".agent-tree").exists())
        self.assertEqual(role.read_text(), "existing role")
        role.unlink()
        outside = Path(self.temp.name) / "outside"
        outside.write_text("outside")
        (self.root / "AGENTS.md").symlink_to(outside)
        self.cli("install", success=False)
        self.assertEqual(outside.read_text(), "outside")

    def test_uninstall_refuses_modified_owned_file(self):
        self.cli("install")
        path = self.root / ".codex/agents/agent_tree_worker.toml"
        path.write_text(path.read_text() + "# manual edit\n")
        self.cli("uninstall", success=False)
        self.assertTrue((self.root / "AGENTS.md").exists())
        self.assertTrue(path.exists())

    def test_upgrade_preserves_models_and_logs(self):
        self.cli("install")
        self.cli("configure", "--main-model", "my-next-model", "--jev-confidence", "0.92")
        logs = self.root / ".agent-tree/logs"
        logs.mkdir()
        (logs / "keep.jsonl").write_text("keep this log\n")
        self.cli("upgrade")
        saved = json.loads((self.root / ".agent-tree/settings.json").read_text())
        self.assertEqual(saved["main_model"], "my-next-model")
        self.assertEqual(saved["jev"]["confidence"], .92)
        self.assertEqual((logs / "keep.jsonl").read_text(), "keep this log\n")
        self.assertEqual((self.root / "AGENTS.md").read_text().count("<!-- agent-tree:start -->"), 1)

    def test_hooks_merge_preserves_existing_and_later_user_hooks(self):
        (self.root / ".codex").mkdir()
        path = self.root / ".codex/hooks.json"
        existing = {"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "echo original"}]}]}}
        original = json.dumps(existing)
        path.write_text(original)
        self.cli("install")
        self.assertEqual(len(json.loads(path.read_text())["hooks"]["Stop"]), 2)
        self.cli("uninstall")
        self.assertEqual(path.read_text(), original)
        self.cli("install")
        value = json.loads(path.read_text())
        added = {"hooks": [{"type": "command", "command": "echo later"}]}
        value["hooks"]["Stop"].append(added)
        path.write_text(json.dumps(value))
        self.cli("upgrade")
        self.cli("uninstall")
        self.assertEqual(json.loads(path.read_text())["hooks"]["Stop"], existing["hooks"]["Stop"] + [added])

    def test_event_monitor_reports_real_states_and_failure(self):
        view = monitor.Monitor()
        with contextlib.redirect_stdout(io.StringIO()) as output:
            view.accept({"type": "turn.started"})
            view.accept({"type": "item.completed", "item": {"type": "collab_agent_tool_call", "tool": "spawn_agent",
                         "receiver_thread_ids": ["child-1"], "agents_states": {"child-1": {"status": "running"}}}})
            view.accept({"type": "item.completed", "item": {"type": "command_execution", "command": "pytest", "exit_code": 1}})
            view.accept({"type": "turn.failed"})
        self.assertEqual(view.agents, {"child-1": "running"})
        self.assertTrue(view.failed)
        self.assertFalse(view.completed)
        self.assertIn("exit=1", output.getvalue())

    def test_trace_saves_real_subprocess_stream_and_replay(self):
        self.cli("install")
        events = [{"type": "turn.started"}, {"type": "item.completed", "item": {"type": "agent_message", "text": "Done"}},
                  {"type": "turn.completed", "usage": {"output_tokens": 3}}]
        script = "import json; events=" + repr(events) + "; [print(json.dumps(e),flush=True) for e in events]"
        emitter = self.root / "emit.py"
        emitter.write_text(script)
        with contextlib.redirect_stdout(io.StringIO()):
            status = monitor.trace([sys.executable, str(emitter), "test request"], self.root, {})
        self.assertEqual(status, 2)  # A successful Codex turn cannot fake missing Astra checkpoints.
        paths = list((self.root / ".agent-tree/logs").glob("*/codex.jsonl"))
        self.assertEqual(len(paths), 1)
        self.assertEqual([json.loads(line) for line in paths[0].read_text().splitlines()], events)
        with contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(monitor.replay(paths[0]), 0)
        self.assertIn("Done", output.getvalue())
        self.cli("uninstall")
        self.assertTrue(paths[0].exists())


if __name__ == "__main__":
    unittest.main()
