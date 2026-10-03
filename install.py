#!/usr/bin/env python3
"""Project-local installation. Python 3.9+, standard library only."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

SOURCE = Path(__file__).resolve().parent
ROLES = ("worker", "explorer", "researcher", "astra")
DEFAULT_MODELS = {"main": "gpt-6-sol", "worker": "gpt-6-sol", "explorer": "gpt-6-luna",
                  "researcher": "gpt-6-luna", "astra": "gpt-6-astra"}
JEV_DEFAULTS = {"command": "jev", "model": "jev-latest", "confidence": .85,
                "probability": .85, "margin": .20, "timeout_ms": 15000, "max_retries": 1}
def remove_hooks(root, manifest):
    if not manifest.get("hook_groups"):
        return
    path = local_path(root, ".codex/hooks.json")
    value = json.loads(path.read_text())
    for event, group in manifest["hook_groups"].items():
        value["hooks"][event].remove(group)
        if not value["hooks"][event]:
            del value["hooks"][event]
    if not value["hooks"]:
        del value["hooks"]
    original = manifest.get("hooks_original")
    original_value = json.loads(original) if original is not None else {}
    # Preserve original empty structures and formatting if there are no later additions.
    normalized = dict(original_value)
    if normalized.get("hooks") == {}:
        normalized.pop("hooks")
    if value == normalized:
        if original is None:
            path.unlink()
        else:
            path.write_text(original)
    else:
        path.write_text(json.dumps(value, indent=2) + "\n")


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
    if manifest.get("hook_groups"):
        hooks = json.loads(local_path(root, ".codex/hooks.json").read_text()).get("hooks", {})
        for event, group in manifest["hook_groups"].items():
            if hooks.get(event, []).count(group) != 1:
                raise ValueError("Hook Agent Tree đã thay đổi; không tự ghi đè: " + event)
    for name, expected in manifest["files"].items():
        file = local_path(root, name)
        if not file.is_file() or digest(file.read_bytes()) != expected:
            raise ValueError("File workflow đã thay đổi hoặc bị thiếu; giữ nguyên để tránh mất dữ liệu: " + name)
    if manifest.get("block"):
        agents = local_path(root, "AGENTS.md")
        data = agents.read_bytes()
        if data.count(manifest["block"].encode()) != 1:
            raise ValueError("Khối Agent Tree trong AGENTS.md đã thay đổi; hãy khôi phục khối trước khi gỡ.")
    return manifest


def install(root, args):
    settings = {role + "_model": getattr(args, role + "_model") or model
                for role, model in DEFAULT_MODELS.items()}
    settings.update({role + "_effort": getattr(args, role + "_effort") or ("high" if role == "main" else "medium") for role in DEFAULT_MODELS})
    settings["max_agents"] = args.max_agents or 6
    settings["jev"] = dict(JEV_DEFAULTS)
    for key in JEV_DEFAULTS:
        value = getattr(args, "jev_" + key, None)
        if value is not None:
            settings["jev"][key] = value
    for key, value in settings.items():
        if key.endswith("_model") and not re.fullmatch(r"[A-Za-z0-9_.:/-]+", value):
            raise ValueError("Model ID không hợp lệ: " + value)
    package = local_path(root, ".agent-tree")
    if (package / "manifest.json").exists():
        checked_manifest(root)
        if json.loads((package / "settings.json").read_text()) != settings:
            raise ValueError("Project đã cài với tùy chọn khác. Gỡ bản cũ trước khi cài lại.")
        print("Workflow đã được cài; không thay đổi file.")
        return
    files = {
        ".agent-tree/.gitignore": b"logs/\n__pycache__/\n",
        ".agent-tree/install.py": Path(__file__).read_bytes(),
        ".agent-tree/settings.json": (json.dumps(settings, indent=2) + "\n").encode(),
        ".codex/skills/agent-tree/SKILL.md": (SOURCE / "templates/skill/SKILL.md").read_bytes(),
        ".codex/skills/agent-tree/agents/openai.yaml": (SOURCE / "templates/skill/agents/openai.yaml").read_bytes(),
        ".codex/skills/agent-tree/references/workflow.md": (SOURCE / "templates/workflow.md").read_bytes(),
    }
    for name in ("runtime.py", "observer.py", "control.py"):
        files[".agent-tree/" + name] = (SOURCE / "templates" / name).read_bytes()
    for role in ROLES:
        relative = ".codex/agents/agent_tree_" + role + ".toml"
        template = (SOURCE / "templates/agents" / ("agent_tree_" + role + ".toml")).read_text()
        template = re.sub(r'^model = ".*"$', 'model = ' + json.dumps(settings[role + "_model"]), template, flags=re.M)
        template = re.sub(r'^model_reasoning_effort = ".*"$', 'model_reasoning_effort = ' + json.dumps(settings[role + "_effort"]), template, flags=re.M)
        files[relative] = template.encode()
    for name in files:
        if local_path(root, name).exists():
            raise ValueError("Không ghi đè file có sẵn: " + name)
    manifest = {"version": 4, "files": {name: digest(data) for name, data in files.items()}}
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
        (package / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    except Exception:
        for path in reversed(created):
            path.unlink()
        for directory in reversed(made_dirs):
            if not any(directory.iterdir()):
                directory.rmdir()
        raise
    print("Đã cài workflow vào: " + str(root))
    print("Chỉ kích hoạt khi gọi $agent-tree trong project; không thêm hook hoặc quy tắc AGENTS.md thường trực.")


def configure(root, args):
    manifest = checked_manifest(root)
    path = root / ".agent-tree/settings.json"
    settings = json.loads(path.read_text())
    settings.setdefault("jev", dict(JEV_DEFAULTS))
    for key in JEV_DEFAULTS:
        value = getattr(args, "jev_" + key, None)
        if value is not None:
            settings["jev"][key] = value
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
    remove_hooks(root, manifest)
    if manifest.get("block"):
        agents = local_path(root, "AGENTS.md")
        remaining = agents.read_bytes().replace(manifest["block"].encode(), b"", 1)
        if remaining or manifest["agents_existed"]:
            agents.write_bytes(remaining)
        else:
            agents.unlink()
    for name in manifest["files"]:
        local_path(root, name).unlink()
    (package / "manifest.json").unlink()
    for directory in (root / ".codex/skills/agent-tree/agents", root / ".codex/skills/agent-tree/references",
                      root / ".codex/skills/agent-tree", root / ".codex/skills", root / ".codex/agents", root / ".codex", package):
        if directory.is_dir() and not any(directory.iterdir()):
            directory.rmdir()
    print("Đã gỡ workflow; giữ nguyên nội dung khác của project.")


def main():
    parser = argparse.ArgumentParser(description="Cài/gỡ Agent Tree cho một project; không sửa cấu hình toàn cục.")
    parser.add_argument("action", choices=("install", "uninstall", "configure", "show", "upgrade"))
    parser.add_argument("--project", required=True, type=Path)
    for role in DEFAULT_MODELS:
        parser.add_argument("--" + role + "-model")
        parser.add_argument("--" + role + "-effort", choices=("low", "medium", "high", "xhigh", "max", "ultra"))
    parser.add_argument("--max-agents", type=int, choices=range(1, 7))
    parser.add_argument("--jev-model")
    parser.add_argument("--jev-command")
    for key in ("confidence", "probability", "margin"):
        parser.add_argument("--jev-" + key, type=float)
    args = parser.parse_args()
    root = args.project.expanduser().resolve()
    home = Path.home().resolve()
    try:
        for key in ("confidence", "probability", "margin"):
            value = getattr(args, "jev_" + key)
            if value is not None and not 0 <= value <= 1:
                raise ValueError("Ngưỡng Jev phải nằm trong khoảng 0 đến 1.")
        if not root.is_dir() or root in (home, Path(root.anchor)) or root == home / ".codex" or home / ".codex" in root.parents:
            raise ValueError("Hãy chọn thư mục project hiện có, không chọn thư mục home hoặc cấu hình Codex toàn cục.")
        if args.action == "install":
            install(root, args)
        elif args.action == "uninstall":
            uninstall(root)
        elif args.action == "configure":
            configure(root, args)
        elif args.action == "upgrade":
            checked_manifest(root)
            previous = json.loads((root / ".agent-tree/settings.json").read_text())
            for key, value in previous.items():
                if key == "jev":
                    for name, setting in value.items():
                        if getattr(args, "jev_" + name, None) is None:
                            setattr(args, "jev_" + name, setting)
                elif getattr(args, key, None) is None:
                    setattr(args, key, value)
            # Validate sources before removing the old installation.
            for name in ("runtime.py", "observer.py", "control.py", "workflow.md", "skill/SKILL.md", "skill/agents/openai.yaml"):
                (SOURCE / "templates" / name).read_bytes()
            uninstall(root)
            install(root, args)
        else:
            checked_manifest(root)
            print((root / ".agent-tree/settings.json").read_text())
        return 0
    except (OSError, ValueError, KeyError) as error:
        print("Không thể hoàn tất: " + str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
