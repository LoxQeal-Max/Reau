"""录制自动化插件 - 简化 GUI

用法：
  python gui/main.py
  python -m gui.main
"""
from __future__ import annotations
import os
import sys
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
        self.root.title(f"{APP_TITLE} v{APP_VERSION}")
        self.root.geometry("700x520")
        self.root.minsize(600, 450)

        self.rec = None
        self.is_recording = False
        self.msg_queue: queue.Queue = queue.Queue()
        self.current_actions = []
        self.device = None

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

    def _build_ui(self):
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except Exception:
            pass

        self._build_device_bar()
        self._build_log_area()
        self._build_control_bar()

    def _build_device_bar(self):
        frame = ttk.Frame(self.root, padding=(10, 8))
        frame.pack(fill="x")

        self.refresh_btn = ttk.Button(frame, text="刷新", command=self._refresh_device)
        self.refresh_btn.pack(side="right", padx=4)

        ttk.Label(frame, text="设备:").pack(side="left", padx=(0, 6))
        self.device_var = tk.StringVar(value="检测中...")
        self.device_label = ttk.Label(frame, textvariable=self.device_var, foreground="gray",
                                      anchor="w", width=50)
        self.device_label.pack(side="left", fill="x", expand=True)

        sep = ttk.Separator(self.root, orient="horizontal")
        sep.pack(fill="x", padx=10)

    def _build_log_area(self):
        frame = ttk.Frame(self.root, padding=(10, 4))
        frame.pack(fill="both", expand=True)

        ttk.Label(frame, text="进程 / 日志", font=("", 10, "bold")).pack(anchor="w", pady=(0, 4))

        self.log_text = scrolledtext.ScrolledText(
            frame, state="disabled", height=18,
            font=("Consolas", 10), bg="#1e1e1e", fg="#d4d4d4",
            insertbackground="#d4d4d4", relief="flat"
        )
        self.log_text.pack(fill="both", expand=True)

        self.log_text.tag_configure("info", foreground="#d4d4d4")
        self.log_text.tag_configure("action", foreground="#569cd6")
        self.log_text.tag_configure("success", foreground="#4ec9b0")
        self.log_text.tag_configure("warn", foreground="#dcdcaa")
        self.log_text.tag_configure("error", foreground="#f44747")

        btn_frame = ttk.Frame(frame)
        btn_frame.pack(fill="x", pady=(4, 0))
        ttk.Button(btn_frame, text="清空日志", command=self._clear_log).pack(side="right")

    def _build_control_bar(self):
        sep = ttk.Separator(self.root, orient="horizontal")
        sep.pack(fill="x", padx=10)

        frame = ttk.Frame(self.root, padding=(10, 10))
        frame.pack(fill="x")

        self.start_btn = tk.Button(frame, text="● 开始录制", command=self._start_recording,
                                    width=14, bg="#2d7d46", fg="white",
                                    activebackground="#236b37", activeforeground="white",
                                    relief="flat")
        self.start_btn.pack(side="left", padx=(0, 8))

        self.stop_btn = tk.Button(frame, text="■ 结束录制", command=self._stop_recording,
                                   width=14, bg="#c42b1c", fg="white",
                                   activebackground="#a52015", activeforeground="white",
                                   disabledforeground="white",
                                   relief="flat", state="disabled")
        self.stop_btn.pack(side="left", padx=(0, 8))

        self.replay_btn = tk.Button(frame, text="▶ 回放", command=self._start_playback,
                                     width=10, bg="#1a73e8", fg="white",
                                     activebackground="#155ab6", activeforeground="white",
                                     relief="flat")
        self.replay_btn.pack(side="left", padx=(0, 8))

        self.clear_btn = tk.Button(frame, text="清空", command=self._clear_actions,
                                    width=8, relief="flat")
        self.clear_btn.pack(side="left", padx=(0, 12))

        self.screenshot_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(frame, text="录制时截图", variable=self.screenshot_var).pack(side="left")

        self.template_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(frame, text="裁剪点击模板", variable=self.template_var).pack(side="left", padx=(8, 0))

        self.status_var = tk.StringVar(value="就绪")
        ttk.Label(frame, textvariable=self.status_var, foreground="gray").pack(side="right")

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
        self.status_var.set("● 启动中...")
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
            self.root.after(0, lambda: self.status_var.set("● 录制中..."))
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
            self._asm.append(self._asm.codegen.emit(a))

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
        uia = a.get("params", {}).get("uia") or {}
        matched = a.get("params", {}).get("element_def", "")
        shot = a.get("params", {}).get("screenshot", "")
        tpl = a.get("params", {}).get("template", "")
        tag = f" [{matched}]" if matched else ""
        shot_tag = f" 📷" if shot else ""
        tpl_tag = f" 🎯" if tpl else ""
        self._log(f"  {a.get('type', '?')} {val}{tag}{shot_tag}{tpl_tag}", "action")

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

        self.replay_btn.configure(state="disabled")
        self.status_var.set("▶ 回放中...")
        self._log(f"=== 开始回放 {SCRIPT_FILE} ===", "success")
        threading.Thread(target=self._do_playback, daemon=True).start()

    def _do_playback(self):
        try:
            import uiautomator2 as u2
            serial = self.device_var.get().split("(")[-1].rstrip(")") if "(" in self.device_var.get() else ""
            d = u2.connect(serial) if serial else u2.connect()

            namespace = {"d": d, "__name__": "__main__", "time": __import__("time")}
            with open(SCRIPT_FILE, encoding="utf-8") as f:
                code = f.read()

            self._log(f"脚本内容:\n{code}", "info")
            exec(code, namespace)
            self._log("=== 回放完成 ===", "success")
        except Exception as e:
            self._log(f"=== 回放异常: {e} ===", "error")
            import traceback
            self._log(traceback.format_exc(), "error")
        finally:
            self.replay_btn.configure(state="normal")
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
    root = tk.Tk()
    app = RecorderApp(root)
    root.protocol("WM_DELETE_WINDOW", root.destroy)
    root.mainloop()


if __name__ == "__main__":
    main()