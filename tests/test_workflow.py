import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SOURCE = Path(__file__).resolve().parents[1]


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

    def test_install_is_explicit_only_and_preserves_project_files(self):
        agents = self.root / "AGENTS.md"
        original = b"# Existing rules\r\nKeep this.\r\n"
        agents.write_bytes(original)
        (self.root / ".codex").mkdir()
        hooks = self.root / ".codex/hooks.json"
        hooks.write_text('{"hooks":{"Stop":[]}}')
        config = self.root / ".codex/config.toml"
        config.write_text('model = "existing-model"\n')
        self.cli("install")
        self.cli("install")
        self.assertEqual(agents.read_bytes(), original)
        self.assertEqual(hooks.read_text(), '{"hooks":{"Stop":[]}}')
        self.assertEqual(config.read_text(), 'model = "existing-model"\n')
        skill = self.root / ".codex/skills/agent-tree/SKILL.md"
        self.assertTrue(skill.is_file())
        policy = (self.root / ".codex/skills/agent-tree/agents/openai.yaml").read_text()
        self.assertIn("allow_implicit_invocation: false", policy)
        self.cli("uninstall")
        self.assertFalse(skill.exists())
        self.assertEqual(agents.read_bytes(), original)
        self.assertEqual(hooks.read_text(), '{"hooks":{"Stop":[]}}')

    def test_model_changes_update_roles(self):
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

    def test_collision_and_symlink_do_not_mutate_project(self):
        role = self.root / ".codex/agents/agent_tree_worker.toml"
        role.parent.mkdir(parents=True)
        role.write_text("existing role")
        self.cli("install", success=False)
        self.assertEqual(role.read_text(), "existing role")
        self.assertFalse((self.root / ".agent-tree").exists())
        role.unlink()
        outside = Path(self.temp.name) / "outside"
        outside.mkdir()
        (self.root / ".codex/skills").symlink_to(outside)
        self.cli("install", success=False)
        self.assertEqual(list(outside.iterdir()), [])

    def test_uninstall_refuses_modified_owned_file(self):
        self.cli("install")
        path = self.root / ".codex/skills/agent-tree/SKILL.md"
        path.write_text(path.read_text() + "\nmanual edit\n")
        self.cli("uninstall", success=False)
        self.assertTrue(path.exists())

    def test_upgrade_removes_legacy_hooks_and_agent_rules_but_keeps_logs(self):
        self.cli("install")
        self.cli("configure", "--main-model", "my-next-model", "--jev-confidence", "0.92")
        manifest_path = self.root / ".agent-tree/manifest.json"
        manifest = json.loads(manifest_path.read_text())
        legacy = ("Xem Agent Tree.command", ".agent-tree/monitor.py", ".agent-tree/watch.py", ".agent-tree/display.py", ".agent-tree/hooks.py")
        for name in legacy:
            content = b"legacy managed file\n"
            (self.root / name).write_bytes(content)
            manifest["files"][name] = hashlib.sha256(content).hexdigest()
        block = "<!-- agent-tree:start -->\nold rules\n<!-- agent-tree:end -->\n"
        (self.root / "AGENTS.md").write_text(block)
        group = {"hooks": [{"type": "command", "command": "echo old"}]}
        hooks = {"hooks": {"Stop": [group]}}
        (self.root / ".codex/hooks.json").write_text(json.dumps(hooks))
        manifest.update(version=3, agents_existed=False, block=block, hooks_original=None, hook_groups={"Stop": group})
        manifest_path.write_text(json.dumps(manifest))
        logs = self.root / ".agent-tree/logs"
        logs.mkdir()
        (logs / "keep.jsonl").write_text("keep this log\n")
        self.cli("upgrade")
        saved = json.loads((self.root / ".agent-tree/settings.json").read_text())
        self.assertEqual(saved["main_model"], "my-next-model")
        self.assertEqual(saved["jev"]["confidence"], .92)
        self.assertEqual((logs / "keep.jsonl").read_text(), "keep this log\n")
        self.assertFalse((self.root / "AGENTS.md").exists())
        self.assertFalse((self.root / ".codex/hooks.json").exists())
        self.assertTrue(all(not (self.root / name).exists() for name in legacy))
        self.assertTrue((self.root / ".codex/skills/agent-tree/SKILL.md").exists())

    def test_skill_run_begins_only_when_called_and_writes_retro(self):
        self.cli("install")
        script = self.root / ".agent-tree/control.py"
        environment = dict(os.environ, CODEX_THREAD_ID="test-thread")
        begin = subprocess.run([sys.executable, str(script), "begin"], cwd=self.root, env=environment,
                               capture_output=True, text=True)
        self.assertEqual(begin.returncode, 0, begin.stderr + begin.stdout)
        run_id = json.loads(begin.stdout)["run_id"]
        self.assertFalse((self.root / ".agent-tree/logs" / run_id / "retro.json").exists())
        finish = subprocess.run([sys.executable, str(script), "--run-id", run_id, "finish"], cwd=self.root,
                                env=environment, capture_output=True, text=True)
        self.assertEqual(finish.returncode, 2)
        report = json.loads((self.root / ".agent-tree/logs" / run_id / "retro.json").read_text())
        self.assertFalse(report["workflow_passed"])
        self.assertEqual(report["jev_forks"], 0)


if __name__ == "__main__":
    unittest.main()
