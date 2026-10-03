#!/usr/bin/env python3
"""Project-local installation. Python 3.9+, standard library only."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

START = "<!-- agent-tree:start -->"
END = "<!-- agent-tree:end -->"
SOURCE = Path(__file__).resolve().parent
ROLES = ("worker", "explorer", "researcher", "astra")
DEFAULT_MODELS = {"main": "gpt-6-sol", "worker": "gpt-6-sol", "explorer": "gpt-6-luna",
                  "researcher": "gpt-6-luna", "astra": "gpt-6-astra"}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def local_path(root, relative):
    path = root / relative
    if Path(relative).is_absolute() or ".." in Path(relative).parts:
        raise ValueError("Đường dẫn cài đặt không hợp lệ: " + relative)
    for part in [path] + list(path.parents):
        if part == root:
            break
        if part.is_symlink():
            raise ValueError("Không ghi qua symbolic link: " + str(part))
    return path


def checked_manifest(root):
    path = local_path(root, ".agent-tree/manifest.json")
    manifest = json.loads(path.read_text())
    for name, expected in manifest["files"].items():
        file = local_path(root, name)
        if not file.is_file() or digest(file.read_bytes()) != expected:
            raise ValueError("File workflow đã thay đổi hoặc bị thiếu; giữ nguyên để tránh mất dữ liệu: " + name)
    agents = local_path(root, "AGENTS.md")
    data = agents.read_bytes()
    block = manifest["block"].encode()
    if data.count(block) != 1:
        raise ValueError("Khối Agent Tree trong AGENTS.md đã thay đổi; hãy khôi phục khối trước khi gỡ.")
    return manifest


def install(root, args):
    settings = {role + "_model": getattr(args, role + "_model") or model
                for role, model in DEFAULT_MODELS.items()}
    settings.update({role + "_effort": getattr(args, role + "_effort") or ("high" if role == "main" else "medium") for role in DEFAULT_MODELS})
    settings["max_agents"] = args.max_agents or 6
    for key, value in settings.items():
        if key.endswith("_model") and not re.fullmatch(r"[A-Za-z0-9_.:/-]+", value):
            raise ValueError("Model ID không hợp lệ: " + value)
    package = local_path(root, ".agent-tree")
    if package.exists():
        checked_manifest(root)
        if json.loads((package / "settings.json").read_text()) != settings:
            raise ValueError("Project đã cài với tùy chọn khác. Gỡ bản cũ trước khi cài lại.")
        print("Workflow đã được cài; không thay đổi file.")
        return
    agents = local_path(root, "AGENTS.md")
    if agents.exists() and not agents.is_file():
        raise ValueError("AGENTS.md phải là file thông thường.")
    original = agents.read_bytes() if agents.exists() else b""
    if START.encode() in original or END.encode() in original:
        raise ValueError("AGENTS.md đã có khối Agent Tree. Kiểm tra bản cài hiện có trước.")
    workflow = (SOURCE / "templates/workflow.md").read_text()
    block = ("\n\n" if original else "") + START + "\n" + workflow + "\n" + END + "\n"
    files = {
        ".agent-tree/run.py": (SOURCE / "templates/run.py").read_bytes(),
        ".agent-tree/monitor.py": (SOURCE / "templates/monitor.py").read_bytes(),
        ".agent-tree/.gitignore": b"logs/\n__pycache__/\n",
        ".agent-tree/install.py": Path(__file__).read_bytes(),
        ".agent-tree/settings.json": (json.dumps(settings, indent=2) + "\n").encode(),
    }
    for role in ROLES:
        relative = ".codex/agents/agent_tree_" + role + ".toml"
        template = (SOURCE / "templates/agents" / ("agent_tree_" + role + ".toml")).read_text()
        template = re.sub(r'^model = ".*"$', 'model = ' + json.dumps(settings[role + "_model"]), template, flags=re.M)
        template = re.sub(r'^model_reasoning_effort = ".*"$', 'model_reasoning_effort = ' + json.dumps(settings[role + "_effort"]), template, flags=re.M)
        files[relative] = template.encode()
    for name in files:
        if local_path(root, name).exists():
            raise ValueError("Không ghi đè file có sẵn: " + name)
    manifest = {"version": 1, "agents_existed": agents.exists(), "block": block,
                "files": {name: digest(data) for name, data in files.items()}}
    created = []
    made_dirs = []
    try:
        for name, data in files.items():
            target = local_path(root, name)
            for directory in reversed(list(target.parents)):
                if directory != root and root in directory.parents and not directory.exists():
                    directory.mkdir()
                    made_dirs.append(directory)
            with target.open("xb") as file:
                file.write(data)
            created.append(target)
        agents.write_bytes(original + block.encode())
        (package / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    except Exception:
        if agents.exists() and agents.read_bytes() == original + block.encode():
            if manifest["agents_existed"]:
                agents.write_bytes(original)
            else:
                agents.unlink()
        for path in reversed(created):
            path.unlink()
        for directory in reversed(made_dirs):
            if not any(directory.iterdir()):
                directory.rmdir()
        raise
    print("Đã cài workflow vào: " + str(root))
    print("Chạy: python3 " + str(package / "run.py"))


def configure(root, args):
    manifest = checked_manifest(root)
    path = root / ".agent-tree/settings.json"
    settings = json.loads(path.read_text())
    edits = {}
    for role in DEFAULT_MODELS:
        model = getattr(args, role + "_model")
        effort = getattr(args, role + "_effort")
        if model:
            if not re.fullmatch(r"[A-Za-z0-9_.:/-]+", model):
                raise ValueError("Model ID không hợp lệ: " + model)
            settings[role + "_model"] = model
        if effort:
            settings[role + "_effort"] = effort
        if role != "main" and (model or effort):
            name = ".codex/agents/agent_tree_" + role + ".toml"
            text = (root / name).read_text()
            text = re.sub(r'^model = ".*"$', 'model = ' + json.dumps(settings[role + "_model"]), text, flags=re.M)
            text = re.sub(r'^model_reasoning_effort = ".*"$', 'model_reasoning_effort = ' + json.dumps(settings[role + "_effort"]), text, flags=re.M)
            edits[name] = text.encode()
    if args.max_agents:
        settings["max_agents"] = args.max_agents
    edits[".agent-tree/settings.json"] = (json.dumps(settings, indent=2) + "\n").encode()
    old = {name: (root / name).read_bytes() for name in edits}
    manifest_path = root / ".agent-tree/manifest.json"
    old_manifest = manifest_path.read_bytes()
    try:
        for name, data in edits.items():
            (root / name).write_bytes(data)
            manifest["files"][name] = digest(data)
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    except OSError:
        for name, data in old.items():
            (root / name).write_bytes(data)
        manifest_path.write_bytes(old_manifest)
        raise
    print(json.dumps(settings, indent=2))
    print("Cấu hình áp dụng từ lần chạy tiếp theo. Model cần được tài khoản Codex hỗ trợ.")


def uninstall(root):
    package = local_path(root, ".agent-tree")
    if not package.exists():
        print("Project chưa cài Agent Tree.")
        return
    manifest = checked_manifest(root)
    agents = local_path(root, "AGENTS.md")
    remaining = agents.read_bytes().replace(manifest["block"].encode(), b"", 1)
    if remaining or manifest["agents_existed"]:
        agents.write_bytes(remaining)
    else:
        agents.unlink()
    for name in manifest["files"]:
        local_path(root, name).unlink()
    (package / "manifest.json").unlink()
    for directory in (root / ".codex/agents", root / ".codex", package):
        if directory.is_dir() and not any(directory.iterdir()):
            directory.rmdir()
    print("Đã gỡ workflow; giữ nguyên nội dung khác của project.")


def main():
    parser = argparse.ArgumentParser(description="Cài/gỡ Agent Tree cho một project; không sửa cấu hình toàn cục.")
    parser.add_argument("action", choices=("install", "uninstall", "configure", "show"))
    parser.add_argument("--project", required=True, type=Path)
    for role in DEFAULT_MODELS:
        parser.add_argument("--" + role + "-model")
        parser.add_argument("--" + role + "-effort", choices=("low", "medium", "high", "xhigh", "max", "ultra"))
    parser.add_argument("--max-agents", type=int, choices=range(1, 7))
    args = parser.parse_args()
    root = args.project.expanduser().resolve()
    home = Path.home().resolve()
    try:
        if not root.is_dir() or root in (home, Path(root.anchor)) or root == home / ".codex" or home / ".codex" in root.parents:
            raise ValueError("Hãy chọn thư mục project hiện có, không chọn thư mục home hoặc cấu hình Codex toàn cục.")
        if args.action == "install":
            install(root, args)
        elif args.action == "uninstall":
            uninstall(root)
        elif args.action == "configure":
            configure(root, args)
        else:
            checked_manifest(root)
            print((root / ".agent-tree/settings.json").read_text())
        return 0
    except (OSError, ValueError, KeyError) as error:
        print("Không thể hoàn tất: " + str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
