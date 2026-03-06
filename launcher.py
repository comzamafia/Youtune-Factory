"""AI YouTube Novel Factory — Desktop Launcher

Double-click or run: python launcher.py
Checks dependencies, starts the server, and opens the browser automatically.
"""

import os
import sys
import time
import socket
import subprocess
import webbrowser
from pathlib import Path

# ── Config ─────────────────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent
PORT = int(os.environ.get("PORT", "8000"))
URL = f"http://localhost:{PORT}"
VENV_PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"

# Colors for Windows console
class C:
    RESET = "\033[0m"
    GREEN = "\033[92m"
    RED = "\033[91m"
    YELLOW = "\033[93m"
    CYAN = "\033[96m"
    BOLD = "\033[1m"

def ok(msg: str):
    print(f"  {C.GREEN}✓{C.RESET} {msg}")

def fail(msg: str):
    print(f"  {C.RED}✗{C.RESET} {msg}")

def warn(msg: str):
    print(f"  {C.YELLOW}!{C.RESET} {msg}")

def info(msg: str):
    print(f"  {C.CYAN}→{C.RESET} {msg}")


def banner():
    print(f"""
{C.CYAN}{C.BOLD}  ╔══════════════════════════════════════════════╗
  ║     AI YouTube Novel Factory  v1.0.0        ║
  ║     Novel → Script → Voice → Image → Video  ║
  ╚══════════════════════════════════════════════╝{C.RESET}
""")


def is_port_open(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1)
        return s.connect_ex(("127.0.0.1", port)) == 0


def check_python() -> bool:
    if VENV_PYTHON.exists():
        ok(f"Python venv: {VENV_PYTHON}")
        return True
    fail(f"Python venv not found: {VENV_PYTHON}")
    print(f"    Run: python -m venv .venv && .venv\\Scripts\\pip install -r requirements.txt")
    return False


def check_ffmpeg() -> bool:
    try:
        r = subprocess.run(["ffmpeg", "-version"], capture_output=True, text=True, timeout=5)
        ver = r.stdout.split("\n")[0] if r.returncode == 0 else "unknown"
        ok(f"FFmpeg: {ver.split('Copyright')[0].strip()}")
        return True
    except FileNotFoundError:
        fail("FFmpeg not found. Install from https://ffmpeg.org/download.html")
        return False


def check_ollama() -> bool:
    try:
        r = subprocess.run(["ollama", "ps"], capture_output=True, text=True, timeout=5)
        if r.returncode == 0:
            ok("Ollama: running")
            return True
    except FileNotFoundError:
        pass

    # Try to start Ollama
    warn("Ollama not running, starting...")
    try:
        subprocess.Popen(
            ["ollama", "serve"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        # Wait for it to come up
        for _ in range(10):
            time.sleep(1)
            if is_port_open(11434):
                ok("Ollama: started successfully")
                return True
        fail("Ollama failed to start within 10s")
        return False
    except FileNotFoundError:
        fail("Ollama not installed. Download from https://ollama.com")
        return False


def check_server_already_running() -> bool:
    if is_port_open(PORT):
        ok(f"Server already running on port {PORT}")
        return True
    return False


def start_server() -> subprocess.Popen:
    info(f"Starting server on port {PORT}...")
    proc = subprocess.Popen(
        [str(VENV_PYTHON), "main.py", "--port", str(PORT)],
        cwd=str(ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )

    # Wait for server to be ready
    for i in range(30):
        time.sleep(1)
        if is_port_open(PORT):
            ok(f"Server ready: {URL}")
            return proc
        # Check if process died
        if proc.poll() is not None:
            fail("Server failed to start!")
            output = proc.stdout.read().decode("utf-8", errors="replace") if proc.stdout else ""
            if output:
                print(f"    {output[:500]}")
            return proc

    fail(f"Server did not respond within 30s on port {PORT}")
    return proc


def open_browser():
    info(f"Opening browser: {URL}")
    time.sleep(1)
    webbrowser.open(URL)


def main():
    os.system("")  # Enable ANSI colors on Windows
    banner()

    print(f"  {C.BOLD}Checking dependencies...{C.RESET}\n")

    # Check all dependencies
    py_ok = check_python()
    ff_ok = check_ffmpeg()
    ol_ok = check_ollama()

    print()

    if not py_ok or not ff_ok:
        fail("Missing required dependencies. Fix the issues above and try again.")
        input("\n  Press Enter to exit...")
        sys.exit(1)

    if not ol_ok:
        warn("Ollama not available — LLM features will fail.")
        warn("The server will start anyway for testing.\n")

    # Start or detect server
    server_proc = None
    if not check_server_already_running():
        server_proc = start_server()
        if not is_port_open(PORT):
            input("\n  Press Enter to exit...")
            sys.exit(1)

    print()
    open_browser()

    print(f"""
{C.GREEN}{C.BOLD}  ┌─────────────────────────────────────────────┐
  │  Server is running at {URL:<22s}│
  │  Press Ctrl+C to stop the server            │
  └─────────────────────────────────────────────┘{C.RESET}
""")

    if server_proc:
        try:
            server_proc.wait()
        except KeyboardInterrupt:
            info("Shutting down server...")
            server_proc.terminate()
            server_proc.wait(timeout=5)
            ok("Server stopped.")
    else:
        info("Server was already running (not managed by launcher).")
        input("  Press Enter to exit...")


if __name__ == "__main__":
    main()
