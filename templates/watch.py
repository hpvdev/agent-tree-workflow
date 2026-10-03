#!/usr/bin/env python3
"""Independent, read-only viewer for a session started in any Codex client."""
import argparse
import json
from pathlib import Path
import sqlite3
import time
from monitor import Monitor
from runtime import ROOT, settings


def read_state(path, key):
    if not path.exists():
        return None
    with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True) as db:
        row = db.execute("SELECT data FROM state WHERE key=?", (key,)).fetchone()
    return json.loads(row[0]) if row else None


def main():
    parser = argparse.ArgumentParser(description="Theo dõi phiên Codex độc lập, không gọi model")
    parser.add_argument("--session", help="Session ID của phiên cần theo dõi")
    parser.add_argument("--list", action="store_true", help="Liệt kê các phiên đã phát hook trong project")
    args = parser.parse_args()
    index = ROOT / ".agent-tree/logs/sessions/events.sqlite3"
    if args.list:
        if not index.exists():
            print("Chưa nhận sự kiện hooks. Mở project trong Codex, trust hooks qua /hooks và gửi yêu cầu mới.")
            return
        with sqlite3.connect(index.resolve().as_uri() + "?mode=ro", uri=True) as db:
            for key, value in db.execute("SELECT key,data FROM state WHERE key LIKE 'session:%'"):
                value = json.loads(value)
                if value.get("role") == "main":
                    print(key.removeprefix("session:"), value["run_id"])
        return
    if not args.session:
        parser.error("Chọn --session ID hoặc dùng --list trước.")
    active = None
    cursor = 0
    view = Monitor(settings(ROOT), live=True)
    print("Đang chờ sự kiện của phiên " + args.session + ". Ctrl+C chỉ đóng bảng theo dõi.")
    try:
        while True:
            state = read_state(index, "session:" + args.session)
            if state:
                run = state["run_id"]
                if run != active:
                    active, cursor = run, 0
                    view = Monitor(settings(ROOT), live=True)
                    print("Lượt: " + run)
                path = ROOT / ".agent-tree/logs" / run / "events.sqlite3"
                if path.exists():
                    with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True) as db:
                        rows = db.execute("SELECT seq,time,type,data FROM events WHERE seq>? ORDER BY seq", (cursor,)).fetchall()
                    for seq, timestamp, kind, data in rows:
                        cursor = seq
                        view.accept({"seq": seq, "time": timestamp, "type": kind, **json.loads(data)})
            time.sleep(.5)
    except KeyboardInterrupt:
        print("Đã đóng bảng theo dõi; phiên Codex vẫn tiếp tục.")


if __name__ == "__main__":
    main()
