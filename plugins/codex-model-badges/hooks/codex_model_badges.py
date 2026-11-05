#!/usr/bin/env python3
"""Keep the native titles of opened, local Codex threads in sync with model settings."""

import errno
import json
import os
from pathlib import Path
from queue import Empty, Queue
import re
import shutil
import subprocess
import sys
import tempfile
from threading import Thread
import time
import uuid

if os.name == "nt":
    import msvcrt
else:
    import fcntl


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
            cwd=Path.home().anchor,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        self.messages = Queue()
        self.reader = Thread(target=self.read_messages, daemon=True)
        self.reader.start()
        self.counter = 0
        try:
            self.call("initialize", {"clientInfo": {"name": "codex_model_badges", "version": "0.2.0"}})
            self.send({"method": "initialized", "params": {}})
        except Exception:
            self.close()
            raise

    def send(self, message):
        self.proc.stdin.write(json.dumps(message, ensure_ascii=True).encode() + b"\n")
        self.proc.stdin.flush()

    def read_messages(self):
        try:
            with self.proc.stdout as stream:
                for line in stream:
                    message = json.loads(line)
                    if isinstance(message, dict) and "id" in message and "method" not in message:
                        self.messages.put(message)
        except (OSError, ValueError) as error:
            self.messages.put(error)
        finally:
            self.messages.put(EOFError("local app-server closed"))

    def call(self, method, params):
        self.counter += 1
        request_id = self.counter
        self.send({"id": request_id, "method": method, "params": params})
        deadline = time.monotonic() + 5
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("local app-server response timed out")
            try:
                message = self.messages.get(timeout=remaining)
            except Empty:
                raise TimeoutError("local app-server response timed out") from None
            if isinstance(message, Exception):
                raise message
            if message.get("id") != request_id:
                continue
            if "error" in message:
                raise RpcError(message["error"].get("code"))
            return message.get("result", {})

    def close(self):
        try:
            self.proc.stdin.close()
        except OSError:
            pass
        try:
            self.proc.wait(timeout=1)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait()
        self.reader.join(timeout=1)


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
        try:
            self.settings = rollout_settings(self.path)
        except OSError:
            return False
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
    if os.name == "nt":
        native = shutil.which("codex.exe")
        if native:
            return native
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            bin_dir = Path(local_app_data) / "Programs" / "OpenAI" / "Codex" / "bin"
            installed = shutil.which("codex", path=str(bin_dir))
            if installed:
                return installed
        return shutil.which("codex")
    bundled = Path("/Applications/ChatGPT.app/Contents/Resources/codex-cli/CodexCLI.app/Contents/MacOS/codex")
    return str(bundled) if os.access(bundled, os.X_OK) else shutil.which("codex")


def try_watcher_lock(lock):
    try:
        if os.name == "nt":
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as error:
        if error.errno not in {errno.EACCES, errno.EAGAIN, errno.EDEADLK}:
            raise
        return False
    return True


def registered_threads(data):
    for entry in data.glob("*.watch"):
        if not is_thread_id(entry.stem):
            continue
        try:
            yield entry, entry.stat().st_mtime
        except FileNotFoundError:
            continue


def watch(data):
    codex = codex_path()
    if not codex:
        return
    installed_script = Path(__file__).resolve()
    while installed_script.is_file():
        with (data / "watch.lock").open("ab") as lock:
            if not try_watcher_lock(lock):
                return
            watch_active_threads(data, codex, installed_script)
        # A hook can register a thread while the old watcher is exiting and still owns the lock.
        cutoff = time.time() - IDLE_EXPIRY
        if not any(stamp >= cutoff for _, stamp in registered_threads(data)):
            return


def watch_active_threads(data, codex, installed_script):
    server = None
    threads = {}
    try:
        while installed_script.is_file():
            now = time.time()
            live = set()
            for entry, stamp in registered_threads(data):
                thread_id = entry.stem
                target = threads.setdefault(thread_id, WatchedThread(stamp))
                target.last_activity = max(target.last_activity, stamp)
                if now - target.last_activity > IDLE_EXPIRY:
                    continue
                live.add(thread_id)
                try:
                    registration = json.loads(entry.read_bytes())
                except (OSError, ValueError):
                    continue
                if not isinstance(registration, dict):
                    continue
                try:
                    if server is None:
                        server = AppServer(codex)
                    target.sync(server, thread_id, now, normalized_slug(registration.get("model")))
                except RpcError:
                    # The first turn may not have materialized on disk yet.
                    target.next_read = now + POLL_SECONDS
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


def update_registration(entry, temp=None):
    # Windows can briefly deny replacement or removal while the watcher has the file open.
    for attempt in range(4):
        try:
            if temp is None:
                entry.unlink(missing_ok=True)
            else:
                temp.replace(entry)
            return
        except PermissionError:
            if os.name != "nt" or attempt == 3:
                raise
            time.sleep(0.05)


def on_hook(data, event):
    thread_id = event.get("session_id")
    if not is_thread_id(thread_id):
        return
    data.mkdir(mode=0o700, parents=True, exist_ok=True)
    entry = data / (thread_id + ".watch")
    if event.get("hook_event_name") == "SessionEnd":
        update_registration(entry)
        return
    with tempfile.NamedTemporaryFile(dir=data, delete=False) as stream:
        temp = Path(stream.name)
        stream.write(json.dumps({"model": normalized_slug(event.get("model"))}).encode())
    try:
        update_registration(entry, temp)
    finally:
        temp.unlink(missing_ok=True)
    with (data / "watch.lock").open("ab") as lock:
        if not try_watcher_lock(lock):
            return
    options = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {"start_new_session": True}
    subprocess.Popen(
        [sys.executable, str(Path(__file__).resolve()), "--watch", str(data)],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        **options,
    )


def main():
    if len(sys.argv) == 3 and sys.argv[1] == "--watch":
        watch(Path(sys.argv[2]))
    elif os.environ.get("PLUGIN_DATA"):
        try:
            event = json.load(sys.stdin.buffer)
            if isinstance(event, dict):
                on_hook(Path(os.environ["PLUGIN_DATA"]), event)
        except (OSError, ValueError):
            # A badge failure must never prevent the user's turn from running.
            pass


if __name__ == "__main__":
    main()
