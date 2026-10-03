"""Render Codex JSONL events; never synthesize work, progress, or token counts."""
from collections import deque
from datetime import datetime
import json
from pathlib import Path
import re
import subprocess
import sys


def clean(value, limit=160):
    return re.sub(r"[\x00-\x1f\x7f-\x9f]", " ", str(value))[:limit]


class Monitor:
    def __init__(self, settings=None, live=False):
        self.settings = settings or {}
        self.live = live and sys.stdout.isatty()
        self.events = deque(maxlen=12)
        self.agents = {}
        self.status = "Chờ sự kiện"
        self.final = ""
        self.failed = False
        self.completed = False

    def accept(self, event):
        kind = event.get("type", "unknown")
        item = event.get("item") or {}
        label = kind
        if kind == "thread.started":
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
        entry = datetime.now().strftime("%H:%M:%S") + "  " + clean(label)
        self.events.append(entry)
        if self.live:
            print("\033[2J\033[H", end="")
            print("AGENT TREE  |  " + self.status)
            print("Main cấu hình: " + clean(self.settings.get("main_model", "không có")))
            print("Main")
            for agent, status in self.agents.items():
                print("  └─ " + clean(agent, 36) + " · " + clean(status, 60))
            if not self.agents:
                print("  └─ Chưa nhận sự kiện agent phụ")
            print("\n" + "\n".join(self.events), flush=True)
        else:
            print(entry, flush=True)


def replay(path):
    monitor = Monitor()
    with Path(path).open() as file:
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
    log_dir = root / ".agent-tree/logs"
    if log_dir.is_symlink():
        raise ValueError("Thư mục log không được là symbolic link.")
    log_dir.mkdir(exist_ok=True, mode=0o700)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    path = log_dir / (stamp + ".jsonl")
    monitor = Monitor(settings, live=True)
    with path.open("x") as log, (log_dir / (stamp + ".stderr.log")).open("x") as errors:
        path.chmod(0o600)
        (log_dir / (stamp + ".stderr.log")).chmod(0o600)
        process = subprocess.Popen(command, cwd=root, stdout=subprocess.PIPE, stderr=errors, text=True)
        try:
            for line in process.stdout:
                log.write(line)
                log.flush()
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                if isinstance(event, dict):
                    monitor.accept(event)
            result = process.wait()
        except KeyboardInterrupt:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            result = 130
        finally:
            process.stdout.close()
    if monitor.final:
        print("\nKết quả:\n" + clean(monitor.final, len(monitor.final)))
    print("\nLog: " + str(path))
    if result == 0 and (monitor.failed or not monitor.completed):
        result = 1
    if result:
        print("Phiên chưa hoàn tất thành công. Chi tiết nằm trong log và file .stderr.log cùng tên.")
    return result
