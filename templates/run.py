#!/usr/bin/env python3
"""Launch Codex with settings scoped to this invocation and project."""
import argparse
import json
from pathlib import Path
import shlex
import shutil
import sys
from launcher import trace


def main():
    parser = argparse.ArgumentParser(description="Chạy Agent Tree trong project đã cài.")
    parser.add_argument("--print-command", action="store_true", help="Chỉ in lệnh, không chạy Codex")
    parser.add_argument("prompt", help="Yêu cầu cho Codex")
    args = parser.parse_args()
    root = Path(__file__).resolve().parent.parent
    try:
        settings = json.loads((root / ".agent-tree/settings.json").read_text())
        command = ["codex", "exec", "--json", "--skip-git-repo-check"]
        if settings.get("approval_mode", "auto-review") == "auto-review":
            command.append("--approve-for-me")
        command += ["-C", str(root), "--model", settings["main_model"],
                   "-c", "model_reasoning_effort=" + json.dumps(settings["main_effort"]),
                   "-c", "agents.enabled=true",
                   "-c", "agents.max_concurrent_threads_per_session=" + str(settings["max_agents"]),
                   "-c", "agents.default_subagent_model=" + json.dumps(settings["worker_model"]),
                   "-c", "agents.default_subagent_reasoning_effort=" + json.dumps(settings["worker_effort"])]
        command.append(args.prompt)
        if args.print_command:
            print(shlex.join(command))
            return 0
        if not shutil.which("codex"):
            print("Chưa tìm thấy Codex CLI. Hãy cài và đăng nhập Codex trước khi chạy.", file=sys.stderr)
            return 1
        return trace(command, root)
    except (OSError, ValueError, KeyError) as error:
        print("Không thể khởi động workflow: " + str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
