import contextlib
from datetime import datetime, timezone
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SOURCE / "templates"))
from runtime import Journal
from observer import Observer
from control import classify, fork, dispatch, failure, request_checkpoint, complete_checkpoint, finish
from install import JEV_DEFAULTS


class ForkTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        (self.root / ".agent-tree").mkdir()
        (self.root / ".agent-tree/settings.json").write_text(json.dumps({"jev": JEV_DEFAULTS, "astra_model": "gpt-6-astra"}))
        (self.root / "impl.py").write_text("def example(): return 1\n")
        (self.root / "README.md").write_text("Introduction\n")
        self.journal = Journal(self.root, "test")
        self.addCleanup(self.journal.close)
        self.journal.put("checkpoint:before_plan", {"status": "completed"})
        self.request = {"kind": "which_file", "state": "Find the implementation", "question": "Which candidate implements the behavior?",
                        "non_sensitive": True, "options": {
                            "impl": {"description": "implementation", "action": {"type": "read_file", "path": "impl.py"}},
                            "docs": {"description": "documentation", "action": {"type": "read_file", "path": "README.md"}}}}

    def response(self, probabilities, confidence):
        return subprocess.CompletedProcess([], 0, json.dumps({"answers": {"route": {"type": "choice",
            "choice": max(probabilities, key=probabilities.get), "probabilities": probabilities, "confidence": confidence}}, "model": "jev-test"}), "")

    def test_sharp_dispatches_once_split_waits_for_sol(self):
        with patch("control.subprocess.run", return_value=self.response({"impl": .97, "docs": .02, "sol": .01}, .95)):
            result = fork(self.journal, self.request)
        self.assertEqual(result["actor"], "jev")
        self.assertIn("def example", result["result"]["content"])
        with self.assertRaises(ValueError):
            dispatch(self.journal, result["id"], "impl", "sol")
        with patch("control.subprocess.run", return_value=self.response({"impl": .49, "docs": .48, "sol": .03}, .1)):
            result = fork(self.journal, self.request)
        self.assertEqual(result["route"], "split")
        self.assertNotIn("result", result)
        resolved = dispatch(self.journal, result["id"], "docs", "sol")
        self.assertEqual(resolved["result"]["content"], "Introduction\n")

    def test_missing_jev_and_invalid_probability_escalate(self):
        with patch("control.subprocess.run", side_effect=FileNotFoundError()):
            result = fork(self.journal, self.request)
        self.assertEqual(result["route"], "split")
        self.assertNotIn("probability", result)
        dispatch(self.journal, result["id"], "stop", "sol")
        with self.assertRaises(ValueError):
            classify({"type": "choice", "probabilities": {"x": float("nan"), "sol": 0}, "confidence": 1}, ["x", "sol"], JEV_DEFAULTS)

    def test_retry_budget_and_repeat_checkpoint(self):
        observed = failure(self.journal, "same failure")
        req = {**self.request, "kind": "retry_or_stop", "failure_key": observed["failure_key"]}
        with patch("control.subprocess.run", return_value=self.response({"impl": .99, "docs": .005, "sol": .005}, .99)):
            fork(self.journal, req)
            self.assertEqual(fork(self.journal, req)["route"], "stop")
        repeated = failure(self.journal, "same failure")
        self.assertEqual(repeated["checkpoint"]["name"], "error_repeats")
        self.assertEqual(fork(self.journal, req)["route"], "astra")

    def test_project_boundary_and_non_sensitive_gate(self):
        self.request["non_sensitive"] = False
        with self.assertRaises(ValueError):
            fork(self.journal, self.request)
        self.request["non_sensitive"] = True
        self.request["options"]["impl"]["action"]["path"] = "../outside.txt"
        with self.assertRaises(ValueError):
            fork(self.journal, self.request)

    def test_native_metadata_proves_fresh_astra_review(self):
        self.journal.put("root_thread", "main-id")
        checkpoint = request_checkpoint(self.journal, "before_done")
        with self.assertRaises(ValueError):
            complete_checkpoint(self.journal, "before_done", "fake")
        sessions = self.root / "sessions"
        folder = sessions / datetime.now(timezone.utc).strftime("%Y/%m/%d")
        folder.mkdir(parents=True)
        records = [
            {"type": "session_meta", "payload": {"id": "review-id", "cwd": str(self.root), "agent_role": "agent_tree_astra",
             "source": {"subagent": {"thread_spawn": {"parent_thread_id": "main-id", "agent_path": "/root/reviewer"}}}}},
            {"type": "turn_context", "payload": {"model": "gpt-6-astra"}},
            {"type": "event_msg", "payload": {"type": "task_started"}},
            {"type": "event_msg", "payload": {"type": "task_complete"}}]
        timestamp = datetime.now(timezone.utc).isoformat()
        records[0]["payload"]["timestamp"] = timestamp
        for record in records:
            record["timestamp"] = timestamp
        records.insert(1, {"timestamp": "2000-01-01T00:00:00Z", "type": "turn_context", "payload": {"model": "inherited-main"}})
        records.insert(2, {"timestamp": "2000-01-01T00:00:00Z", "type": "event_msg", "payload": {"type": "token_count", "info": {"total_token_usage": {"input_tokens": 999}}}})
        file = folder / "rollout.jsonl"
        file.write_text("\n".join(map(json.dumps, records)) + "\n")
        observer = Observer(self.journal, sessions)
        observer.poll()
        self.assertFalse(any(e.get("model") == "inherited-main" or e["type"] == "agent.usage" for e in self.journal.events()))
        complete_checkpoint(self.journal, "before_done", "/root/reviewer")
        self.assertTrue(finish(self.journal)["passed"])
        count = len(self.journal.events())
        observer.poll()
        self.assertEqual(count, len(self.journal.events()))
        request_checkpoint(self.journal, "before_done")
        with self.assertRaises(ValueError):
            complete_checkpoint(self.journal, "before_done", "review-id")


if __name__ == "__main__":
    unittest.main()
