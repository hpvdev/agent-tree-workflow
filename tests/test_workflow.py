import contextlib
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SOURCE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SOURCE / "templates"))
import launcher


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
                                 "--print-command", "Do a task"], capture_output=True, text=True)
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
        legacy = ("Xem Agent Tree.command", ".agent-tree/monitor.py", ".agent-tree/watch.py", ".agent-tree/display.py")
        manifest_path = self.root / ".agent-tree/manifest.json"
        manifest = json.loads(manifest_path.read_text())
        for name in legacy:
            content = b"legacy Watch file\n"
            (self.root / name).write_bytes(content)
            manifest["files"][name] = hashlib.sha256(content).hexdigest()
        manifest_path.write_text(json.dumps(manifest))
        logs = self.root / ".agent-tree/logs"
        logs.mkdir()
        (logs / "keep.jsonl").write_text("keep this log\n")
        self.cli("upgrade")
        saved = json.loads((self.root / ".agent-tree/settings.json").read_text())
        self.assertEqual(saved["main_model"], "my-next-model")
        self.assertEqual(saved["jev"]["confidence"], .92)
        self.assertEqual((logs / "keep.jsonl").read_text(), "keep this log\n")
        self.assertEqual((self.root / "AGENTS.md").read_text().count("<!-- agent-tree:start -->"), 1)
        self.assertTrue((self.root / ".agent-tree/launcher.py").exists())
        self.assertTrue(all(not (self.root / name).exists() for name in legacy))

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

    def test_launcher_saves_real_subprocess_stream_and_retro(self):
        self.cli("install")
        events = [{"type": "turn.started"}, {"type": "item.completed", "item": {"type": "agent_message", "text": "Done"}},
                  {"type": "turn.completed", "usage": {"output_tokens": 3}}]
        script = "import json; events=" + repr(events) + "; [print(json.dumps(e),flush=True) for e in events]"
        emitter = self.root / "emit.py"
        emitter.write_text(script)
        with contextlib.redirect_stdout(io.StringIO()) as output:
            status = launcher.trace([sys.executable, str(emitter), "test request"], self.root)
        self.assertEqual(status, 2)  # A successful Codex turn cannot fake missing Astra checkpoints.
        paths = list((self.root / ".agent-tree/logs").glob("*/codex.jsonl"))
        self.assertEqual(len(paths), 1)
        self.assertEqual([json.loads(line) for line in paths[0].read_text().splitlines()], events)
        self.assertIn("Done", output.getvalue())
        self.assertFalse(json.loads((paths[0].parent / "retro.json").read_text())["workflow_passed"])
        self.cli("uninstall")
        self.assertTrue(paths[0].exists())


if __name__ == "__main__":
    unittest.main()
