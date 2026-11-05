"""Test installed hooks, watcher ownership, and title updates without sending model requests."""

import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
from unittest.mock import patch


REPO = Path(__file__).resolve().parents[1]
PLUGIN_ID = "codex-model-badges@local-model-badges"
SCRIPT = "codex_model_badges.py"


def load_installed_script(install):
    path = install / "hooks" / SCRIPT
    spec = importlib.util.spec_from_file_location("badges", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def wait_for(check, message, timeout=25):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if check():
            return
        time.sleep(0.25)
    raise AssertionError(message)


def hook_runner(install, thread_id):
    events = json.loads((install / "hooks" / "hooks.json").read_bytes())["hooks"]
    if os.name == "nt":
        shell = ["powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive", "-Command"]
        command_key = "commandWindows"
    else:
        shell = ["/bin/sh", "-c"]
        command_key = "command"

    def run(event):
        command = events[event][0]["hooks"][0][command_key]
        payload = {"hook_event_name": event, "session_id": thread_id, "model": "gpt-6.1-sol"}
        subprocess.run(
            [*shell, command],
            input=json.dumps(payload).encode(),
            check=True,
            timeout=15,
        )

    return run


def smoke(codex, root):
    subprocess.run([codex, "plugin", "marketplace", "add", str(REPO)], check=True, timeout=30)
    result = subprocess.check_output([codex, "plugin", "add", PLUGIN_ID, "--json"], timeout=30)
    install = Path(json.loads(result)["installedPath"])
    badges = load_installed_script(install)

    class TestServer(badges.AppServer):
        def call(self, method, params):
            if method == "initialize":
                params = {**params, "capabilities": {"experimentalApi": True}}
            return super().call(method, params)

    data = root / "watch data"
    with patch.dict(os.environ, {"PLUGIN_ROOT": str(install), "PLUGIN_DATA": str(data)}):
        server = TestServer(codex)
        try:
            thread_id = server.call("thread/start", {"cwd": str(root), "model": "gpt-6.1-sol"})["thread"]["id"]
            run_hook = hook_runner(install, thread_id)
            thread_params = {"threadId": thread_id}

            def title():
                return server.call("thread/read", thread_params)["thread"]["name"]

            def lock_available():
                try:
                    with (data / "watch.lock").open("ab") as lock:
                        return badges.try_watcher_lock(lock)
                except FileNotFoundError:
                    return True

            try:
                run_hook("SessionStart")
                run_hook("UserPromptSubmit")
                wait_for(lambda: not lock_available(), "the installed hook did not start a watcher")
                assert title() is None, "the watcher should wait for the native title"

                original = "📌 示例会话"
                server.call("thread/name/set", {**thread_params, "name": original})
                wait_for(lambda: title() == "☀️\u2009" + original, "the model badge did not appear")
                print("PASS: the watcher prefixes the native title")

                server.call("thread/settings/update", {**thread_params, "serviceTier": "fast"})
                wait_for(lambda: title() == "☀️ ⚡\u2009" + original, "Fast on did not update the title")
                server.call("thread/settings/update", {**thread_params, "serviceTier": None})
                wait_for(lambda: title() == "☀️\u2009" + original, "Fast off did not update the title")
                server.call("thread/settings/update", {**thread_params, "model": "gpt-6.1-terra"})
                wait_for(lambda: title() == "🌍\u2009" + original, "the new model did not update the title")
                print("PASS: Fast on, Fast off, and model switching update the title without another message")

                run_hook("Stop")
                assert title() == "🌍\u2009" + original
            finally:
                run_hook("SessionEnd")
                wait_for(lock_available, "the watcher did not release its lock after session end")
            print("PASS: session end stops the watcher")
        finally:
            server.close()


if __name__ == "__main__":
    cli = shutil.which("codex.exe" if os.name == "nt" else "codex") or shutil.which("codex")
    if not cli:
        raise SystemExit("Install a recent native Codex CLI before running this test.")
    with tempfile.TemporaryDirectory(prefix="codex model badges ") as directory:
        scratch = Path(directory).resolve()
        codex_home = scratch / "codex"
        codex_home.mkdir()
        with patch.dict(os.environ, {"CODEX_HOME": str(codex_home)}):
            smoke(cli, scratch)
