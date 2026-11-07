"""Start/stop only this checkout's native SiteWatch service (CPU, localhost)."""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / ".runtime/sitewatch-env/runtime"
STATE = RUNTIME / "managed-process.json"
LOG = RUNTIME / "managed-server.log"
URL = "http://127.0.0.1:8767"
MODEL = ROOT / "downloads/sitewatch/repository/models/sitewatch_best.pt"
EXPECTED_SHA = "c2db52b9be8ccd5bcc09d6e0f9498a6e442e47eb6f6b62850db11530b77651ab"


def identity(pid):
    try:
        proc = Path("/proc") / str(pid)
        argv = (proc / "cmdline").read_bytes().split(b"\0")
        argv = [v.decode() for v in argv if v]
        # /proc stat's command can contain spaces, so split after its last ')'.
        start_ticks = (proc / "stat").read_text().rsplit(")", 1)[1].split()[19]
        if str(ROOT / "sitewatch/run.py") not in argv or str(ROOT) not in argv:
            return None
        return {"pid": pid, "start_ticks": start_ticks}
    except (OSError, ValueError, IndexError):
        return None


def owned():
    try:
        state = json.loads(STATE.read_text())
        actual = identity(int(state["pid"]))
        return state if actual == {k: state[k] for k in ("pid", "start_ticks")} else None
    except (OSError, ValueError, KeyError, TypeError):
        return None


def healthy():
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(URL + "/_stcore/health", timeout=1) as response:
            return response.status == 200 and response.read() == b"ok"
    except OSError:
        return False


def status():
    state = owned()
    result = {"running": bool(state), "pid": state["pid"] if state else None,
              "server_healthy": healthy() if state else False, "url": URL,
              "device": "cpu", "log": str(LOG),
              "note": "Server health is not a model accuracy assertion; weights load on browser connection."}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return result


def wait_ready():
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        if not owned():
            raise RuntimeError(f"SiteWatch exited during startup; see {LOG}")
        if healthy():
            return
        time.sleep(0.25)
    raise RuntimeError(f"Server health did not become ready within 45 s; see {LOG}")


def start(wait):
    if owned():
        if wait:
            wait_ready()
        return status()
    if not (ROOT / "sitewatch/run.py").is_file():
        raise RuntimeError("SiteWatch source is not integrated in this checkout yet.")
    # An unowned listener is never stopped or silently adopted.
    with socket.socket() as probe:
        if probe.connect_ex(("127.0.0.1", 8767)) == 0:
            raise RuntimeError("Port 8767 is occupied by an unmanaged service; close its own launcher first.")
    if not MODEL.is_file() or hashlib.sha256(MODEL.read_bytes()).hexdigest() != EXPECTED_SHA:
        raise RuntimeError("Pinned PPE weight is missing or has wrong SHA256; run sitewatch/prepare.py.")
    if not (ROOT / ".runtime/sitewatch-env/bin/python").is_file():
        raise RuntimeError("SiteWatch environment is missing; run sitewatch/prepare.py.")
    command = [sys.executable, str(ROOT / "sitewatch/run.py"), "--project-root", str(ROOT)]
    with LOG.open("ab") as log:
        process = subprocess.Popen(command, cwd=ROOT, stdout=log, stderr=log,
                                   stdin=subprocess.DEVNULL, start_new_session=True)
    actual = identity(process.pid)
    if actual is None:
        raise RuntimeError(f"Launcher exited before identity could be verified; see {LOG}")
    temporary = STATE.with_suffix(".tmp")
    temporary.write_text(json.dumps({**actual, "command": command, "url": URL}, ensure_ascii=False) + "\n")
    temporary.replace(STATE)
    if wait:
        wait_ready()
    return status()


def stop():
    state = owned()
    if state:
        pid = state["pid"]
        if os.getpgid(pid) != pid:
            raise RuntimeError("Refusing to stop a process outside its dedicated process group")
        os.killpg(pid, signal.SIGTERM)
        deadline = time.monotonic() + 10
        while identity(pid) and time.monotonic() < deadline:
            time.sleep(0.1)
        if identity(pid):
            raise RuntimeError("Owned service did not stop within 10 s; inspect its log")
        while time.monotonic() < deadline:
            with socket.socket() as probe:
                if probe.connect_ex(("127.0.0.1", 8767)) != 0:
                    break
            time.sleep(0.1)
        else:
            raise RuntimeError("Launcher stopped but port 8767 is still occupied; no unrelated service was stopped")
    STATE.unlink(missing_ok=True)
    return status()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["start", "stop", "status"])
    parser.add_argument("--wait", action="store_true")
    args = parser.parse_args()
    RUNTIME.mkdir(parents=True, exist_ok=True)
    with (RUNTIME / "manager.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            {"start": lambda: start(args.wait), "stop": stop, "status": status}[args.action]()
        except (OSError, RuntimeError) as exc:
            print(str(exc), file=sys.stderr)
            raise SystemExit(1)


if __name__ == "__main__":
    main()
