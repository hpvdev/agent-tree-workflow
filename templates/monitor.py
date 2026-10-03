"""Render Codex JSONL events; never synthesize work, progress, or token counts."""
from collections import deque
from datetime import datetime
import json
from pathlib import Path
import re
import subprocess
import sys
import os
import queue
import threading
from display import frame
from runtime import Journal
from observer import Observer


def clean(value, limit=160):
    return re.sub(r"[\x00-\x1f\x7f-\x9f]", " ", str(value))[:limit]


class Monitor:
    def __init__(self, settings=None, live=False, caption=""):
        self.settings = settings or {}
        self.live = live and sys.stdout.isatty()
        self.caption = caption
        self.events = deque(maxlen=12)
        self.agents = {}
        self.status = "Chờ sự kiện"
        self.final = ""
        self.failed = False
        self.completed = False
        self.forks = 0
        self.sharp = 0
        self.split = 0
        self.checkpoints = {}
        self.agent_details = {}
        self.decisions = {}
        self.activity_time = None
        self.animation_stopped = True
        self.phase = None
        self.playback = False
        self.last_frame = None

    def accept(self, event):
        kind = event.get("type", "unknown")
        item = event.get("item") or {}
        label = kind
        self.activity_time = event.get("time", datetime.now().astimezone().isoformat())
        if kind in ("session.turn", "turn.started", "fork.started", "agent.observed") or kind == "tool.activity" and event.get("status") == "started":
            self.animation_stopped = False
        if kind in ("session.turn_completed", "turn.completed", "turn.failed", "session.audit_incomplete", "workflow.audit", "error") or kind == "session.lifecycle":
            self.animation_stopped = True
        if kind.startswith("fork."):
            self.phase = "jev"
        elif kind.startswith("agent."):
            self.phase = "agent"
        elif kind == "tool.activity":
            self.phase = "tool"
        elif kind.startswith("checkpoint."):
            self.phase = "review"
        if kind == "session.turn":
            self.status = "Đang chạy"
            label = "Phiên " + event.get("session", "") + " · nhận yêu cầu mới"
        elif kind == "session.turn_completed":
            self.status = "Hoàn tất lượt"
            label = self.status
        elif kind == "session.audit_incomplete":
            self.status = "Chưa đủ checkpoint"
            label = self.status
        elif kind == "tool.activity":
            label = event.get("role", "agent") + " · " + event.get("tool", "tool") + " · " + event.get("status", "")
        elif kind == "routing.blocked":
            label = "JEV · chặn tool chưa khớp nhánh · " + event.get("tool", "")
        elif kind in ("agent.observed", "agent.state"):
            agent = event["id"]
            self.agent_details.setdefault(agent, {}).update(event)
            self.agents[agent] = event.get("status", "observed")
            label = event.get("role", "agent") + " · " + event.get("status", "observed") + " · " + str(event.get("model") or "đang xác định model")
        elif kind == "agent.usage":
            self.agent_details.setdefault(event["id"], {}).update(usage=event.get("usage", {}))
            label = event.get("role", "agent") + " · cập nhật token"
        elif kind == "fork.started":
            self.forks += 1
            label = "JEV · " + event["kind"] + " · đang đánh giá"
        elif kind == "fork.decided":
            route = event["route"]
            self.sharp += route == "sharp"
            self.split += route == "split"
            probability = event.get("probability")
            self.decisions[event["kind"]] = event
            label = "JEV · " + event["kind"] + " → " + event.get("choice", "Sol") + " · " + route
            if probability is not None:
                label += " · p=" + format(probability, ".3f") + " · confidence=" + format(event["confidence"], ".3f")
        elif kind.startswith("fork."):
            label = "JEV · " + kind + " · " + str(event.get("choice", event.get("reason", "")))
        elif kind.startswith("checkpoint."):
            self.checkpoints[event["name"]] = "completed" if kind.endswith("completed") else "pending"
            label = "ASTRA · " + event["name"] + " · " + self.checkpoints[event["name"]]
        elif kind == "workflow.audit":
            label = "Workflow: đủ checkpoint" if event["passed"] else "Workflow: còn thiếu checkpoint hoặc quyết định chưa xử lý"
            self.status = "Đủ checkpoint" if event["passed"] else "Chưa đủ checkpoint"
        elif kind == "observer.warning":
            label = event["message"]
        elif kind == "failure.observed":
            label = "Lỗi được báo lại · lần " + str(event["count"])
        elif kind == "thread.started":
            label = "Bắt đầu phiên " + str(event.get("thread_id", ""))
        elif kind == "turn.started":
            self.status = "Đang chạy"
            label = self.status
        elif kind == "turn.completed":
            self.status = "Hoàn tất lượt"
            self.completed = True
            label = self.status + " | usage: " + json.dumps(event.get("usage", {}))
        elif kind in ("turn.failed", "error"):
            self.status = "Có lỗi — xem log để biết chi tiết"
            self.failed = True
            label = self.status
        elif kind.startswith("item."):
            phase = {"item.started": "đang chạy", "item.updated": "cập nhật", "item.completed": "xong"}.get(kind, kind)
            item_type = item.get("type", "item")
            label = item_type + " · " + phase
            if item_type == "agent_message":
                label = item.get("text", label)
                if kind == "item.completed":
                    self.final = item.get("text", "")
            elif item_type == "reasoning":
                label = "Đang xử lý yêu cầu"
            elif item_type == "command_execution":
                label = phase + " · " + str(item.get("command", ""))
                if item.get("exit_code") is not None:
                    label += " · exit=" + str(item["exit_code"])
            elif item_type == "file_change":
                label = phase + " · " + ", ".join(c.get("path", "") for c in item.get("changes", []))
            elif item_type in ("collab_agent_tool_call", "collab_tool_call", "collabToolCall"):
                label = str(item.get("tool", "agent")) + " · " + phase
                ids = item.get("receiver_thread_ids", [])
                single = item.get("newThreadId") or item.get("receiverThreadId")
                if single:
                    ids = list(ids) + [single]
                statuses = item.get("agents_states", {})
                for agent_id in ids:
                    state = statuses.get(agent_id, {})
                    self.agents[agent_id] = state.get("status", "được gọi; chưa có trạng thái") if isinstance(state, dict) else state
                for agent_id, state in statuses.items():
                    self.agents[agent_id] = state.get("status", state) if isinstance(state, dict) else state
                label += " · " + ", ".join(str(i) for i in ids)
            elif item_type in ("mcp_tool_call", "dynamic_tool_call"):
                label = str(item.get("tool", item_type)) + " · " + phase
        entry = str(event.get("time", datetime.now().strftime("%H:%M:%S"))) + "  " + clean(label)
        self.events.append(entry)
        if self.live:
            self.draw()
        else:
            print(entry, flush=True)

    def draw(self):
        if not self.live:
            return
        rendered = frame(self)
        if rendered != self.last_frame:
            print("\033[H" + rendered + "\033[J", end="", flush=True)
            self.last_frame = rendered


def replay(path):
    monitor = Monitor()
    path = Path(path)
    if path.is_dir():
        path = path / "timeline.jsonl"
    with path.open() as file:
        for line in file:
            try:
                event = json.loads(line)
            except ValueError:
                print("Bỏ qua một dòng log không hợp lệ.")
                continue
            if isinstance(event, dict):
                monitor.accept(event)
    if monitor.final:
        print("\nKết quả:\n" + clean(monitor.final, len(monitor.final)))
    return 0


def trace(command, root, settings):
    from control import finish
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    journal = Journal(root, stamp)
    observer = Observer(journal)
    monitor = Monitor(settings, live=True)
    path = journal.directory / "codex.jsonl"
    environment = dict(os.environ, AGENT_TREE_RUN=stamp)
    # Scope the controller to this run even when shell environment filtering drops custom env vars.
    command = list(command)
    command[-1] += ("\n\nAgent Tree run ID: " + stamp + ". Main must follow project workflow. "
                    "Use python3 .agent-tree/control.py --run-id " + stamp + " for checkpoint, fork, resolve, failure, finish. "
                    "Before planning request before_plan and spawn native agent_tree_astra, await and complete with actual agent_id. "
                    "Use Jev fork for narrow file/tool/agent/retry semantic decisions. Resolve split results as Sol. "
                    "After implementation and verification request before_done, spawn a fresh native Astra, await, complete. "
                    "No checkpoint can be self-attested. Never alter workflow state or scripts to pass audit. "
                    "If model/tool/observer unavailable, report the block. Finally run control finish.")
    messages = queue.Queue()
    cursor = 0
    def read_output(stream):
        try:
            for line in stream:
                messages.put(line)
        finally:
            messages.put(None)
    with path.open("x") as log, (journal.directory / "stderr.log").open("x") as errors, (journal.directory / "timeline.jsonl").open("x") as timeline:
        for file in (path, journal.directory / "stderr.log", journal.directory / "timeline.jsonl"):
            file.chmod(0o600)
        process = subprocess.Popen(command, cwd=root, env=environment, stdout=subprocess.PIPE, stderr=errors, text=True)
        reader = threading.Thread(target=read_output, args=(process.stdout,), daemon=True)
        reader.start()
        ended = False
        try:
            while not ended:
                try:
                    line = messages.get(timeout=.5)
                except queue.Empty:
                    line = ""
                if line is None:
                    ended = True
                elif line:
                    log.write(line); log.flush()
                    try:
                        event = json.loads(line)
                        if isinstance(event, dict):
                            if event.get("type") == "thread.started":
                                journal.put("root_thread", event["thread_id"])
                            monitor.accept(event)
                            timeline.write(json.dumps(event) + "\n"); timeline.flush()
                    except ValueError:
                        pass
                if journal.get("transport") != "hooks":
                    observer.poll()
                monitor.draw()
                for event in journal.events(cursor):
                    cursor = event["seq"]
                    monitor.accept(event)
                    timeline.write(json.dumps(event) + "\n"); timeline.flush()
            result = process.wait()
        except KeyboardInterrupt:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill(); process.wait()
            result = 130
        finally:
            reader.join(timeout=2)
            process.stdout.close()
        if journal.get("transport") != "hooks":
            observer.poll()
        audit = finish(journal)
        for event in journal.events(cursor):
            monitor.accept(event)
            timeline.write(json.dumps(event) + "\n")
        if not audit["passed"] and result == 0:
            result = 2
    journal.close()
    if monitor.final:
        print("\nKết quả:\n" + clean(monitor.final, len(monitor.final)))
    print("\nLog: " + str(journal.directory))
    if result == 0 and (monitor.failed or not monitor.completed):
        result = 1
    if result:
        print("Phiên chưa đạt đầy đủ workflow. Xem timeline.jsonl và stderr.log trong thư mục log.")
    return result
