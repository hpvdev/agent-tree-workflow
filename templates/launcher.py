"""Run a project-scoped Codex request without a separate Watch interface."""
from datetime import datetime
import json
import os
import queue
import subprocess
import threading

from control import finish, finalize_retro
from observer import Observer
from runtime import Journal


def trace(command, root):
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    journal = Journal(root, stamp)
    observer = Observer(journal)
    command = list(command)
    command[-1] += ("\n\nAgent Tree run ID: " + stamp + ". Follow project AGENTS.md. "
                    "Use python3 .agent-tree/control.py --run-id " + stamp + " for checkpoints, forks and finish. "
                    "Use native Astra and Jev as specified; never self-attest a checkpoint.")
    messages = queue.Queue()

    def read_output(stream):
        try:
            for line in stream:
                messages.put(line)
        finally:
            messages.put(None)

    final = ""
    completed = False
    failed = False
    cursor = 0
    path = journal.directory / "codex.jsonl"
    environment = dict(os.environ, AGENT_TREE_RUN=stamp)
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
                    log.write(line)
                    log.flush()
                    try:
                        event = json.loads(line)
                    except ValueError:
                        event = None
                    if isinstance(event, dict):
                        if event.get("type") == "thread.started":
                            journal.put("root_thread", event["thread_id"])
                        elif event.get("type") == "item.completed" and (event.get("item") or {}).get("type") == "agent_message":
                            final = event["item"].get("text", final)
                        completed |= event.get("type") == "turn.completed"
                        failed |= event.get("type") in ("turn.failed", "error")
                        timeline.write(json.dumps(event, ensure_ascii=False) + "\n")
                if journal.get("transport") != "hooks":
                    observer.poll()
                for event in journal.events(cursor):
                    cursor = event["seq"]
                    timeline.write(json.dumps(event, ensure_ascii=False) + "\n")
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
            reader.join(timeout=2)
            process.stdout.close()
        if journal.get("transport") != "hooks":
            observer.poll()
        audit = finish(journal)
        if result == 0 and not audit["passed"]:
            result = 2
        if result == 0 and (failed or not completed):
            result = 1
        finalize_retro(journal, result == 0)
        for event in journal.events(cursor):
            timeline.write(json.dumps(event, ensure_ascii=False) + "\n")
    journal.close()
    if final:
        print(final)
    print("Nhật ký: " + str(journal.directory))
    if result:
        print("Lượt này chưa hoàn tất đầy đủ; xem nhật ký trong thư mục trên.")
    return result
