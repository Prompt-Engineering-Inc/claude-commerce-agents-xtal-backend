"""Run Anthropic's retail storefront over an XTAL collection with one command.

    python scripts/run_demo.py                 # API :8000 over XTAL + upstream storefront :3000
    python scripts/run_demo.py --api-only      # just the API (uvicorn, with reload off)
    python scripts/run_demo.py --web-only      # just the storefront, pointed at --api-port

The API is ``examples/retail_on_xtal/main.py`` (this repo) served by uvicorn with the
vendored ``examples/`` on the path. The web app is upstream's own retail storefront,
unchanged, started the way upstream's ``scripts/run_demo.py retail --web-only`` starts
it (``next dev`` with ``NEXT_PUBLIC_API_URL`` pointed at the API); that upstream script
does the same on macOS and Linux, but on Windows it execs a shell script and fails. Settings come from ``.env`` at this repo's root (see ``.env.example``);
``XTAL_COLLECTION`` must be set or the API boots the upstream ACME mock instead. Logs go
to ``--log-dir`` (default ``docs/demo/logs/``, gitignored) as well as the console.
"""

from __future__ import annotations

import argparse
import os
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[1]
UPSTREAM = REPO_ROOT / "vendor" / "commerce-agents"
EXAMPLES = REPO_ROOT / "examples"
UPSTREAM_EXAMPLES = UPSTREAM / "examples"
STOREFRONT = UPSTREAM_EXAMPLES / "retail" / "storefront-web"
NEXT = UPSTREAM_EXAMPLES / "node_modules" / "next" / "dist" / "bin" / "next"


def port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        return sock.connect_ex(("127.0.0.1", port)) == 0


def wait_for(url: str, timeout_s: float, process: subprocess.Popen | None) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if process is not None and process.poll() is not None:
            return False
        try:
            with urllib.request.urlopen(url, timeout=2):
                return True
        except Exception:
            time.sleep(0.5)
    return False


def spawn(command: list[str], cwd: Path, env: dict[str, str]) -> subprocess.Popen:
    flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
    return subprocess.Popen(
        command,
        cwd=cwd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        creationflags=flags,
        start_new_session=os.name != "nt",
    )


def tee(process: subprocess.Popen, label: str, log_path: Path) -> None:
    def run() -> None:
        assert process.stdout is not None
        with log_path.open("ab") as log:
            for line in process.stdout:
                log.write(line)
                log.flush()
                sys.stdout.write(f"[{label}] {line.decode(errors='replace')}")

    threading.Thread(target=run, daemon=True).start()


def stop(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/T", "/F", "/PID", str(process.pid)], capture_output=True, check=False
        )
    else:
        os.killpg(os.getpgid(process.pid), signal.SIGTERM)
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()


def main() -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").partition("\n")[0])
    side = parser.add_mutually_exclusive_group()
    side.add_argument("--api-only", action="store_true")
    side.add_argument("--web-only", action="store_true")
    parser.add_argument("--api-port", type=int, default=8000)
    parser.add_argument("--log-dir", type=Path, default=REPO_ROOT / "docs" / "demo" / "logs")
    args = parser.parse_args()

    load_dotenv(REPO_ROOT / ".env", override=False)
    if not os.environ.get("XTAL_COLLECTION"):
        print(
            "XTAL_COLLECTION is not set; the API would boot the upstream ACME mock. Set it in .env."
        )
        return 2
    if not UPSTREAM_EXAMPLES.exists():
        print(f"Upstream is not vendored at {UPSTREAM}; see README (clone at the pinned commit).")
        return 2
    args.log_dir.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(
        [str(EXAMPLES), str(UPSTREAM_EXAMPLES), str(REPO_ROOT), env.get("PYTHONPATH", "")]
    )
    env.setdefault("PYTHONUNBUFFERED", "1")

    processes: list[tuple[str, subprocess.Popen]] = []
    try:
        if not args.web_only:
            if port_in_use(args.api_port):
                print(f"Port {args.api_port} is busy; stop what is there or pass --api-port.")
                return 1
            api = spawn(
                [
                    sys.executable,
                    "-m",
                    "uvicorn",
                    "retail_on_xtal.main:app",
                    "--app-dir",
                    str(EXAMPLES),
                    "--port",
                    str(args.api_port),
                ],
                REPO_ROOT,
                env,
            )
            processes.append(("api", api))
            tee(api, "api", args.log_dir / "api.log")
            if not wait_for(f"http://localhost:{args.api_port}/api/health", 90, api):
                print("The API did not come up; see the output above.")
                return 1
        if not args.api_only:
            if not NEXT.exists():
                print(f"{NEXT} is missing; run `npm ci` in {UPSTREAM_EXAMPLES} first.")
                return 1
            web = spawn(
                ["node", str(NEXT), "dev", "--port", "3000"],
                STOREFRONT,
                env | {"NEXT_PUBLIC_API_URL": f"http://localhost:{args.api_port}"},
            )
            processes.append(("web", web))
            tee(web, "web", args.log_dir / "web.log")
            if not wait_for("http://localhost:3000", 180, web):
                print("The storefront did not come up on :3000; see the output above.")
                return 1
        print(f"\nAPI     http://localhost:{args.api_port}/api/health")
        if not args.api_only:
            print("store   http://localhost:3000")
        print("Ctrl-C stops everything.\n")
        while all(process.poll() is None for _, process in processes):
            time.sleep(1)
        for name, process in processes:
            if process.poll() is not None:
                print(f"{name} exited with code {process.returncode}.")
                return process.returncode or 1
        return 0
    except KeyboardInterrupt:
        print("\nShutting down.")
        return 0
    finally:
        for _, process in processes:
            stop(process)


if __name__ == "__main__":
    raise SystemExit(main())
