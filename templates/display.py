"""Terminal tree frames, driven only by observed activity."""
import re
import shutil
import time
from datetime import datetime

COLORS = {"sol": "\033[38;5;215m", "jev": "\033[38;5;155m", "astra": "\033[38;5;211m", "agent": "\033[38;5;147m", "dim": "\033[38;5;245m"}
RESET = "\033[0m"


def safe(value):
    return re.sub(r"[\x00-\x1f\x7f-\x9f]", " ", str(value))


def recent(timestamp, now):
    try:
        return 0 <= now - datetime.fromisoformat(timestamp.replace("Z", "+00:00")).timestamp() < 15
    except (TypeError, ValueError, AttributeError):
        return False


def frame(view, now=None, columns=None):
    now = time.time() if now is None else now
    width = min(columns or shutil.get_terminal_size((100, 40)).columns, 120) - 1
    width = max(width, 30)
    alive = recent(view.activity_time, now) and not view.animation_stopped
    pulse = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"[int(now * 8) % 10] if alive else "○"
    heading = ("PHÁT LẠI NHẬT KÝ" if view.playback else ("HOẠT ĐỘNG VỪA GHI NHẬN" if alive else "NHẬT KÝ · CHỜ SỰ KIỆN MỚI"))
    height = shutil.get_terminal_size((100, 40)).lines
    if width < 88 or height < 35:
        line = "─" * max(1, width - 2)
        def border(title, color):
            return COLORS[color] + "│ " + safe(title)[:width - 4].ljust(width - 4) + " │" + RESET
        def status(role):
            records = [d for d in view.agent_details.values() if d.get("role") == "agent_tree_" + role]
            running = sum(d.get("status") == "running" for d in records)
            done = sum(d.get("status") == "completed" for d in records)
            return (pulse + " " + str(running)) if running else ("✓ " + str(done) if done else ("cần kiểm tra" if records else "—"))
        flow = (" " * (int(now * 6) % max(1, width - 12)) + "●") if alive else "↓"
        lines = [COLORS["sol"] + "AGENT TREE · " + heading + RESET,
                 safe(view.caption)[:width],
                 COLORS["sol"] + "╭" + line + "╮" + RESET,
                 border("SOL · " + safe(view.settings.get("main_model", "?")) + " · " + view.status, "sol"),
                 COLORS["sol"] + "╰" + line + "╯" + RESET,
                 COLORS["jev"] + flow + RESET,
                 COLORS["jev"] + "╭" + line + "╮" + RESET,
                 border("JEV FORK LAYER · %s forks · sharp %s / split %s" % (view.forks, view.sharp, view.split), "jev")]
        for kind in ("which_file", "which_tool", "which_agent", "retry_or_stop"):
            decision = view.decisions.get(kind, {})
            probability = decision.get("probability")
            detail = format(probability, ".2f") + " " + decision.get("route", "") + " → " + decision.get("choice", "Sol") if probability is not None else decision.get("reason", "chưa có quyết định")
            lines.append(border(kind.ljust(14) + " " + detail, "jev"))
        lines += [COLORS["jev"] + "╰" + line + "╯" + RESET,
                  COLORS["agent"] + "  ↓ WORKER " + status("worker") + "   ↓ EXPLORER " + status("explorer") + "   ↓ RESEARCHER " + status("researcher") + RESET,
                  COLORS["astra"] + "ASTRA · " + " · ".join(("✓ " if value == "completed" else pulse + " ") + key for key, value in view.checkpoints.items()) + RESET,
                  COLORS["sol"] + "  └─────────► SOL · REVIEW / VERIFY" + RESET,
                  "Kéo rộng cửa sổ để xem đầy đủ cây và model từng agent."]
        count = max(0, min(3, height - len(lines) - 2))
        if count:
            lines += [safe(line)[-width:] for line in list(view.events)[-count:]]
        lines += ["Ctrl+C đóng Watch · không dừng Codex"]
        return "\n".join(lines[:max(1, height - 1)])
    grid = [[(" ", "dim") for _ in range(width)] for _ in range(32)]

    def put(x, y, text, color="dim"):
        if 0 <= y < len(grid):
            for i, char in enumerate(safe(text)):
                if 0 <= x + i < width:
                    grid[y][x + i] = (char, color)

    def box(x, y, w, h, title, lines, color):
        put(x, y, "╭" + "─" * (w - 2) + "╮", color)
        for yy in range(y + 1, y + h - 1):
            put(x, yy, "│" + " " * (w - 2) + "│", color)
        put(x, y + h - 1, "╰" + "─" * (w - 2) + "╯", color)
        put(x + 2, y + 1, title[:w - 4], color)
        for i, line in enumerate(lines[:h - 3]):
            put(x + 2, y + 2 + i, line[:w - 4], color)

    def edge(points, color, moving=False):
        for x, y, char in points:
            put(x, y, char, "dim")
        if points and alive and moving:
            x, y, _ = points[int(now * 6) % len(points)]
            put(x, y, "●", color)

    left = 23
    x = left + 3
    area = width - x
    mid = x + area // 2
    put(0, 0, "CODEX AGENT TREE", "sol")
    put(24, 0, heading, "jev" if alive else "dim")
    put(0, 1, safe(view.caption)[:width])
    astra = [d for d in view.agent_details.values() if d.get("role") == "agent_tree_astra"]
    busy_astra = any(d.get("status") == "running" for d in astra)
    counts = [(d.get("usage") or {}).get("input_tokens") for d in astra]
    tokens = str(sum(counts)) if counts and all(v is not None for v in counts) else "chưa có dữ liệu"
    checkpoints = []
    for name in ("before_plan", "error_repeats", "before_done"):
        state = view.checkpoints.get(name)
        mark = "✓" if state == "completed" else (pulse if state == "pending" else "·")
        checkpoints += [mark + " " + name, ""]
    box(0, 3, left, 21, "ASTRA · ON CALL", [
        "Chỉ tư vấn", "", *checkpoints, "Calls: " + str(len(astra)), "Input tokens:", tokens,
        "", "Sol áp dụng review", "Không sửa code"], "astra")
    box(mid - 16, 3, 33, 5, "SOL · MAIN", [safe(view.settings.get("main_model", "model chưa rõ")), pulse + " " + view.status], "sol")
    edge([(xx, 5, "─") for xx in range(left, mid - 16)], "astra", busy_astra)
    edge([(mid, yy, "│") for yy in range(8, 10)], "jev", view.phase == "jev")
    put(x, 8, "max agents: " + str(view.settings.get("max_agents", 6)), "agent")
    choices = []
    for kind in ("which_file", "which_tool", "which_agent", "retry_or_stop"):
        choice = view.decisions.get(kind, {})
        p = choice.get("probability")
        bar = "█" * round(p * 8) + "░" * (8 - round(p * 8)) if p is not None else "········"
        choices.append(kind.ljust(14) + " " + bar + " " + (format(p, ".2f") if p is not None else " -- ") + " " + choice.get("route", "chưa gọi"))
    box(x, 10, area, 8, "JEV · FORK LAYER   " + str(view.forks) + " forks", choices + ["sharp → code   |   split → Sol"], "jev")
    agent_w = (area - 4) // 3
    centers = [x + i * (agent_w + 2) + agent_w // 2 for i in range(3)]
    edge([(mid, 18, "│")] + [(xx, 19, "─") for xx in range(centers[0], centers[-1] + 1)], "agent", view.phase in ("tool", "agent"))
    for i, role in enumerate(("worker", "explorer", "researcher")):
        records = [d for d in view.agent_details.values() if d.get("role") == "agent_tree_" + role]
        running = sum(d.get("status") == "running" for d in records)
        done = sum(d.get("status") == "completed" for d in records)
        model = records[-1].get("model") if records else None
        status = (pulse + " " + str(running) + " đang chạy") if running else ("✓ " + str(done) + " đã xong" if done else "Chưa được gọi")
        edge([(centers[i], 20, "▼")], "agent", running > 0)
        box(x + i * (agent_w + 2), 21, agent_w, 5, role.upper(), [safe(model or "—"), status], "agent")
    edge([(xx, 26, "─") for xx in range(centers[0], centers[-1] + 1)] + [(mid, 27, "▼")], "sol", view.phase == "review")
    box(mid - 16, 28, 33, 4, "BACK TO SOL · REVIEW / VERIFY", [view.status], "sol")
    edge([(xx, 29, "─") for xx in range(left, mid - 16)], "astra", busy_astra)
    result = []
    for row in grid:
        line, previous = "", None
        for char, color in row:
            if color != previous:
                line += COLORS[color]
                previous = color
            line += char
        result.append(line.rstrip() + RESET)
    count = max(0, min(5, height - 35))
    result += [COLORS["dim"] + "─" * width + RESET]
    result += [safe(line)[-width:] for line in list(view.events)[-count:]] if count else []
    result += ["Ctrl+C đóng Watch · không dừng Codex" + (" · phát lại dữ liệu đã lưu" if view.playback else "")]
    return "\n".join(result)
