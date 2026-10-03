#!/usr/bin/env python3
"""Native project lifecycle hooks. No network calls and no approval grants."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shlex
import re
import sys
from runtime import Journal, ROOT
from control import failure, finish, native_event

EVENTS = ("SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse", "PermissionRequest",
          "SubagentStart", "SubagentStop", "Stop", "Interrupt", "SessionEnd")


def context(event, text):
    return {"hookSpecificOutput": {"hookEventName": event, "additionalContext": text}}


def deny(text):
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": text}}


def controller_call(tool, arguments, run):
    """Only a plain, canonical controller invocation can bypass a pending route."""
    if tool not in ("Bash", "exec_command", "shell_command") or not isinstance(arguments, dict):
        return False
    command = arguments.get("command", arguments.get("cmd"))
    if not isinstance(command, str):
        return False
    try:
        tokens = shlex.split(command)
    except ValueError:
        return False
    # Canonical shell quoting disallows substitutions, pipelines and appended commands.
    if command.strip() != shlex.join(tokens) or tokens[:4] != ["python3", ".agent-tree/control.py", "--run-id", run]:
        return False
    tail = tokens[4:]
    return (tail in (["status"], ["finish"]) or
            len(tail) == 3 and tail[0] == "fork" and tail[1] == "--json" or
            len(tail) == 3 and tail[0] == "resolve" or
            len(tail) == 2 and tail[0] == "failure" or
            len(tail) in (2, 4) and tail[0] == "checkpoint" and tail[1] in ("before_plan", "before_done", "error_repeats") and (len(tail) == 2 or tail[2] == "--agent-id"))


def routing_guard(journal, tool, arguments, call_id):
    if controller_call(tool, arguments, journal.run_id):
        return {}
    short = tool.split(".")[-1].split("__")[-1]
    # Deterministic coordination must remain possible while a branch is pending.
    if short in ("wait", "wait_agent", "wait_agents", "close_agent", "list_agents", "update_plan", "write_stdin"):
        return {}
    if short == "spawn_agent" and isinstance(arguments, dict) and arguments.get("agent_type") == "agent_tree_astra":
        if any((journal.get("checkpoint:" + name) or {}).get("status") == "pending" for name in ("before_plan", "error_repeats", "before_done")):
            return {}
        return deny("Astra chỉ được gọi cho checkpoint đang chờ; hãy request checkpoint trước.")
    repeated = journal.get("checkpoint:error_repeats")
    if repeated and repeated["status"] != "completed":
        return deny("Lỗi lặp lại: cần hoàn tất checkpoint Astra error_repeats trước khi tiếp tục thực thi.")
    if (journal.get("checkpoint:before_done") or {}).get("status") == "completed":
        journal.put("checkpoint:before_done", None)
        journal.emit("checkpoint.invalidated", name="before_done")
    if native_event(journal, tool, arguments, call_id, "pre"):
        return {}
    decisions = [json.loads(row[0]) for row in journal.db.execute("SELECT data FROM state WHERE key LIKE 'decision:%'")]
    waiting = [d["id"] for d in decisions if d["status"] in ("pending", "awaiting_native", "native_failed", "failed")]
    if waiting or short == "spawn_agent":
        journal.emit("routing.blocked", tool=tool, pending=waiting)
        return deny("Jev fork layer: cần thực thi đúng nhánh đã chọn hoặc resolve/cancel quyết định đang chờ. Spawn worker/explorer/researcher cần which_agent. Native hook tool=" + tool + ". Không đổi tool/input sau khi chọn; tạo fork mới nếu cần.")
    return {}  # Known deterministic work has no semantic fork to classify.


def handle(data, root=ROOT):
    event = data.get("hook_event_name")
    if event not in EVENTS:
        return {}
    cwd = Path(data.get("cwd", "")).resolve()
    root = Path(root).resolve()
    if cwd != root and root not in cwd.parents:
        return {}  # Never attach another project's session.
    session = str(data.get("session_id", ""))
    if not session:
        return {"systemMessage": "Agent Tree chưa nhận được session_id; chưa thể theo dõi phiên."}
    index = Journal(root, "sessions")
    journal = None
    try:
        mapping = index.get("session:" + session)
        if event == "SubagentStop" and data.get("agent_id"):
            mapping = index.get("session:" + str(data["agent_id"]), mapping)
        if event == "UserPromptSubmit":
            turn = str(data.get("turn_id") or "")
            if not turn:
                return {"systemMessage": "Agent Tree thiếu turn_id; không tự tái sử dụng checkpoint của lượt cũ."}
            run_id = "hook-" + hashlib.sha256((session + ":" + turn).encode()).hexdigest()[:24]
            if mapping and mapping.get("turn_id") == turn:
                run_id = mapping["run_id"]
            # Optional launcher and native hooks share one journal for its single turn.
            launch_run = os.environ.get("AGENT_TREE_RUN")
            if launch_run and re.fullmatch(r"[A-Za-z0-9_-]+", launch_run) and not mapping and (root / ".agent-tree/logs" / launch_run / "events.sqlite3").is_file():
                run_id = launch_run
            index.put("session:" + session, {"run_id": run_id, "role": "main", "root_session": session, "turn_id": turn})
            mapping = index.get("session:" + session)
        if not mapping:
            if event == "SessionStart":
                return context(event, "Agent Tree hooks are active in this project. Follow AGENTS.md. UserPromptSubmit will provide a separate run ID for each turn. Never open a nested CLI to activate the workflow.")
            # Child tools may identify the child session; map it using native transcript metadata.
            transcript = data.get("transcript_path")
            if transcript:
                try:
                    with Path(transcript).open() as file:
                        meta = json.loads(file.readline()).get("payload", {})
                    source = meta.get("source", {})
                    spawn = source.get("subagent", {}).get("thread_spawn", {}) if isinstance(source, dict) else {}
                    parent = index.get("session:" + str(spawn.get("parent_thread_id")), {})
                    if parent and Path(meta.get("cwd", "")).resolve() == root:
                        mapping = {**parent, "role": meta.get("agent_role") or spawn.get("agent_role") or "subagent"}
                        index.put("session:" + session, mapping)
                except (OSError, ValueError, TypeError, AttributeError):
                    pass
        if not mapping:
            return {}
        journal = Journal(root, mapping["run_id"])
        journal.put("root_thread", mapping["root_session"])
        journal.put("transport", "hooks")
        run = mapping["run_id"]
        role = mapping.get("role", "main")
        if event == "UserPromptSubmit":
            if not journal.get("initialized"):
                journal.put("initialized", True)
                journal.emit("session.turn", session=session, turn_id=data["turn_id"], model=data.get("model"), status="running")
            return context(event, "Agent Tree active for this turn. RUN_ID=" + run + ". Use python3 .agent-tree/control.py --run-id " + run + " for checkpoint/fork/resolve/failure/finish. Use fork --json with shell-quoted inline JSON. Follow AGENTS.md: fresh Astra before_plan, Jev which_file/which_tool/which_agent/retry_or_stop, sharp executes selected branch; split requires Sol resolve. Native branches stay pending until Pre/Post hooks observe exact tool/input. Fresh Astra on repeated error and before_done. Never alter journal/scripts to bypass audit. Native permissions still apply. Children do only assigned work and no main checkpoints.")
        if event == "SessionStart":
            return context(event, "Agent Tree resumed run " + run + ". Retain existing checkpoints for this turn. New user input gets a new run ID.")
        if event in ("SubagentStart", "SubagentStop"):
            agent_id = str(data.get("agent_id", ""))
            if not agent_id:
                return {}
            key = "agent:" + agent_id
            agent = journal.get(key, {})
            if event == "SubagentStart":
                if agent:
                    return {}  # Replayed lifecycle event must not make an old agent fresh.
                agent = {"id": agent_id, "agent_path": agent_id if agent_id.startswith("/") else None,
                         "parent": session, "role": data.get("agent_type", "unknown"),
                         "model": data.get("model"), "created_at": datetime.now(timezone.utc).isoformat(), "status": "running"}
                journal.put(key, agent)
                index.put("session:" + agent_id, {**mapping, "role": agent["role"]})
                journal.emit("agent.observed", **agent)
                return context(event, "You are a child agent. Do only the assigned role. Main owns Agent Tree checkpoints and final audit; do not run them or recursively delegate.")
            if agent:
                agent.update(status="completed", model=data.get("model") or agent.get("model"))
                journal.put(key, agent)
                journal.emit("agent.state", **agent)
            return {}
        if event in ("PreToolUse", "PostToolUse", "PermissionRequest"):
            tool = str(data.get("tool_name", "unknown"))
            # Log identity/status by default, never arguments, prompts or raw tool output.
            call_id = str(data.get("tool_use_id", ""))
            response = data.get("tool_response")
            failed = isinstance(response, dict) and (response.get("isError") is True or isinstance(response.get("exit_code"), int) and response["exit_code"] != 0)
            journal.emit("tool.activity", session=session, role=role, tool=tool, call_id=call_id,
                         status="started" if event == "PreToolUse" else ("approval_requested" if event == "PermissionRequest" else ("failed" if failed else "returned")))
            if event == "PreToolUse" and role == "main":
                return routing_guard(journal, tool, data.get("tool_input"), call_id)
            if event == "PostToolUse" and role == "main":
                native_event(journal, tool, data.get("tool_input"), call_id, "post", failed)
            if controller_call(tool, data.get("tool_input"), run):
                return {}  # Bookkeeping errors must not create recursive retry checkpoints.
            if failed and call_id and not journal.get("failure-call:" + call_id):
                journal.put("failure-call:" + call_id, True)
                signature = json.dumps({"tool": tool, "input": data.get("tool_input")}, sort_keys=True)
                observed = failure(journal, signature, source="native_hook")
                return context(event, "Agent Tree recorded a failed tool invocation. failure_key=" + observed["failure_key"] + ". If error_repeats is pending, main must request a fresh Astra review before retry. Do not also manually record this same occurrence.")
            return {}  # Never allow, rewrite or deny permissions on behalf of Codex.
        if event == "Stop":
            if role != "main" or data.get("agent_id"):
                return {}
            audit = finish(journal)
            if not audit["passed"]:
                if data.get("stop_hook_active") or journal.get("stop_reminded"):
                    journal.emit("session.audit_incomplete", missing=audit["missing"])
                    return {"systemMessage": "Agent Tree: lượt này chưa đạt workflow. Còn thiếu checkpoint hoặc quyết định chưa xử lý; không tự đánh dấu hoàn tất."}
                journal.put("stop_reminded", True)
                return {"decision": "block", "reason": "Agent Tree audit incomplete for run " + run + ": " + json.dumps(audit) + ". Complete missing steps if possible; otherwise report the actual limitation. Do not edit journal or fabricate reviews."}
            journal.emit("session.turn_completed", session=session)
        elif event in ("Interrupt", "SessionEnd"):
            journal.emit("session.lifecycle", session=session, status=event)
        return {}
    finally:
        if journal:
            journal.close()
        index.close()


def main():
    try:
        result = handle(json.load(sys.stdin))
        print(json.dumps(result, ensure_ascii=False))
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(json.dumps({"systemMessage": "Agent Tree hook không hoàn tất; kiểm tra cấu hình project."}))
        print(type(error).__name__, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
