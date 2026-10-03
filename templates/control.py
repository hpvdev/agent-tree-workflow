#!/usr/bin/env python3
"""Executable Jev fork layer plus audited Astra checkpoints."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import os
import subprocess
import sys
import tempfile
import uuid
from runtime import Journal, ROOT, settings
from observer import Observer


def project_file(root, name):
    path = (root / name).resolve()
    if root not in path.parents or not path.is_file():
        raise ValueError("Chỉ đọc file nằm trong project.")
    if any(part in (".git", ".agent-tree") for part in path.relative_to(root).parts) or path.name.startswith(".env"):
        raise ValueError("File này không thuộc phạm vi đọc của tầng quyết định.")
    if path.stat().st_size > 256000:
        raise ValueError("File vượt giới hạn 256 KB của thao tác đọc hẹp.")
    return path


def validate_action(root, action):
    if not isinstance(action, dict) or action.get("type") not in ("read_file", "search_text", "stop", "native_tool", "spawn_agent", "main"):
        raise ValueError("Action không được hỗ trợ.")
    if action["type"] == "main":
        return
    if action["type"] in ("native_tool", "spawn_agent"):
        if not isinstance(action.get("tool"), str) or not action["tool"].strip() or not isinstance(action.get("input"), dict):
            raise ValueError("Native action cần tool và input object đúng với hook của runtime.")
        is_spawn = action["tool"].split(".")[-1].split("__")[-1] == "spawn_agent"
        if is_spawn != (action["type"] == "spawn_agent"):
            raise ValueError("Lời gọi spawn_agent phải dùng action spawn_agent.")
        if is_spawn:
            role = action.get("role")
            if role not in ("worker", "explorer", "researcher") or action["input"].get("agent_type") != "agent_tree_" + role:
                raise ValueError("Chọn worker/explorer/researcher và agent_type tương ứng; Astra chỉ qua checkpoint.")
            if "model" in action["input"] and action["input"]["model"] != settings(root)[role + "_model"]:
                raise ValueError("Model agent phải khớp cấu hình project.")
        return
    if action["type"] != "stop":
        project_file(root, action["path"])
    if action["type"] == "search_text" and (not isinstance(action.get("text"), str) or not action["text"]):
        raise ValueError("search_text cần chuỗi tìm kiếm không rỗng.")


def execute(root, action):
    validate_action(root, action)
    if action["type"] == "stop":
        return {"stopped": True, "scope": "current fork only"}
    if action["type"] == "main":
        return {"agent": "main", "instruction": "Jev selected Sol to execute this work."}
    text = project_file(root, action["path"]).read_text()
    if action["type"] == "read_file":
        return {"path": action["path"], "content": text[:16000], "truncated": len(text) > 16000}
    matches = [{"line": i, "text": line[:500]} for i, line in enumerate(text.splitlines(), 1) if action["text"] in line]
    return {"path": action["path"], "matches": matches[:40], "truncated": len(matches) > 40}


def classify(answer, labels, policy):
    probabilities = answer.get("probabilities", {})
    confidence = answer.get("confidence")
    if answer.get("type") != "choice" or set(probabilities) != set(labels):
        raise ValueError("Jev trả về tập lựa chọn không hợp lệ.")
    numbers = list(probabilities.values()) + [confidence]
    if any(isinstance(p, bool) or not isinstance(p, (int, float)) or not math.isfinite(p) or not 0 <= p <= 1 for p in numbers):
        raise ValueError("Xác suất hoặc confidence không hợp lệ.")
    if abs(sum(probabilities.values()) - 1) > .02:
        raise ValueError("Phân phối xác suất không hợp lệ.")
    ranked = sorted(probabilities, key=probabilities.get, reverse=True)
    choice = answer.get("choice")
    if choice != ranked[0]:
        raise ValueError("Lựa chọn không khớp phân phối.")
    margin = probabilities[ranked[0]] - probabilities[ranked[1]]
    sharp = choice != "sol" and confidence >= policy["confidence"] and probabilities[choice] >= policy["probability"] and margin >= policy["margin"]
    return {"route": "sharp" if sharp else "split", "choice": choice,
            "probability": probabilities[choice], "confidence": confidence, "margin": margin,
            "probabilities": probabilities}


def request_checkpoint(journal, name):
    if name not in ("before_plan", "error_repeats", "before_done"):
        raise ValueError("Checkpoint không hợp lệ.")
    pending = journal.get("checkpoint:" + name)
    if pending and pending["status"] == "pending":
        return pending
    seq = len(journal.events())
    value = {"name": name, "status": "pending", "after_seq": seq, "requested_at": datetime.now(timezone.utc).isoformat(),
             "instruction": "Spawn native agent_tree_astra now; supply objective and relevant plan/diff/errors. Await result, then complete with actual agent_id. Astra never edits code."}
    journal.put("checkpoint:" + name, value)
    journal.emit("checkpoint.requested", name=name)
    return value


def complete_checkpoint(journal, name, agent_id):
    pending = journal.get("checkpoint:" + name)
    agent = journal.get("agent:" + agent_id, {})
    if not agent:
        # Native tools can return a canonical task path instead of a thread UUID.
        candidates = [json.loads(row[0]) for row in journal.db.execute("SELECT data FROM state WHERE key LIKE 'agent:%'")]
        matches = [value for value in candidates if value.get("agent_path") == agent_id]
        if len(matches) == 1:
            agent = matches[0]
            agent_id = agent["id"]
    observed_after = any(e["type"] == "agent.observed" and e.get("id") == agent_id for e in journal.events((pending or {}).get("after_seq", 0)))
    expected = settings(journal.root)["astra_model"]
    try:
        fresh = datetime.fromisoformat(agent["created_at"].replace("Z", "+00:00")) >= datetime.fromisoformat(pending["requested_at"])
    except (KeyError, TypeError, ValueError, AttributeError):
        fresh = False
    if not pending or pending["status"] != "pending" or not observed_after or not fresh or agent.get("role") != "agent_tree_astra" or agent.get("model") != expected or agent.get("status") != "completed":
        raise ValueError("Chưa quan sát được Astra mới hoàn tất cho checkpoint này. Chờ observer hoặc báo giới hạn; không tự đánh dấu đã review.")
    pending.update(status="completed", agent_id=agent_id)
    journal.put("checkpoint:" + name, pending)
    journal.emit("checkpoint.completed", name=name, agent_id=agent_id)
    return pending


def fork(journal, request):
    if (journal.get("checkpoint:before_plan") or {}).get("status") != "completed":
        return {"route": "astra", **request_checkpoint(journal, "before_plan")}
    if request.get("kind") not in ("which_file", "which_tool", "which_agent", "retry_or_stop"):
        raise ValueError("Loại điểm rẽ không hợp lệ.")
    if request["kind"] != "which_agent" and not journal.get("agent_route"):
        raise ValueError("Jev phải chọn agent thực hiện trước các điểm rẽ khác.")
    options = request.get("options", {})
    if not 2 <= len(options) <= 12 or "sol" in options:
        raise ValueError("Cung cấp 2–12 lựa chọn, không dùng nhãn sol đã dành cho fallback.")
    if request.get("non_sensitive") is not True:
        raise ValueError("Chỉ gửi state/question/description không nhạy cảm đến Jev; cần non_sensitive=true sau khi kiểm tra.")
    if request["kind"] == "which_agent" and not journal.get("agent_route") and not any(isinstance(option, dict) and isinstance(option.get("action"), dict) and option["action"].get("type") == "main" for option in options.values()):
        raise ValueError("Lựa chọn agent đầu lượt phải gồm Sol/main để Jev có thể chọn thực hiện trực tiếp.")
    for label, option in options.items():
        if not isinstance(label, str) or not isinstance(option.get("description"), str):
            raise ValueError("Mỗi lựa chọn cần nhãn và mô tả.")
        validate_action(journal.root, option["action"])
        if request["kind"] == "which_agent" and option["action"]["type"] not in ("spawn_agent", "main", "stop"):
            raise ValueError("which_agent chỉ chọn Sol/main, agent con hoặc dừng phân công.")
        if request["kind"] != "which_agent" and option["action"]["type"] == "main":
            raise ValueError("Action Sol/main chỉ dùng để chọn agent.")
    if request["kind"] == "retry_or_stop":
        key = request.get("failure_key")
        if not key:
            raise ValueError("retry_or_stop cần failure_key từ lệnh failure.")
        failure = journal.get("failure:" + key)
        if not failure:
            raise ValueError("Chưa ghi nhận lỗi này.")
        if failure["count"] > 1 and (journal.get("checkpoint:error_repeats") or {}).get("status") != "completed":
            return {"route": "astra", **request_checkpoint(journal, "error_repeats")}
        if failure.get("retries", 0) >= settings(journal.root)["jev"]["max_retries"]:
            journal.emit("fork.stopped", reason="retry budget exhausted")
            return {"route": "stop", "reason": "retry budget exhausted"}
    state = request.get("state", "")
    question = request.get("question", "")
    if not isinstance(state, str) or not isinstance(question, str) or not state.strip() or not question.strip() or len(state) + len(question) > 12000:
        raise ValueError("Cần state/question ngắn, rõ ràng (tổng tối đa 12.000 ký tự).")
    config = settings(journal.root)["jev"]
    # A new operation after final review requires a fresh final review.
    if (journal.get("checkpoint:before_done") or {}).get("status") == "completed":
        journal.put("checkpoint:before_done", None)
        journal.emit("checkpoint.invalidated", name="before_done")
    decision_id = uuid.uuid4().hex
    decision = {"id": decision_id, "kind": request["kind"], "options": options,
                "failure_key": request.get("failure_key"), "status": "pending"}
    journal.put("decision:" + decision_id, decision)
    journal.emit("fork.started", id=decision_id, kind=request["kind"])
    criteria = {label: option["description"] for label, option in options.items()}
    criteria["sol"] = "Evidence is insufficient, candidates are missing, or Sol must reason about this decision."
    try:
        with tempfile.TemporaryDirectory() as temp:
            q = Path(temp) / "questions.json"
            q.write_text(json.dumps({"route": {"type": "choice", "instructions": question, "criteria": criteria}}))
            result = subprocess.run([config["command"], "ask", "-", "--questions", "@" + str(q),
                                     "--model", config["model"], "--timeout", str(config["timeout_ms"]), "--json"],
                                    input=state, capture_output=True, text=True, timeout=config["timeout_ms"] / 1000 + 5)
        if result.returncode:
            raise ValueError("Jev không hoàn tất yêu cầu.")
        output = json.loads(result.stdout)
        outcome = classify(output["answers"]["route"], criteria, config)
        if request["kind"] == "which_agent" and outcome["choice"] != "sol" and outcome["margin"] > 0:
            # Agent ownership belongs to Jev even when its confidence is below the generic action threshold.
            outcome["route"] = "sharp"
        outcome.update(model=output.get("model"), usage=output.get("usage"))
    except (OSError, ValueError, KeyError, TypeError, subprocess.TimeoutExpired):
        outcome = {"route": "split", "reason": "Jev unavailable or invalid output; Sol must decide."}
    decision.update(outcome)
    journal.put("decision:" + decision_id, decision)
    journal.emit("fork.decided", id=decision_id, kind=request["kind"], **outcome)
    if outcome["route"] == "sharp":
        return dispatch(journal, decision_id, outcome["choice"], "jev")
    instruction = ("Agent choice remains with Jev. Gather narrow evidence, resolve this decision to stop, then ask Jev again."
                   if request["kind"] == "which_agent" else
                   "Sol must reason from available evidence, then call resolve with a listed choice or stop. No action has run.")
    return {"id": decision_id, **outcome, "instruction": instruction}


def dispatch(journal, decision_id, choice, actor):
    decision = journal.get("decision:" + decision_id)
    if decision and choice == "stop" and (choice not in decision["options"] or decision["status"] != "pending") and decision["status"] in ("pending", "failed", "awaiting_native", "native_failed"):
        decision["status"] = "cancelled"
        journal.put("decision:" + decision_id, decision)
        journal.emit("fork.cancelled", id=decision_id, actor=actor)
        return {"id": decision_id, "stopped": True}
    if not decision or decision["status"] != "pending":
        raise ValueError("Điểm rẽ đã xử lý hoặc không tồn tại; không chạy lại hành động.")
    if decision["kind"] == "which_agent" and actor != "jev" and choice != "stop":
        raise ValueError("Chỉ Jev được chọn agent; hãy dừng điểm rẽ thiếu bằng chứng rồi hỏi lại Jev.")
    if choice == "sol" or choice not in decision["options"]:
        raise ValueError("Chỉ thực hiện lựa chọn trong tập đã khai báo.")
    action = decision["options"][choice]["action"]
    repeated = journal.get("checkpoint:error_repeats")
    if action["type"] != "stop" and repeated and repeated["status"] != "completed":
        raise ValueError("Cần Astra cho lỗi lặp lại trước khi thực thi nhánh tiếp theo.")
    if decision.get("failure_key") and action["type"] != "stop":
        if journal.get("failure:" + decision["failure_key"], {}).get("retries", 0) >= settings(journal.root)["jev"]["max_retries"]:
            raise ValueError("Đã hết lượt retry; dừng quyết định này.")
    previous = json.dumps(decision)
    decision["status"] = "executing"
    cursor = journal.db.execute("UPDATE state SET data=? WHERE key=? AND data=?", (json.dumps(decision), "decision:" + decision_id, previous))
    journal.db.commit()
    if cursor.rowcount != 1:
        raise ValueError("Một tiến trình khác đã nhận điểm rẽ này.")
    if decision.get("failure_key") and action["type"] != "stop":
        key = "failure:" + decision["failure_key"]
        failure = journal.get(key)
        failure["retries"] = failure.get("retries", 0) + 1
        journal.put(key, failure)
    if action["type"] in ("native_tool", "spawn_agent"):
        decision.update(status="awaiting_native", selected=choice, actor=actor,
                        native_signature=native_signature(action["tool"], action["input"]))
        journal.put("decision:" + decision_id, decision)
        journal.emit("fork.ready", id=decision_id, choice=choice, actor=actor, tool=action["tool"], role=action.get("role"))
        return {"id": decision_id, "route": decision["route"], "choice": choice, "actor": actor,
                "status": "awaiting_native", "call": {"tool": action["tool"], "input": action["input"]},
                "instruction": "Invoke exactly this native tool. This is a routing decision, NOT execution approval. Pre/PostToolUse hooks must observe the call before audit can pass."}
    try:
        result = execute(journal.root, action)
        decision["status"] = "completed"
    except (OSError, ValueError, UnicodeError):
        result = {"error": "Thao tác không hoàn tất; Sol cần kiểm tra dữ kiện hiện tại."}
        decision["status"] = "failed"
    journal.put("decision:" + decision_id, decision)
    journal.emit("fork.executed", id=decision_id, choice=choice, actor=actor, action=action["type"], status=decision["status"])
    if decision["kind"] == "which_agent" and action["type"] == "main" and decision["status"] == "completed" and not journal.get("agent_route"):
        journal.put("agent_route", {"role": "main", "decision_id": decision_id, "actor": actor})
    return {"id": decision_id, "route": decision["route"], "choice": choice, "actor": actor, "result": result}


def native_signature(tool, arguments):
    return hashlib.sha256(json.dumps([tool, arguments], sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def observed_agent(journal, agent_id):
    agent = journal.get("agent:" + agent_id)
    if agent:
        return agent
    matches = [json.loads(row[0]) for row in journal.db.execute("SELECT data FROM state WHERE key LIKE 'agent:%'")
               if json.loads(row[0]).get("agent_path") == agent_id]
    return matches[0] if len(matches) == 1 else None


def confirm_agent(journal, decision_id, agent_id):
    decision = journal.get("decision:" + decision_id)
    if not decision or decision["kind"] != "which_agent" or decision["status"] != "awaiting_native":
        raise ValueError("Chưa có lựa chọn agent đang chờ xác nhận.")
    action = decision["options"][decision["selected"]]["action"]
    if action["type"] != "spawn_agent":
        raise ValueError("Lựa chọn này không tạo agent con.")
    agent = observed_agent(journal, agent_id)
    ready = next((event for event in journal.events() if event["type"] == "fork.ready" and event.get("id") == decision_id), None)
    if not agent or not ready or agent.get("role") != "agent_tree_" + action["role"] or agent.get("parent") != journal.get("root_thread"):
        raise ValueError("Chưa quan sát được agent đã chọn trong phiên này; chờ metadata rồi thử lại.")
    try:
        fresh = datetime.fromisoformat(agent["created_at"].replace("Z", "+00:00")) >= datetime.fromisoformat(ready["time"])
    except (KeyError, TypeError, ValueError, AttributeError):
        fresh = False
    if not fresh or agent.get("model") != settings(journal.root)[action["role"] + "_model"]:
        raise ValueError("Agent quan sát được chưa khớp thời điểm hoặc model đã chọn.")
    decision.update(status="completed", agent_id=agent["id"])
    journal.put("decision:" + decision_id, decision)
    journal.emit("fork.agent_confirmed", id=decision_id, agent_id=agent["id"], role=action["role"])
    if not journal.get("agent_route"):
        journal.put("agent_route", {"role": action["role"], "decision_id": decision_id, "actor": "jev"})
    return {"id": decision_id, "agent_id": agent["id"], "role": action["role"], "status": "completed"}


def native_event(journal, tool, arguments, call_id, phase, failed=False):
    """Bind a selected branch to one observed invocation; never self-attest execution."""
    signature = native_signature(tool, arguments)
    journal.db.execute("BEGIN IMMEDIATE")
    try:
        rows = journal.db.execute("SELECT key,data FROM state WHERE key LIKE 'decision:%' ORDER BY rowid").fetchall()
        for key, raw in rows:
            decision = json.loads(raw)
            same_call = decision.get("call_id") == call_id and decision.get("native_signature") == signature
            if phase == "pre" and same_call and decision["status"] == "native_running":
                journal.db.commit()
                return decision["id"]
            eligible = (phase == "pre" and decision["status"] == "awaiting_native" and decision.get("native_signature") == signature or
                        phase == "post" and same_call and decision["status"] == "native_running")
            if not eligible or not call_id:
                continue
            decision.update(status="native_running" if phase == "pre" else ("native_failed" if failed else "completed"), call_id=call_id)
            journal.db.execute("UPDATE state SET data=? WHERE key=?", (json.dumps(decision), key))
            journal.db.commit()
            journal.emit("fork.native_started" if phase == "pre" else "fork.native_returned", id=decision["id"],
                         choice=decision["selected"], actor=decision["actor"], tool=tool, call_id=call_id, status=decision["status"])
            if phase == "post" and decision["status"] == "completed" and decision["kind"] == "which_agent" and not journal.get("agent_route"):
                journal.put("agent_route", {"role": decision["options"][decision["selected"]]["action"]["role"],
                                            "decision_id": decision["id"], "actor": decision["actor"]})
            return decision["id"]
        journal.db.commit()
        return None
    except Exception:
        journal.db.rollback()
        raise


def failure(journal, key, source="agent_report"):
    key = hashlib.sha256(key.encode()).hexdigest()[:20]
    value = journal.get("failure:" + key, {"count": 0, "retries": 0})
    value["count"] += 1
    journal.put("failure:" + key, value)
    journal.emit("failure.observed", key=key, count=value["count"], source=source)
    result = {"failure_key": key, **value}
    if value["count"] > 1:
        # Every recurrence needs fresh advice, not a review from an earlier recurrence.
        journal.put("checkpoint:error_repeats", None)
        result["checkpoint"] = request_checkpoint(journal, "error_repeats")
    return result


def finish(journal):
    missing = [name for name in ("before_plan", "before_done") if (journal.get("checkpoint:" + name) or {}).get("status") != "completed"]
    if not journal.get("agent_route"):
        missing.append("which_agent")
    repeated = journal.get("checkpoint:error_repeats")
    if repeated and repeated["status"] != "completed":
        missing.append("error_repeats")
    pending = [key for key, data in journal.db.execute("SELECT key,data FROM state WHERE key LIKE 'decision:%'") if json.loads(data)["status"] not in ("completed", "cancelled")]
    passed = not missing and not pending
    journal.emit("workflow.audit", passed=passed, missing=missing, unresolved=pending)
    return {"passed": passed, "missing": missing, "unresolved": pending}


def finalize_retro(journal, passed):
    """Summarize observed coordination once, after the turn has ended."""
    existing = journal.get("retro")
    if existing and (existing["workflow_passed"] or not passed):
        return existing
    events = journal.events()
    agents = {event["id"]: event.get("role", "unknown") for event in events
              if event["type"] == "agent.observed" and event.get("id")}
    counts = {role: sum(value == "agent_tree_" + role for value in agents.values())
              for role in ("astra", "worker", "explorer", "researcher")}
    decisions = [event for event in events if event["type"] == "fork.decided"]
    first = datetime.fromisoformat(events[0]["time"]) if events else datetime.now(timezone.utc)
    last = datetime.fromisoformat(events[-1]["time"]) if events else first
    report = {
        "run_id": journal.run_id,
        "workflow_passed": passed,
        "duration_seconds": max(0, round((last - first).total_seconds())),
        "agents": counts,
        "jev_forks": sum(event["type"] == "fork.started" for event in events),
        "jev_sharp": sum(event.get("route") == "sharp" for event in decisions),
        "jev_split": sum(event.get("route") == "split" for event in decisions),
        "review_restarts": sum(event["type"] == "checkpoint.invalidated" and event.get("name") == "before_done" for event in events),
        "tool_hook_events": sum(event["type"] == "tool.activity" for event in events),
        "failed_tool_calls": sum(event["type"] == "tool.activity" and event.get("status") == "failed" for event in events),
        "quality": "not_measured",
    }
    try:
        (journal.directory / "retro.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        (journal.directory / "retro.json").chmod(0o600)
    except OSError:
        pass  # A reporting file must not block a completed Codex turn.
    journal.put("retro", report)
    journal.emit("workflow.retro_updated" if existing else "workflow.retro", **report)
    return report


def main():
    parser = argparse.ArgumentParser(description="Tầng quyết định Jev và checkpoint Agent Tree")
    parser.add_argument("--run-id")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("begin")
    p = commands.add_parser("fork"); p.add_argument("--input", default="-", help="JSON trên stdin hoặc đường dẫn file"); p.add_argument("--json", help="JSON inline cho một quyết định Jev")
    p = commands.add_parser("resolve"); p.add_argument("decision_id"); p.add_argument("choice")
    p = commands.add_parser("confirm-agent"); p.add_argument("decision_id"); p.add_argument("agent_id")
    p = commands.add_parser("checkpoint"); p.add_argument("name", choices=("before_plan", "error_repeats", "before_done")); p.add_argument("--agent-id")
    p = commands.add_parser("failure"); p.add_argument("fingerprint")
    commands.add_parser("finish")
    commands.add_parser("status")
    args = parser.parse_args()
    journal = None
    try:
        if args.command == "begin":
            if not os.environ.get("CODEX_THREAD_ID"):
                raise ValueError("Codex chưa cung cấp thread ID; không thể xác minh agent trong skill.")
            journal = Journal(run_id=uuid.uuid4().hex)
            journal.put("root_thread", os.environ["CODEX_THREAD_ID"])
            journal.emit("session.turn", session=os.environ["CODEX_THREAD_ID"], status="running", mode="skill")
            print(json.dumps({"run_id": journal.run_id}, ensure_ascii=False))
            return 0
        journal = Journal(run_id=args.run_id)
        if journal.get("root_thread") and journal.get("transport") != "hooks":
            Observer(journal).poll()
        if args.command == "fork":
            value = fork(journal, json.loads(args.json) if args.json is not None else (json.load(sys.stdin) if args.input == "-" else json.loads(Path(args.input).read_text())))
        elif args.command == "resolve":
            value = dispatch(journal, args.decision_id, args.choice, "sol")
        elif args.command == "confirm-agent":
            value = confirm_agent(journal, args.decision_id, args.agent_id)
        elif args.command == "checkpoint":
            value = complete_checkpoint(journal, args.name, args.agent_id) if args.agent_id else request_checkpoint(journal, args.name)
        elif args.command == "failure":
            value = failure(journal, args.fingerprint)
        elif args.command == "status":
            value = {"agents": [json.loads(row[0]) for row in journal.db.execute("SELECT data FROM state WHERE key LIKE 'agent:%'")],
                     "checkpoints": {name: journal.get("checkpoint:" + name) for name in ("before_plan", "error_repeats", "before_done")}}
        else:
            value = finish(journal)
            finalize_retro(journal, value["passed"])
        print(json.dumps(value, ensure_ascii=False))
        return 0 if value.get("passed", True) else 2
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(json.dumps({"error": str(error)}, ensure_ascii=False))
        return 1
    finally:
        if journal:
            journal.close()


if __name__ == "__main__":
    sys.exit(main())
