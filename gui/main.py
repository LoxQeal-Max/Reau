"""录制自动化插件 - 简化 GUI

用法：
  python gui/main.py
  python -m gui.main
"""
from __future__ import annotations

import sys
import subprocess as _sp
if sys.platform == 'win32':
    _CREATE_NO_WINDOW = 0x08000000
    _orig_run = _sp.run
    _orig_popen = _sp.Popen
    def _patched_run(*args, **kwargs):
        kwargs.setdefault('creationflags', 0)
        kwargs['creationflags'] |= _CREATE_NO_WINDOW
        return _orig_run(*args, **kwargs)
    def _patched_popen(*args, **kwargs):
        kwargs.setdefault('creationflags', 0)
        kwargs['creationflags'] |= _CREATE_NO_WINDOW
        return _orig_popen(*args, **kwargs)
    _sp.run = _patched_run
    _sp.Popen = _patched_popen

import os
import time
import queue
import threading
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

APP_TITLE = "录制自动化工具"
APP_VERSION = "1.0.0"

OUTPUT_DIR = "out"
SCRIPT_FILE = os.path.join(OUTPUT_DIR, "script.py")


class RecorderApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title(f"{APP_TITLE}")
        self.root.geometry("720x540")
        self.root.minsize(620, 460)
        self.root.configure(bg=self.C_BG)

        self.rec = None
        self.is_recording = False
        self.msg_queue: queue.Queue = queue.Queue()
        self.current_actions = []
        self.device = None
        self._stop_playback_flag = threading.Event()

        self._set_icon()
        self._build_ui()
        self._setup_stdout_redirect()
        self._poll_messages()
        self._refresh_device()

    def _setup_stdout_redirect(self):
        import io
        import sys

        class StdRedirect(io.TextIOBase):
            def __init__(self, app):
                self.app = app

            def write(self, text):
                if text and text.strip():
                    self.app.root.after(0, self.app._append_log, text.rstrip("\n"), "info")
                return len(text)

        sys.stdout = StdRedirect(self)
        sys.stderr = StdRedirect(self)

    def _set_icon(self):
        try:
            import sys
            if getattr(sys, 'frozen', False):
                base_dir = os.path.dirname(sys.executable)
            else:
                base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            icon_path = os.path.join(base_dir, "icon.png")
            if os.path.exists(icon_path):
                img = tk.PhotoImage(file=icon_path)
                self.root.iconphoto(True, img)
                self._icon_img = img
        except Exception:
            pass

    # Win11 明亮主题配色
    C_BG = "#f3f3f3"           # 窗口背景
    C_CARD = "#ffffff"          # 卡片/面板背景
    C_BORDER = "#e0e0e0"        # 边框
    C_TEXT = "#1a1a1a"          # 主文字
    C_TEXT_SEC = "#5f5f5f"      # 次要文字
    C_ACCENT = "#0067c0"        # Win11 蓝
    C_ACCENT_HOVER = "#005a9e"  # 悬停蓝
    C_GREEN = "#107c10"        # 录制绿
    C_RED = "#c42b1c"          # 停止红
    C_ORANGE = "#ca5010"       # 警告橙
    C_LOG_BG = "#fafafa"       # 日志背景
    C_LOG_FG = "#1a1a1a"       # 日志文字

    def _build_ui(self):
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except Exception:
            pass

        # 全局样式配置
        style.configure(".", background=self.C_BG, foreground=self.C_TEXT,
                         font=("Microsoft YaHei UI", 9))
        style.configure("TFrame", background=self.C_BG)
        style.configure("Card.TFrame", background=self.C_CARD)
        style.configure("TLabel", background=self.C_BG, foreground=self.C_TEXT,
                         font=("Microsoft YaHei UI", 9))
        style.configure("Title.TLabel", background=self.C_BG, foreground=self.C_TEXT,
                         font=("Microsoft YaHei UI", 10, "bold"))
        style.configure("Card.TLabel", background=self.C_CARD, foreground=self.C_TEXT)
        style.configure("Dim.TLabel", background=self.C_BG, foreground=self.C_TEXT_SEC)
        style.configure("CardDim.TLabel", background=self.C_CARD, foreground=self.C_TEXT_SEC)
        style.configure("TButton", font=("Microsoft YaHei UI", 9))
        style.configure("TEntry", fieldbackground=self.C_CARD, bordercolor=self.C_BORDER)
        style.configure("TCheckbutton", background=self.C_BG, foreground=self.C_TEXT,
                         font=("Microsoft YaHei UI", 9))
        style.configure("Card.TCheckbutton", background=self.C_CARD, foreground=self.C_TEXT)
        style.configure("TSeparator", background=self.C_BORDER)

        self.root.configure(bg=self.C_BG)

        self._build_device_bar()
        self._build_log_area()
        self._build_control_bar()

    def _build_device_bar(self):
        frame = ttk.Frame(self.root, padding=(14, 10, 14, 6))
        frame.pack(fill="x")

        self.refresh_btn = ttk.Button(frame, text="⟳ 刷新", command=self._refresh_device)
        self.refresh_btn.pack(side="right", padx=(8, 0))

        ttk.Label(frame, text="设备", style="Dim.TLabel").pack(side="left", padx=(0, 8))
        self.device_var = tk.StringVar(value="检测中...")
        self.device_label = ttk.Label(frame, textvariable=self.device_var,
                                      style="Dim.TLabel", anchor="w", width=50)
        self.device_label.pack(side="left", fill="x", expand=True)

        sep = ttk.Separator(self.root, orient="horizontal")
        sep.pack(fill="x", padx=14, pady=(0, 2))

    def _build_log_area(self):
        frame = ttk.Frame(self.root, padding=(14, 4, 14, 4))
        frame.pack(fill="both", expand=True)

        ttk.Label(frame, text="日志", style="Title.TLabel").pack(anchor="w", pady=(0, 6))

        self.log_text = scrolledtext.ScrolledText(
            frame, state="disabled", height=18,
            font=("Cascadia Code", 9), bg=self.C_LOG_BG, fg=self.C_LOG_FG,
            insertbackground=self.C_LOG_FG, relief="flat",
            borderwidth=1, highlightbackground=self.C_BORDER,
            highlightthickness=1, highlightcolor=self.C_BORDER,
            padx=8, pady=6
        )
        self.log_text.pack(fill="both", expand=True)

        # 明亮主题日志配色
        self.log_text.tag_configure("info", foreground="#3b3b3b")
        self.log_text.tag_configure("action", foreground="#0066b4")
        self.log_text.tag_configure("success", foreground="#107c10")
        self.log_text.tag_configure("warn", foreground="#9c5400")
        self.log_text.tag_configure("error", foreground="#c42b1c")

        btn_frame = ttk.Frame(frame)
        btn_frame.pack(fill="x", pady=(4, 0))
        ttk.Button(btn_frame, text="清空日志", command=self._clear_log).pack(side="right")

    def _build_control_bar(self):
        sep = ttk.Separator(self.root, orient="horizontal")
        sep.pack(fill="x", padx=14, pady=(2, 0))

        # 第一行：操作按钮
        btn_frame = ttk.Frame(self.root, padding=(14, 8, 14, 4))
        btn_frame.pack(fill="x")

        self.start_btn = tk.Button(
            btn_frame, text="● 开始录制", command=self._start_recording,
            width=12, bg=self.C_CARD, fg=self.C_GREEN,
            activebackground="#e6f0e6", activeforeground=self.C_GREEN,
            disabledforeground="#aaaaaa",
            relief="flat", cursor="hand2",
            borderwidth=1, highlightbackground=self.C_BORDER,
            highlightthickness=1, highlightcolor=self.C_BORDER,
            font=("Microsoft YaHei UI", 9),
            padx=12, pady=4
        )
        self.start_btn.pack(side="left", padx=(0, 6))

        self.stop_btn = tk.Button(
            btn_frame, text="■ 结束录制", command=self._stop_recording,
            width=12, bg=self.C_CARD, fg=self.C_RED,
            activebackground="#f5e0de", activeforeground=self.C_RED,
            disabledforeground="#cccccc",
            relief="flat", cursor="hand2",
            borderwidth=1, highlightbackground=self.C_BORDER,
            highlightthickness=1, highlightcolor=self.C_BORDER,
            font=("Microsoft YaHei UI", 9),
            padx=12, pady=4, state="disabled"
        )
        self.stop_btn.pack(side="left", padx=(0, 6))

        self.replay_btn = tk.Button(
            btn_frame, text="▶ 回放", command=self._start_playback,
            width=8, bg=self.C_ACCENT, fg="white",
            activebackground=self.C_ACCENT_HOVER, activeforeground="white",
            disabledforeground="#cccccc",
            relief="flat", cursor="hand2",
            borderwidth=0, highlightthickness=0,
            font=("Microsoft YaHei UI", 9),
            padx=12, pady=4
        )
        self.replay_btn.pack(side="left", padx=(0, 6))

        self.stop_playback_btn = tk.Button(
            btn_frame, text="■ 停止", command=self._stop_playback,
            width=8, bg=self.C_CARD, fg=self.C_ORANGE,
            activebackground="#fbeee6", activeforeground=self.C_ORANGE,
            disabledforeground="#cccccc",
            relief="flat", cursor="hand2",
            borderwidth=1, highlightbackground=self.C_BORDER,
            highlightthickness=1, highlightcolor=self.C_BORDER,
            font=("Microsoft YaHei UI", 9),
            padx=12, pady=4, state="disabled"
        )
        self.stop_playback_btn.pack(side="left", padx=(0, 6))

        self.clear_btn = tk.Button(
            btn_frame, text="清空", command=self._clear_actions,
            width=6, bg=self.C_CARD, fg=self.C_TEXT_SEC,
            activebackground="#ededed", activeforeground=self.C_TEXT,
            relief="flat", cursor="hand2",
            borderwidth=1, highlightbackground=self.C_BORDER,
            highlightthickness=1, highlightcolor=self.C_BORDER,
            font=("Microsoft YaHei UI", 9),
            padx=10, pady=4
        )
        self.clear_btn.pack(side="left", padx=(0, 0))

        self.status_var = tk.StringVar(value="就绪")
        ttk.Label(btn_frame, textvariable=self.status_var, style="Dim.TLabel").pack(side="right", padx=(10, 0))

        # 第二行：复选框
        opt_frame = ttk.Frame(self.root, padding=(14, 0, 14, 10))
        opt_frame.pack(fill="x")

        self.screenshot_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(opt_frame, text="录制截图", variable=self.screenshot_var).pack(side="left")

        self.template_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(opt_frame, text="裁剪模板", variable=self.template_var).pack(side="left", padx=(6, 0))

    # ---------- 设备 ----------
    def _refresh_device(self):
        self._log("正在检测设备...", "info")
        threading.Thread(target=self._do_refresh, daemon=True).start()

    def _do_refresh(self):
        try:
            import subprocess
            import uiautomator2 as u2

            adb = self._find_adb_path()
            r = subprocess.run([adb, "devices"], capture_output=True, text=True, timeout=5)
            lines = [l.strip() for l in r.stdout.splitlines() if l.strip() and "List" not in l]
            devices = []
            for line in lines:
                parts = line.split()
                if len(parts) >= 2 and parts[1] == "device":
                    devices.append(parts[0])

            if devices:
                serial = devices[0]
                d = u2.connect(serial)
                info = d.info
                self.device = d
                name = info.get("productName", serial)
                w = info.get("displayWidth", "?")
                h = info.get("displayHeight", "?")
                self.device_var.set(f"{name}  [{w}x{h}]  ({serial})")
                self._log(f"已连接: {name} [{w}x{h}]", "success")
            else:
                self.device_var.set("未检测到设备")
                self._log("未检测到设备，请连接手机并开启 USB 调试", "warn")
        except Exception as e:
            self.device_var.set(f"连接失败: {e}")
            self._log(f"连接失败: {e}", "error")

    def _find_adb_path(self):
        import os
        try:
            from airtest.core.android.adb import ADB
            return ADB().adb_path
        except Exception:
            pass
        candidates = []
        try:
            import airtest.core.android.adb as mod
            pkg_dir = os.path.dirname(mod.__file__)
            candidates.append(os.path.join(pkg_dir, "static", "adb", "windows", "adb.exe"))
        except Exception:
            pass
        candidates.append("adb")
        for p in candidates:
            if p == "adb":
                return p
            if os.path.exists(p):
                return p
        return "adb"

    # ---------- 录制 ----------
    def _start_recording(self):
        if self.is_recording:
            return
        if not self.device:
            messagebox.showwarning("提示", "请先连接设备")
            return

        self.start_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")
        self.status_var.set("启动中...")
        self._log("正在启动录制...", "info")

        threading.Thread(target=self._do_start_recording, daemon=True).start()

    def _do_start_recording(self):
        try:
            from recorder.recorder_core import RecorderCore
            from recorder.air_assembler import ScriptAssembler
            from recorder.bus import bus
            from recorder.codegen.element_data import load_default_elements

            load_default_elements()
            self.current_actions = []
            self._clear_log()

            self._asm = ScriptAssembler(OUTPUT_DIR)
            self.rec = RecorderCore(codegen=self._asm.codegen)

            bus.subscribe("action", self._on_action)
            bus.subscribe("code", self._on_code)

            serial = self.device_var.get().split("(")[-1].rstrip(")") if "(" in self.device_var.get() else ""
            enable_shot = self.screenshot_var.get()
            enable_tpl = self.template_var.get()
            self.rec.start("android", device_serial=serial,
                          enable_screenshot=enable_shot, enable_template=enable_tpl)
            self.is_recording = True

            parts = []
            if enable_shot: parts.append("📷截图")
            if enable_tpl: parts.append("🎯模板")
            if not parts: parts.append("仅坐标")
            self.root.after(0, lambda: self.status_var.set("录制中..."))
            self.root.after(0, lambda: self._log(f"=== 开始录制，请触摸屏幕 ({' / '.join(parts)}) ===", "success"))
        except Exception as e:
            self.is_recording = False
            self.root.after(0, lambda: self.start_btn.configure(state="normal"))
            self.root.after(0, lambda: self.stop_btn.configure(state="disabled"))
            self.root.after(0, lambda: self.status_var.set("就绪"))
            self.root.after(0, lambda: self._log(f"启动失败: {e}", "error"))
            import traceback
            self.root.after(0, lambda: self._log(traceback.format_exc(), "error"))

    def _stop_recording(self):
        if not self.is_recording:
            return
        self.is_recording = False

        self.start_btn.configure(state="normal")
        self.stop_btn.configure(state="disabled")

        actions = self.rec.stop()
        self._log(f"录制结束，共 {len(actions)} 条操作", "info")

        for a in actions:
            action_type = a.type if hasattr(a, 'type') else "touch"
            self._asm.append(self._asm.codegen.emit(a), timestamp=a.timestamp, action_type=action_type)

        script_path = self._asm.build()
        self._log(f"脚本已生成: {script_path}", "success")
        self.status_var.set("就绪")

        if actions:
            self._log(f"回放: python demo_auto.py --replay", "info")

    def _clear_actions(self):
        self.current_actions = []
        self._clear_log()

    def _on_action(self, a: dict):
        self.current_actions.append(a)
        tgt = a.get("target", {})
        val = tgt.get("value", "")
        action_type = a.get("type", "?")
        uia = a.get("params", {}).get("uia") or {}
        matched = a.get("params", {}).get("element_def", "")
        shot = a.get("params", {}).get("screenshot", "")
        tpl = a.get("params", {}).get("template", "")
        tag = f" [{matched}]" if matched else ""
        shot_tag = f" 📷" if shot else ""
        tpl_tag = f" 🎯" if tpl else ""

        if action_type == "swipe":
            p = a.get("params", {})
            direction = p.get("direction", "")
            distance = p.get("distance", 0)
            duration = p.get("duration", 0)
            start = p.get("start", (0, 0))
            end = p.get("end", (0, 0))
            val = f"{start} → {end} [{direction}] {distance:.0f}px {duration:.2f}s"

        self._log(f"  {action_type} {val}{tag}{shot_tag}{tpl_tag}", "action")

    def _on_code(self, c: dict):
        self._log(f"  → {c.get('code', '')}", "info")

    # ---------- 回放 ----------
    def _start_playback(self):
        if not os.path.exists(SCRIPT_FILE):
            messagebox.showwarning("提示", f"找不到脚本: {SCRIPT_FILE}")
            return
        if not self.device:
            messagebox.showwarning("提示", "请先连接设备")
            return

        self._stop_playback_flag.clear()
        self.replay_btn.configure(state="disabled")
        self.stop_playback_btn.configure(state="normal")
        self.status_var.set("回放中...")
        self._log(f"=== 开始回放 {SCRIPT_FILE} ===", "success")
        threading.Thread(target=self._do_playback, daemon=True).start()

    def _stop_playback(self):
        self._stop_playback_flag.set()
        self._log("已发送停止指令...", "warn")

    def _do_playback(self):
        try:
            import uiautomator2 as u2
            import cv2
            import numpy as np
            import time as _time
            serial = self.device_var.get().split("(")[-1].rstrip(")") if "(" in self.device_var.get() else ""
            self._log(f"连接设备: {serial or '默认'}", "info")
            d = u2.connect(serial) if serial else u2.connect()
            info = d.info
            self._log(f"设备分辨率: {info.get('displayWidth')}x{info.get('displayHeight')}", "info")
            self._log(f"设备: {info.get('productName', 'unknown')}", "info")

            stop_flag = self._stop_playback_flag

            def check_stop():
                if stop_flag.is_set():
                    raise RuntimeError("STOP_PLAYBACK")

            def _sleep(seconds):
                self._log(f"等待 {seconds:.1f}s...", "info")
                for _ in range(int(seconds / 0.1)):
                    check_stop()
                    _time.sleep(0.1)
                remain = seconds - int(seconds / 0.1) * 0.1
                if remain > 0:
                    check_stop()
                    _time.sleep(remain)

            with open(SCRIPT_FILE, encoding="utf-8") as f:
                code = f.read()

            # Remove lines that would override our injected variables
            lines = code.split('\n')
            filtered_lines = []
            for line in lines:
                stripped = line.strip()
                if stripped.startswith('import uiautomator2'):
                    continue
                if stripped.startswith('import cv2'):
                    continue
                if stripped.startswith('import numpy'):
                    continue
                if stripped.startswith('d = u2.connect('):
                    continue
                if stripped.startswith('if __name__ == "__main__"') or stripped == 'run()':
                    continue
                filtered_lines.append(line)

            clean_code = '\n'.join(filtered_lines)

            def action_log(msg):
                self._log(str(msg), "action")

            namespace = {
                "d": d,
                "__name__": "__main__",
                "time": _time,
                "_time": _time,
                "check_stop": check_stop,
                "_sleep": _sleep,
                "print": action_log,
                "cv2": cv2,
                "np": np,
            }

            self._log("开始执行脚本...", "success")

            local_ns = {}
            exec(clean_code, namespace, local_ns)

            if "run" in local_ns:
                self._log("调用 run()...", "info")
                local_ns["run"]()
                self._log("=== 回放完成 ===", "success")
            else:
                self._log("未找到 run() 函数", "error")

        except RuntimeError as e:
            if "STOP_PLAYBACK" in str(e):
                self._log("=== 回放已立即终止 ===", "warn")
            else:
                self._log(f"=== 回放异常: {e} ===", "error")
        except Exception as e:
            self._log(f"=== 回放异常: {e} ===", "error")
            import traceback
            self._log(traceback.format_exc(), "error")
        finally:
            self.replay_btn.configure(state="normal")
            self.stop_playback_btn.configure(state="disabled")
            self.status_var.set("就绪")

    # ---------- 日志 ----------
    def _log(self, msg: str, tag: str = "info"):
        ts = time.strftime("%H:%M:%S")
        self.root.after(0, self._append_log, f"[{ts}] {msg}", tag)

    def _poll_messages(self):
        try:
            while True:
                kind, msg, tag = self.msg_queue.get_nowait()
                self._append_log(msg, tag)
        except queue.Empty:
            pass
        self.root.after(100, self._poll_messages)

    def _append_log(self, msg: str, tag: str = "info"):
        self.log_text.configure(state="normal")
        self.log_text.insert("end", msg + "\n", tag)
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _clear_log(self):
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")


def main():
    try:
        _sp.run(["adb", "start-server"], capture_output=True, timeout=5)
    except Exception:
        pass

    root = tk.Tk()
    app = RecorderApp(root)
    root.protocol("WM_DELETE_WINDOW", root.destroy)
    root.mainloop()


if __name__ == "__main__":
    main()