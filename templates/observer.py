"""Read-only adapter for local Codex rollout metadata. No encrypted text is decoded.

Rollout formats are not stable APIs. Unknown formats remain explicitly unobserved.
Only the selected root session and its descendants enter the project journal.
"""
from datetime import datetime, timedelta, timezone
import json
import os
import time
from pathlib import Path


class Observer:
    def __init__(self, journal, sessions=None):
        self.journal = journal
        self.sessions = Path(sessions) if sessions else Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")) / "sessions"
        self.tracked = {}
        self.checked = set()
        self.since = time.time() - 10

    def poll(self):
        root_id = self.journal.get("root_thread")
        if not root_id:
            return
        candidates = []
        # Session files are partitioned by date; include both sides of a timezone boundary.
        for offset in (-1, 0, 1):
            day = datetime.now(timezone.utc) + timedelta(days=offset)
            candidates.extend((self.sessions / day.strftime("%Y/%m/%d")).glob("*.jsonl"))
        for path in candidates:
            if path in self.checked:
                continue
            try:
                if path.stat().st_mtime < self.since:
                    continue
                with path.open() as file:
                    meta = json.loads(file.readline()).get("payload", {})
                source = meta.get("source", {})
                spawn = source.get("subagent", {}).get("thread_spawn", {}) if isinstance(source, dict) else {}
                thread = meta.get("id") or meta.get("session_id")
                parent = spawn.get("parent_thread_id")
                known_ids = {value["id"] for value in self.tracked.values()} | {root_id}
                if thread != root_id and parent not in known_ids:
                    # Reconsider later: its parent may be discovered in the next poll.
                    continue
                if Path(meta.get("cwd", "")).resolve() != self.journal.root:
                    continue
                role = meta.get("agent_role") or spawn.get("agent_role") or ("main" if thread == root_id else "unknown")
                agent = {"id": thread, "agent_path": spawn.get("agent_path"), "created_at": meta.get("timestamp"), "parent": parent, "role": role, "status": "observed", "model": None}
                self.tracked[path] = {**agent, "offset": 0, "usage": None, "started": meta.get("timestamp", "")}
                self.checked.add(path)
                self.journal.put("agent:" + thread, agent)
                self.journal.emit("agent.observed", **agent)
            except (OSError, ValueError, TypeError, AttributeError):
                continue
        for path, info in list(self.tracked.items()):
            try:
                with path.open() as file:
                    file.seek(info["offset"])
                    while True:
                        start = file.tell()
                        line = file.readline()
                        if not line or not line.endswith("\n"):
                            info["offset"] = start
                            break
                        event = json.loads(line)
                        if event.get("timestamp", "") < info["started"]:
                            continue
                        payload = event.get("payload", {})
                        changed = False
                        if event.get("type") == "turn_context" and payload.get("model"):
                            info["model"] = payload["model"]
                            changed = True
                        if event.get("type") == "event_msg":
                            kind = payload.get("type")
                            if kind in ("task_started", "task_complete", "task_failed", "turn_aborted"):
                                info["status"] = {"task_started": "running", "task_complete": "completed", "task_failed": "failed", "turn_aborted": "interrupted"}[kind]
                                changed = True
                            if kind == "token_count":
                                usage = (payload.get("info") or {}).get("total_token_usage")
                                if usage and usage != info["usage"]:
                                    info["usage"] = usage
                                    self.journal.emit("agent.usage", id=info["id"], role=info["role"], usage=usage)
                        if changed:
                            agent = {k: info[k] for k in ("id", "agent_path", "created_at", "parent", "role", "model", "status")}
                            self.journal.put("agent:" + info["id"], agent)
                            self.journal.emit("agent.state", **agent)
            except (OSError, ValueError, TypeError, AttributeError):
                self.journal.emit("observer.warning", message="Không đọc được một phần metadata; không suy đoán trạng thái.")
