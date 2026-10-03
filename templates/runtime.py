"""Per-run event journal and checkpoints. All state stays inside the project."""
import json
import os
from pathlib import Path
import re
import sqlite3
from datetime import datetime, timezone


ROOT = Path(__file__).resolve().parent.parent


class Journal:
    def __init__(self, root=ROOT, run_id=None):
        self.root = Path(root).resolve()
        self.run_id = run_id or os.environ.get("AGENT_TREE_RUN")
        if not self.run_id or not re.fullmatch(r"[A-Za-z0-9_-]+", self.run_id):
            raise ValueError("Hãy chạy qua run.py hoặc cung cấp --run-id hợp lệ.")
        directory = self.root / ".agent-tree/logs" / self.run_id
        for path in (directory.parent, directory, directory / "events.sqlite3"):
            if path.is_symlink():
                raise ValueError("Không ghi nhật ký qua symbolic link.")
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.directory = directory
        self.db = sqlite3.connect(str(directory / "events.sqlite3"), timeout=15)
        self.db.execute("CREATE TABLE IF NOT EXISTS events (seq INTEGER PRIMARY KEY, time TEXT, type TEXT, data TEXT)")
        self.db.execute("CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, data TEXT)")
        self.db.commit()
        (directory / "events.sqlite3").chmod(0o600)

    def close(self):
        self.db.close()

    def emit(self, event_type, **data):
        self.db.execute("INSERT INTO events(time,type,data) VALUES (?,?,?)",
                        (datetime.now(timezone.utc).isoformat(), event_type, json.dumps(data)))
        self.db.commit()

    def events(self, after=0):
        return [{"seq": seq, "time": time, "type": kind, **json.loads(data)}
                for seq, time, kind, data in self.db.execute("SELECT seq,time,type,data FROM events WHERE seq>? ORDER BY seq", (after,))]

    def get(self, key, default=None):
        row = self.db.execute("SELECT data FROM state WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def put(self, key, value):
        self.db.execute("INSERT OR REPLACE INTO state VALUES (?,?)", (key, json.dumps(value)))
        self.db.commit()


def settings(root=ROOT):
    return json.loads((Path(root) / ".agent-tree/settings.json").read_text())
