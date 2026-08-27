"""一键启动脚本 - 自动打开浏览器（通过 VBS 隐藏控制台）"""
import os
import socket
import sys
import threading
import time
import traceback
import webbrowser

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

LOG_FILE = os.path.join(ROOT, "reau.log")


def _log(msg: str):
    """写入日志文件"""
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"[{time.strftime('%H:%M:%S')}] {msg}\n")
    except Exception:
        pass


def _wait_and_open(url: str, max_wait: int = 20):
    """等待服务就绪后打开浏览器"""
    _log(f"Waiting for service at {url}...")
    start = time.time()
    while time.time() - start < max_wait:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(1)
            sock.connect(("127.0.0.1", 8000))
            sock.close()
            _log(f"Service ready, opening browser: {url}")
            webbrowser.open(url)
            return
        except (ConnectionRefusedError, OSError):
            time.sleep(0.3)
    _log(f"Timeout waiting for service, opening browser anyway: {url}")
    webbrowser.open(url)


def main():
    _log("=" * 40)
    _log("Reau starting...")

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind(("127.0.0.1", 8000))
        sock.close()
    except OSError:
        _log("Port 8000 already in use, opening browser directly")
        webbrowser.open("http://localhost:8000")
        return

    # Single browser entry point - wait for service then open
    threading.Thread(
        target=_wait_and_open,
        args=("http://localhost:8000",),
        daemon=True,
    ).start()

    _log("Launching uvicorn on :8000")
    import uvicorn
    uvicorn.run("backend.main:app", host="0.0.0.0", port=8000, log_level="info")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        _log(f"FATAL ERROR: {e}")
        _log(traceback.format_exc())
        input("Press Enter to exit...")
