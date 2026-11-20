#!/usr/bin/env python3
"""Keep the native titles of opened, local Codex threads in sync with model settings."""

import bisect
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

# Unicode 18.0.0 emoji properties, generated from emoji-data.txt.
# A leading cluster counts as an emoji only in emoji presentation: default
# Emoji_Presentation, or Extended_Pictographic plus U+FE0F / a skin tone.
# Bare text-default symbols such as ©, ™, or # are not treated as leading emoji.
_EP_RANGES = (
    (0xA9, 0xA9), (0xAE, 0xAE), (0x203C, 0x203C), (0x2049, 0x2049), (0x2122, 0x2122),
    (0x2139, 0x2139), (0x2194, 0x2199), (0x21A9, 0x21AA), (0x231A, 0x231B), (0x2328, 0x2328),
    (0x23CF, 0x23CF), (0x23E9, 0x23F3), (0x23F8, 0x23FA), (0x24C2, 0x24C2), (0x25AA, 0x25AB),
    (0x25B6, 0x25B6), (0x25C0, 0x25C0), (0x25FB, 0x25FE), (0x2600, 0x2604), (0x260E, 0x260E),
    (0x2611, 0x2611), (0x2614, 0x2615), (0x2618, 0x2618), (0x261D, 0x261D), (0x2620, 0x2620),
    (0x2622, 0x2623), (0x2626, 0x2626), (0x262A, 0x262A), (0x262E, 0x262F), (0x2638, 0x263A),
    (0x2640, 0x2640), (0x2642, 0x2642), (0x2648, 0x2653), (0x265F, 0x2660), (0x2663, 0x2663),
    (0x2665, 0x2666), (0x2668, 0x2668), (0x267B, 0x267B), (0x267E, 0x267F), (0x2692, 0x2697),
    (0x2699, 0x2699), (0x269B, 0x269C), (0x26A0, 0x26A1), (0x26A7, 0x26A7), (0x26AA, 0x26AB),
    (0x26B0, 0x26B1), (0x26BD, 0x26BE), (0x26C4, 0x26C5), (0x26C8, 0x26C8), (0x26CE, 0x26CF),
    (0x26D1, 0x26D1), (0x26D3, 0x26D4), (0x26E9, 0x26EA), (0x26F0, 0x26F5), (0x26F7, 0x26FA),
    (0x26FD, 0x26FD), (0x2702, 0x2702), (0x2705, 0x2705), (0x2708, 0x270D), (0x270F, 0x270F),
    (0x2712, 0x2712), (0x2714, 0x2714), (0x2716, 0x2716), (0x271D, 0x271D), (0x2721, 0x2721),
    (0x2728, 0x2728), (0x2733, 0x2734), (0x2744, 0x2744), (0x2747, 0x2747), (0x274C, 0x274C),
    (0x274E, 0x274E), (0x2753, 0x2755), (0x2757, 0x2757), (0x2763, 0x2764), (0x2795, 0x2797),
    (0x27A1, 0x27A1), (0x27B0, 0x27B0), (0x27BF, 0x27BF), (0x2934, 0x2935), (0x2B05, 0x2B07),
    (0x2B1B, 0x2B1C), (0x2B50, 0x2B50), (0x2B55, 0x2B55), (0x3030, 0x3030), (0x303D, 0x303D),
    (0x3297, 0x3297), (0x3299, 0x3299), (0x1F004, 0x1F004), (0x1F02C, 0x1F02F), (0x1F094, 0x1F09F),
    (0x1F0AF, 0x1F0B0), (0x1F0C0, 0x1F0C0), (0x1F0CF, 0x1F0D0), (0x1F0F6, 0x1F0FF), (0x1F170, 0x1F171),
    (0x1F17E, 0x1F17F), (0x1F18E, 0x1F18E), (0x1F191, 0x1F19A), (0x1F1AF, 0x1F1E5), (0x1F201, 0x1F20F),
    (0x1F21A, 0x1F21A), (0x1F22F, 0x1F22F), (0x1F232, 0x1F23A), (0x1F23C, 0x1F23F), (0x1F249, 0x1F25F),
    (0x1F266, 0x1F321), (0x1F324, 0x1F393), (0x1F396, 0x1F397), (0x1F399, 0x1F39B), (0x1F39E, 0x1F3F0),
    (0x1F3F3, 0x1F3F5), (0x1F3F7, 0x1F3FA), (0x1F400, 0x1F4FD), (0x1F4FF, 0x1F53D), (0x1F549, 0x1F54E),
    (0x1F550, 0x1F567), (0x1F56F, 0x1F570), (0x1F573, 0x1F57A), (0x1F587, 0x1F587), (0x1F58A, 0x1F58D),
    (0x1F590, 0x1F590), (0x1F595, 0x1F596), (0x1F5A4, 0x1F5A5), (0x1F5A8, 0x1F5A8), (0x1F5B1, 0x1F5B2),
    (0x1F5BC, 0x1F5BC), (0x1F5C2, 0x1F5C4), (0x1F5D1, 0x1F5D3), (0x1F5DC, 0x1F5DE), (0x1F5E1, 0x1F5E1),
    (0x1F5E3, 0x1F5E3), (0x1F5E8, 0x1F5E8), (0x1F5EF, 0x1F5EF), (0x1F5F3, 0x1F5F3), (0x1F5FA, 0x1F64F),
    (0x1F680, 0x1F6C5), (0x1F6CB, 0x1F6D2), (0x1F6D5, 0x1F6E5), (0x1F6E9, 0x1F6E9), (0x1F6EB, 0x1F6F0),
    (0x1F6F3, 0x1F6FF), (0x1F7DC, 0x1F7F0), (0x1F80C, 0x1F80F), (0x1F848, 0x1F84F), (0x1F85A, 0x1F85F),
    (0x1F888, 0x1F88F), (0x1F8AE, 0x1F8AF), (0x1F8BC, 0x1F8BF), (0x1F8C2, 0x1F8CF), (0x1F8D9, 0x1F8FF),
    (0x1F90C, 0x1F93A), (0x1F93C, 0x1F945), (0x1F947, 0x1F9FF), (0x1FA58, 0x1FA5F), (0x1FA6E, 0x1FAFF),
    (0x1FC00, 0x1FFFD),
)
_EMOJI_PRESENTATION_RANGES = (
    (0x231A, 0x231B), (0x23E9, 0x23EC), (0x23F0, 0x23F0), (0x23F3, 0x23F3), (0x25FD, 0x25FE),
    (0x2614, 0x2615), (0x2648, 0x2653), (0x267F, 0x267F), (0x2693, 0x2693), (0x26A1, 0x26A1),
    (0x26AA, 0x26AB), (0x26BD, 0x26BE), (0x26C4, 0x26C5), (0x26CE, 0x26CE), (0x26D4, 0x26D4),
    (0x26EA, 0x26EA), (0x26F2, 0x26F3), (0x26F5, 0x26F5), (0x26FA, 0x26FA), (0x26FD, 0x26FD),
    (0x2705, 0x2705), (0x270A, 0x270B), (0x2728, 0x2728), (0x274C, 0x274C), (0x274E, 0x274E),
    (0x2753, 0x2755), (0x2757, 0x2757), (0x2795, 0x2797), (0x27B0, 0x27B0), (0x27BF, 0x27BF),
    (0x2B1B, 0x2B1C), (0x2B50, 0x2B50), (0x2B55, 0x2B55), (0x1F004, 0x1F004), (0x1F0CF, 0x1F0CF),
    (0x1F18E, 0x1F18E), (0x1F191, 0x1F19A), (0x1F1E6, 0x1F1FF), (0x1F201, 0x1F201), (0x1F21A, 0x1F21A),
    (0x1F22F, 0x1F22F), (0x1F232, 0x1F236), (0x1F238, 0x1F23A), (0x1F250, 0x1F251), (0x1F300, 0x1F320),
    (0x1F32D, 0x1F335), (0x1F337, 0x1F37C), (0x1F37E, 0x1F393), (0x1F3A0, 0x1F3CA), (0x1F3CF, 0x1F3D3),
    (0x1F3E0, 0x1F3F0), (0x1F3F4, 0x1F3F4), (0x1F3F8, 0x1F43E), (0x1F440, 0x1F440), (0x1F442, 0x1F4FC),
    (0x1F4FF, 0x1F53D), (0x1F54B, 0x1F54E), (0x1F550, 0x1F567), (0x1F57A, 0x1F57A), (0x1F595, 0x1F596),
    (0x1F5A4, 0x1F5A4), (0x1F5FB, 0x1F64F), (0x1F680, 0x1F6C5), (0x1F6CC, 0x1F6CC), (0x1F6D0, 0x1F6D2),
    (0x1F6D5, 0x1F6D9), (0x1F6DC, 0x1F6DF), (0x1F6EB, 0x1F6EC), (0x1F6F4, 0x1F6FC), (0x1F7E0, 0x1F7EB),
    (0x1F7F0, 0x1F7F0), (0x1F90C, 0x1F93A), (0x1F93C, 0x1F945), (0x1F947, 0x1F9FF), (0x1FA70, 0x1FA7C),
    (0x1FA80, 0x1FAC6), (0x1FAC8, 0x1FAC8), (0x1FACC, 0x1FADD), (0x1FADF, 0x1FAEB), (0x1FAEF, 0x1FAFA),
)
_EP_STARTS = [start for start, _end in _EP_RANGES]
_EP_ENDS = [end for _start, end in _EP_RANGES]
_EMOJI_PRESENTATION_STARTS = [start for start, _end in _EMOJI_PRESENTATION_RANGES]
_EMOJI_PRESENTATION_ENDS = [end for _start, end in _EMOJI_PRESENTATION_RANGES]
_VS15 = "\ufe0e"
_VS16 = "\ufe0f"
_ZWJ = "\u200d"
_KEYCAP = "\u20e3"
_KEYCAP_BASES = set("#*0123456789")
_RI_START, _RI_END = 0x1F1E6, 0x1F1FF
_SKIN_START, _SKIN_END = 0x1F3FB, 0x1F3FF
_TAG_START, _TAG_END = 0xE0020, 0xE007E
_TAG_TERM = 0xE007F


def _in_ranges(codepoint, starts, ends):
    index = bisect.bisect_right(starts, codepoint) - 1
    return index >= 0 and codepoint <= ends[index]


def _consume_emoji_core(title, index):
    length = len(title)
    if index >= length:
        return index
    char = title[index]
    codepoint = ord(char)
    if char in _KEYCAP_BASES:
        cursor = index + 1
        if cursor < length and title[cursor] == _VS16:
            cursor += 1
        if cursor < length and title[cursor] == _KEYCAP:
            return cursor + 1
        return index
    if _RI_START <= codepoint <= _RI_END:
        if index + 1 < length and _RI_START <= ord(title[index + 1]) <= _RI_END:
            return index + 2
        return index
    if not _in_ranges(codepoint, _EP_STARTS, _EP_ENDS):
        return index
    cursor = index + 1
    if cursor < length and title[cursor] == _VS15:
        return index
    had_vs16 = False
    if cursor < length and title[cursor] == _VS16:
        had_vs16 = True
        cursor += 1
    had_skin = False
    if cursor < length and _SKIN_START <= ord(title[cursor]) <= _SKIN_END:
        had_skin = True
        cursor += 1
    if cursor < length and _TAG_START <= ord(title[cursor]) <= _TAG_END:
        tag = cursor
        while tag < length and _TAG_START <= ord(title[tag]) <= _TAG_END:
            tag += 1
        if tag < length and ord(title[tag]) == _TAG_TERM:
            cursor = tag + 1
    if _in_ranges(codepoint, _EMOJI_PRESENTATION_STARTS, _EMOJI_PRESENTATION_ENDS) or had_vs16 or had_skin:
        return cursor
    return index


def leading_emoji_length(title):
    """Return the length of a leading emoji grapheme, or 0 if there is not one."""
    cursor = _consume_emoji_core(title, 0)
    if cursor == 0:
        return 0
    while cursor < len(title) and title[cursor] == _ZWJ:
        nxt = _consume_emoji_core(title, cursor + 1)
        if nxt == cursor + 1:
            break
        cursor = nxt
    return cursor


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
    if previous is None and leading_emoji_length(title) > 0:
        return title
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
