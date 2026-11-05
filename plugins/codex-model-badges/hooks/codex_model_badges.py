#!/usr/bin/env python3
"""Keep the native titles of opened, local Codex threads in sync with model settings."""

import fcntl
import json
import os
from pathlib import Path
import re
import selectors
import shutil
import subprocess
import sys
import tempfile
import time
import uuid


ICONS = {
    "gpt-6.1-sol": "☀️",
    "gpt-6.1-terra": "🌍",
    "gpt-6-astra": "✨",
    "gpt-6-sol": "🌞",
    "gpt-6-luna": "🌙",
    "gpt-5.6-sol": "🟠",
    "gpt-5.6-terra": "🟢",
    "gpt-5.5": "🟣",
    "gpt-5.4": "🔵",
    "gpt-5.4-mini": "🔷",
    "gpt-5.3-codex": "🛠️",
    "gpt-5.2-codex": "🔧",
}
OTHER_MODEL = "🧩"
SPEED_ICONS = {"fast": "⚡", "priority": "⚡", "ultrafast": "🚀"}
SEPARATOR = "\u2009"
PREFIX = re.compile(
    r"^(?:" + "|".join(map(re.escape, (*ICONS.values(), OTHER_MODEL)))
    + r")(?: [⚡🚀])?" + SEPARATOR
)
POLL_SECONDS = 2
TITLE_POLL_SECONDS = 15
IDLE_EXPIRY = 60 * 60
TAIL_BYTES = 1024 * 1024
PLACEHOLDERS = {"new chat", "new thread", "新建会话", "新对话", "新建对话"}


def normalized_slug(value):
    if isinstance(value, str) and re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9._-]{0,95}", value):
        return value.lower()
    return None


def title_with_badge(title, model, speed, speed_known=True):
    previous = PREFIX.match(title)
    base = title[previous.end():] if previous else title
    icon = ICONS.get(model, OTHER_MODEL)
    speed_icon = SPEED_ICONS.get(speed)
    if not speed_known and previous and previous.group().startswith(icon + " "):
        speed_icon = previous.group().removesuffix(SEPARATOR).split(" ")[-1]
    prefix = f"{icon} {speed_icon}" if speed_icon else icon
    return prefix + SEPARATOR + base


def rollout_settings(path):
    """Read the newest usable checkpoint near the end of a saved rollout."""
    with path.open("rb") as stream:
        size = stream.seek(0, os.SEEK_END)
        offset = max(0, size - TAIL_BYTES)
        stream.seek(max(0, offset - 1))
        lines = stream.read(TAIL_BYTES + bool(offset)).split(b"\n")
        if offset:
            lines = lines[1:]
    model = None
    for line in reversed(lines):
        try:
            entry = json.loads(line)
        except (ValueError, UnicodeError):
            continue
        if not isinstance(entry, dict) or not isinstance(entry.get("payload"), dict):
            continue
        payload = entry["payload"]
        if entry.get("type") == "turn_context":
            model = model or normalized_slug(payload.get("model"))
        if entry.get("type") == "event_msg" and payload.get("type") == "thread_settings_applied":
            settings = payload.get("thread_settings")
            if not isinstance(settings, dict):
                continue
            checkpoint_model = normalized_slug(settings.get("model"))
            if not checkpoint_model:
                continue
            if model and model != checkpoint_model:
                return model, None, False
            return checkpoint_model, normalized_slug(settings.get("service_tier")), "service_tier" in settings
    return model, None, False


class RpcError(Exception):
    pass


class AppServer:
    """Local JSONL client. It reads metadata and sets titles without starting turns."""

    def __init__(self, codex):
        self.proc = subprocess.Popen(
            [codex, "app-server", "--disable", "hooks"],
            cwd="/",
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            bufsize=0,
        )
        self.reader = selectors.DefaultSelector()
        self.reader.register(self.proc.stdout, selectors.EVENT_READ)
        self.buffer = bytearray()
        self.counter = 0
        try:
            self.call("initialize", {"clientInfo": {"name": "codex_model_badges", "version": "0.1.0"}})
            self.send({"method": "initialized", "params": {}})
        except Exception:
            self.close()
            raise

    def send(self, message):
        self.proc.stdin.write(json.dumps(message, ensure_ascii=True).encode() + b"\n")

    def call(self, method, params):
        self.counter += 1
        request_id = self.counter
        self.send({"id": request_id, "method": method, "params": params})
        deadline = time.monotonic() + 5
        while True:
            while b"\n" in self.buffer:
                line, _, self.buffer = self.buffer.partition(b"\n")
                message = json.loads(line)
                if message.get("id") != request_id:
                    continue
                if "error" in message:
                    raise RpcError(message["error"].get("code"))
                return message.get("result", {})
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not self.reader.select(remaining):
                raise TimeoutError("local app-server response timed out")
            chunk = os.read(self.proc.stdout.fileno(), 65536)
            if not chunk:
                raise EOFError("local app-server closed")
            self.buffer.extend(chunk)

    def close(self):
        self.reader.close()
        self.proc.stdin.close()
        try:
            self.proc.wait(timeout=1)
        except subprocess.TimeoutExpired:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=1)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait()
        self.proc.stdout.close()


class WatchedThread:
    def __init__(self, now):
        self.last_activity = now
        self.next_read = 0
        self.path = None
        self.fingerprint = None
        self.settings = (None, None, False)

    def file_changed(self, now):
        if not self.path:
            return False
        try:
            stat = self.path.stat()
        except OSError:
            return False
        current = (self.path, stat.st_ino, stat.st_size, stat.st_mtime_ns)
        if current == self.fingerprint:
            return False
        previous_settings = self.settings
        self.settings = rollout_settings(self.path)
        self.fingerprint = current
        self.last_activity = now
        return self.settings != previous_settings

    def sync(self, server, thread_id, now, hook_model):
        changed = self.file_changed(now)
        if not changed and now < self.next_read:
            return
        self.next_read = now + TITLE_POLL_SECONDS
        thread = server.call("thread/read", {"threadId": thread_id, "includeTurns": False}).get("thread", {})
        if thread.get("id") != thread_id or thread.get("ephemeral") or thread.get("parentThreadId"):
            return
        path = thread.get("path")
        if isinstance(path, str) and path.endswith(".jsonl"):
            self.path = Path(path)
            self.file_changed(now)
        title = thread.get("name")
        if not isinstance(title, str) or not title.strip() or title.strip().lower() in PLACEHOLDERS:
            self.next_read = now + POLL_SECONDS
            return
        saved_model, speed, speed_known = self.settings
        model = saved_model or normalized_slug(thread.get("model")) or hook_model
        if not model:
            return
        desired = title_with_badge(title, model, speed, speed_known)
        if desired != title:
            server.call("thread/name/set", {"threadId": thread_id, "name": desired})


def is_thread_id(value):
    try:
        return isinstance(value, str) and str(uuid.UUID(value)) == value
    except ValueError:
        return False


def codex_path():
    bundled = Path("/Applications/ChatGPT.app/Contents/Resources/codex-cli/CodexCLI.app/Contents/MacOS/codex")
    return str(bundled) if os.access(bundled, os.X_OK) else shutil.which("codex")


def watch(data, lock_fd):
    codex = codex_path()
    if not codex:
        return
    server = None
    threads = {}
    installed_script = Path(__file__).resolve()
    try:
        while installed_script.is_file():
            now = time.time()
            entries = list(data.glob("*.watch"))
            if not entries:
                return
            live = set()
            for entry in entries:
                thread_id = entry.stem
                if not is_thread_id(thread_id):
                    continue
                try:
                    stamp = entry.stat().st_mtime
                    registration = json.loads(entry.read_text())
                    target = threads.setdefault(thread_id, WatchedThread(stamp))
                    target.last_activity = max(target.last_activity, stamp)
                    if now - target.last_activity > IDLE_EXPIRY:
                        continue
                    live.add(thread_id)
                    if server is None:
                        server = AppServer(codex)
                    target.sync(server, thread_id, now, normalized_slug(registration.get("model")))
                except RpcError:
                    # The first turn may not have materialized on disk yet.
                    if thread_id in threads:
                        threads[thread_id].next_read = now + POLL_SECONDS
                except (OSError, EOFError, ValueError):
                    if server:
                        server.close()
                        server = None
                    break
            threads = {thread_id: threads[thread_id] for thread_id in live}
            if not live:
                return
            time.sleep(POLL_SECONDS)
    finally:
        if server:
            server.close()
        os.close(lock_fd)


def on_hook(data, event):
    thread_id = event.get("session_id")
    if not is_thread_id(thread_id):
        return
    data.mkdir(mode=0o700, parents=True, exist_ok=True)
    entry = data / (thread_id + ".watch")
    if event.get("hook_event_name") == "SessionEnd":
        entry.unlink(missing_ok=True)
        return
    with tempfile.NamedTemporaryFile(dir=data, delete=False) as stream:
        temp = Path(stream.name)
        stream.write(json.dumps({"model": normalized_slug(event.get("model"))}).encode())
    temp.replace(entry)
    with (data / "watch.lock").open("ab") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve()), "--watch", str(data), str(lock.fileno())],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            pass_fds=(lock.fileno(),),
        )


def main():
    if len(sys.argv) == 4 and sys.argv[1] == "--watch":
        watch(Path(sys.argv[2]), int(sys.argv[3]))
    elif os.environ.get("PLUGIN_DATA"):
        try:
            event = json.load(sys.stdin)
            if isinstance(event, dict):
                on_hook(Path(os.environ["PLUGIN_DATA"]), event)
        except (OSError, ValueError):
            # A badge failure must never prevent the user's turn from running.
            pass


if __name__ == "__main__":
    main()
