"""录制自动化工具 - 入口

用法：
  python demo_auto.py              # 启动 GUI
  python demo_auto.py --gui        # 启动 GUI
  python demo_auto.py 30           # 定时录制 30 秒（命令行）
  python demo_auto.py 30 SERIAL    # 指定秒数和设备
  python demo_auto.py --replay     # 回放上次录制的脚本
"""
from __future__ import annotations
import os
import sys
import time
import threading
import logging

for _n in ("airtest", "airtest.core", "airtest.utils", "airtest.aircv", "poco", "pocounit", "uiautomator2"):
    logging.getLogger(_n).setLevel(logging.WARNING)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

OUTPUT_DIR = "out"
SCRIPT_FILE = os.path.join(OUTPUT_DIR, "script.py")
DEFAULT_SERIAL = ""


def main():
    args = sys.argv[1:]

    if not args or "--gui" in args:
        return _launch_gui()

    seconds = None
    serial = DEFAULT_SERIAL
    do_replay = False

    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--replay":
            do_replay = True
        elif arg == "--serial" and i + 1 < len(args):
            serial = args[i + 1]
            i += 1
        elif arg.isdigit():
            seconds = int(arg)
        elif not arg.startswith("--"):
            serial = arg
        i += 1

    if do_replay:
        return _replay(serial)

    return _cli_record(seconds, serial)


def _launch_gui():
    from gui.main import main as gui_main
    gui_main()


def _cli_record(seconds: int | None, serial: str):
    from recorder.recorder_core import RecorderCore
    from recorder.air_assembler import ScriptAssembler
    from recorder.bus import bus
    from recorder.codegen.element_data import load_default_elements

    load_default_elements()

    asm = ScriptAssembler(OUTPUT_DIR)
    rec = RecorderCore(codegen=asm.codegen)

    def _on_action(a):
        tgt = a.get("target", {})
        val = tgt.get("value", "")
        matched = a.get("params", {}).get("element_def", "")
        tag = f" [{matched}]" if matched else ""
        print(f"  [action] {a['type']} {val}{tag}", flush=True)

    def _on_code(c):
        print(f"  [code]   {c['code']}", flush=True)

    bus.subscribe("action", _on_action)
    bus.subscribe("code", _on_code)

    if seconds:
        print(f"=== 开始录制（请在 {seconds} 秒内触摸屏幕）===\n", flush=True)
    else:
        print("=== 开始录制（触摸屏幕，按 Enter 结束）===\n", flush=True)

    rec.start("android", device_serial=serial)

    stop_evt = threading.Event()

    def _timer():
        time.sleep(seconds)
        stop_evt.set()

    def _wait_enter():
        try:
            input()
        except (EOFError, KeyboardInterrupt):
            time.sleep(60)
        stop_evt.set()

    t = threading.Thread(target=_timer if seconds else _wait_enter, daemon=True)
    t.start()
    stop_evt.wait()

    print("\n=== 结束录制 ===", flush=True)
    actions = rec.stop()
    print(f"共 {len(actions)} 条 action", flush=True)
    for a in actions:
        asm.append(asm.codegen.emit(a))

    script_path = asm.build()
    print(f"\n脚本已生成: {script_path}", flush=True)

    with open(script_path, encoding="utf-8") as f:
        print(f.read(), flush=True)

    if actions:
        print(f"\n回放: python demo_auto.py --replay", flush=True)


def _replay(serial: str):
    if not os.path.exists(SCRIPT_FILE):
        print(f"找不到脚本: {SCRIPT_FILE}", flush=True)
        return

    import uiautomator2 as u2

    print(f"=== 回放 {SCRIPT_FILE} ===", flush=True)
    try:
        d = u2.connect(serial) if serial else u2.connect()
        print(f"已连接设备", flush=True)
    except Exception as e:
        print(f"连接失败: {e}", flush=True)
        return

    namespace = {"d": d, "__name__": "__main__", "time": __import__("time")}
    with open(SCRIPT_FILE, encoding="utf-8") as f:
        code = f.read()

    print(f"脚本内容:\n{code}", flush=True)
    try:
        exec(code, namespace)
        print("\n=== 回放完成 ===", flush=True)
    except Exception as e:
        print(f"\n=== 回放异常: {e} ===", flush=True)
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()