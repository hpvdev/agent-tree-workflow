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
from control import classify, fork, dispatch, failure, request_checkpoint, complete_checkpoint, finish, native_event
from hooks import handle, routing_guard, controller_call
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

    def test_native_selection_requires_matching_real_call(self):
        request = {**self.request, "kind": "which_tool", "options": {
            "tests": {"description": "Run existing tests", "action": {"type": "native_tool", "tool": "Bash", "input": {"command": "python3 -m unittest"}}},
            "stop": {"description": "Stop this operation", "action": {"type": "stop"}}}}
        with patch("control.subprocess.run", return_value=self.response({"tests": .98, "stop": .01, "sol": .01}, .96)):
            result = fork(self.journal, request)
        self.assertEqual(result["status"], "awaiting_native")
        self.assertIn("decision:" + result["id"], finish(self.journal)["unresolved"])
        wrong = routing_guard(self.journal, "Bash", {"command": "echo unrelated"}, "call")
        self.assertEqual(wrong["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertEqual(routing_guard(self.journal, "Bash", result["call"]["input"], "call"), {})
        self.assertEqual(routing_guard(self.journal, "Bash", result["call"]["input"], "call"), {})  # replay
        self.assertIsNone(native_event(self.journal, "Bash", result["call"]["input"], "wrong-call", "post"))
        self.assertEqual(native_event(self.journal, "Bash", result["call"]["input"], "call", "post"), result["id"])
        self.assertIsNone(native_event(self.journal, "Bash", result["call"]["input"], "call-2", "pre"))
        self.assertEqual(finish(self.journal)["unresolved"], [])

    def test_agent_selection_split_and_cancellation(self):
        request = {**self.request, "kind": "which_agent", "options": {
            role: {"description": role, "action": {"type": "spawn_agent", "role": role, "tool": "spawn_agent",
                    "input": {"agent_type": "agent_tree_" + role, "message": "A public example task"}}}
            for role in ("worker", "explorer", "researcher")}}
        denied = routing_guard(self.journal, "spawn_agent", request["options"]["worker"]["action"]["input"], "spawn")
        self.assertEqual(denied["hookSpecificOutput"]["permissionDecision"], "deny")
        with patch("control.subprocess.run", return_value=self.response({"worker": .4, "explorer": .3, "researcher": .2, "sol": .1}, .2)):
            result = fork(self.journal, request)
        self.assertEqual(result["route"], "split")
        result = dispatch(self.journal, result["id"], "explorer", "sol")
        self.assertEqual(result["call"]["input"]["agent_type"], "agent_tree_explorer")
        self.assertEqual(result["actor"], "sol")
        dispatch(self.journal, result["id"], "stop", "sol")
        self.assertEqual(finish(self.journal)["unresolved"], [])

    def test_controller_escape_does_not_allow_shell_chains(self):
        valid = "python3 .agent-tree/control.py --run-id test status"
        self.assertTrue(controller_call("Bash", {"command": valid}, "test"))
        for cmd in (valid + "; touch other", valid + " && echo bad", valid.replace("test", "other"), "python3 -c 'print(1)'"):
            self.assertFalse(controller_call("Bash", {"command": cmd}, "test"))

    def test_read_only_inspection_does_not_repeat_final_astra_review(self):
        self.journal.put("checkpoint:before_done", {"status": "completed", "agent_id": "review"})
        self.assertEqual(routing_guard(self.journal, "Bash", {"command": "nl -ba impl.py | sed -n '1,20p'"}, "read"), {})
        self.assertTrue(finish(self.journal)["passed"])
        self.assertEqual(self.journal.get("checkpoint:before_done")["status"], "completed")
        for command in ("sed -i '' 's/1/2/' impl.py", "rg example impl.py > result.txt", "python3 change.py"):
            self.assertEqual(routing_guard(self.journal, "Bash", {"command": command}, "change"), {})
            self.assertIsNone(self.journal.get("checkpoint:before_done"))
            self.journal.put("checkpoint:before_done", {"status": "completed", "agent_id": "review"})

    def test_hooks_turn_isolation_and_native_astra(self):
        base = {"cwd": str(self.root), "session_id": "parent", "model": "gpt-6-sol"}
        def hook(event, **values):
            return handle({**base, "hook_event_name": event, **values}, self.root)
        first = hook("UserPromptSubmit", turn_id="turn-1", prompt="not logged")
        with JournalContext(self.root, "sessions") as index:
            run = index.get("session:parent")["run_id"]
        with JournalContext(self.root, run) as journal:
            request_checkpoint(journal, "before_plan")
        hook("SubagentStart", agent_id="review", agent_type="agent_tree_astra", model="gpt-6-astra")
        hook("SubagentStop", agent_id="review", agent_type="agent_tree_astra", model="gpt-6-astra")
        with JournalContext(self.root, run) as journal:
            complete_checkpoint(journal, "before_plan", "review")
            self.assertNotIn("not logged", str(journal.events()))
        self.assertEqual(hook("PermissionRequest", tool_name="Bash", tool_input={"command": "private"}), {})
        self.assertEqual(hook("Stop")["decision"], "block")
        self.assertNotIn("decision", hook("Stop", stop_hook_active=True))
        second = hook("UserPromptSubmit", turn_id="turn-2")
        self.assertNotEqual(first, second)
        with JournalContext(self.root, "sessions") as index:
            next_run = index.get("session:parent")["run_id"]
        with JournalContext(self.root, next_run) as journal:
            self.assertIsNone(journal.get("checkpoint:before_plan"))
        # A late child completion belongs to its original run.
        hook("SubagentStop", agent_id="review", model="gpt-6-astra")
        with JournalContext(self.root, next_run) as journal:
            self.assertIsNone(journal.get("agent:review"))

    def test_stop_creates_one_retro_from_observed_events(self):
        base = {"cwd": str(self.root), "session_id": "retro-parent", "turn_id": "one"}
        handle({**base, "hook_event_name": "UserPromptSubmit"}, self.root)
        with JournalContext(self.root, "sessions") as index:
            run = index.get("session:retro-parent")["run_id"]
        with JournalContext(self.root, run) as journal:
            journal.put("checkpoint:before_plan", {"status": "completed"})
            journal.put("checkpoint:before_done", {"status": "completed"})
            journal.emit("agent.observed", id="review", role="agent_tree_astra")
            journal.emit("fork.started", kind="which_file")
            journal.emit("fork.decided", kind="which_file", route="split")
            journal.emit("checkpoint.invalidated", name="before_done")
            journal.emit("tool.activity", status="returned")
        self.assertEqual(handle({**base, "hook_event_name": "Stop"}, self.root), {})
        self.assertEqual(handle({**base, "hook_event_name": "Stop"}, self.root), {})
        with JournalContext(self.root, run) as journal:
            report = journal.get("retro")
            self.assertEqual(report["agents"]["astra"], 1)
            self.assertEqual(report["jev_forks"], 1)
            self.assertEqual(report["review_restarts"], 1)
            self.assertEqual(report["tool_hook_events"], 1)
            self.assertEqual(report["quality"], "not_measured")
            self.assertEqual(sum(event["type"] == "workflow.retro" for event in journal.events()), 1)
            self.assertEqual(json.loads((journal.directory / "retro.json").read_text()), report)

    def test_launcher_and_hooks_share_run_even_when_prompt_event_replays(self):
        base = {"cwd": str(self.root), "session_id": "launched-parent", "hook_event_name": "UserPromptSubmit", "turn_id": "one"}
        with patch.dict("os.environ", {"AGENT_TREE_RUN": "test"}):
            first = handle(base, self.root)
            self.assertEqual(handle(base, self.root), first)
            with JournalContext(self.root, "sessions") as index:
                self.assertEqual(index.get("session:launched-parent")["run_id"], "test")
            handle({**base, "turn_id": "two"}, self.root)
            with JournalContext(self.root, "sessions") as index:
                self.assertNotEqual(index.get("session:launched-parent")["run_id"], "test")

    def test_hooks_failure_dedup_and_repeat_gate(self):
        base = {"cwd": str(self.root), "session_id": "parent", "turn_id": "one"}
        handle({**base, "hook_event_name": "UserPromptSubmit"}, self.root)
        event = {**base, "hook_event_name": "PostToolUse", "tool_name": "Bash", "tool_input": {"command": "python3 -m unittest"},
                 "tool_use_id": "first", "tool_response": {"exit_code": 1}}
        handle(event, self.root)
        handle(event, self.root)
        handle({**event, "tool_use_id": "second"}, self.root)
        with JournalContext(self.root, "sessions") as index:
            run = index.get("session:parent")["run_id"]
        with JournalContext(self.root, run) as journal:
            errors = [e for e in journal.events() if e["type"] == "failure.observed"]
            self.assertEqual([e["count"] for e in errors], [1, 2])
            self.assertTrue(all(e["source"] == "native_hook" for e in errors))
            self.assertEqual(routing_guard(journal, "Bash", {"command": "retry"}, "third")["hookSpecificOutput"]["permissionDecision"], "deny")
            self.assertEqual(routing_guard(journal, "spawn_agent", {"agent_type": "agent_tree_astra"}, "review"), {})


@contextlib.contextmanager
def JournalContext(root, run):
    journal = Journal(root, run)
    try:
        yield journal
    finally:
        journal.close()


if __name__ == "__main__":
    unittest.main()
