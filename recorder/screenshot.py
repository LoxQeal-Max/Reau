"""分级回退截图模块 — 独立、无副作用、可单独测试

不依赖项目其他模块，可独立 import 使用。
Android 16 兼容性：优先 uiautomator2，兜底 adb screencap。
"""
from __future__ import annotations

import io
import os
import subprocess
import time
from typing import Optional, Tuple


class ScreenshotStrategy:
    """分级回退截图：uiautomator2 → adb screencap → 失败返回 None"""

    def __init__(self, device_serial: str = "", adb_path: str = ""):
        self.device_serial = device_serial
        self.adb_path = adb_path or self._find_adb()
        self._d = None

    @staticmethod
    def _find_adb() -> str:
        candidates = []
        try:
            from airtest.core.android.adb import ADB
            candidates.append(ADB().adb_path)
        except Exception:
            pass
        candidates.append("adb")
        for p in candidates:
            if p == "adb":
                return p
            if os.path.exists(p):
                return p
        return "adb"

    def _adb_base(self) -> list[str]:
        cmd = [self.adb_path]
        if self.device_serial:
            cmd += ["-s", self.device_serial]
        return cmd

    def connect(self) -> bool:
        """建立 uiautomator2 连接，返回是否成功"""
        try:
            import uiautomator2 as u2
            if self.device_serial:
                self._d = u2.connect(self.device_serial)
            else:
                self._d = u2.connect()
            info = self._d.info
            print(f"[screenshot] uiautomator2 已连接: {info.get('productName')} "
                  f"[{info.get('displayWidth')}x{info.get('displayHeight')}]")
            return True
        except Exception as e:
            print(f"[screenshot] uiautomator2 连接失败: {e}")
            self._d = None
            return False

    def capture(self) -> Tuple[Optional[bytes], str]:
        """
        截图并返回 (png_bytes, method_name)。
        全部失败返回 (None, "all_failed")。
        """
        methods = [
            ("uiautomator2", self._capture_via_uia2),
            ("adb_screencap", self._capture_via_adb),
        ]
        for name, fn in methods:
            try:
                t0 = time.time()
                data = fn()
                dt = (time.time() - t0) * 1000
                if data and len(data) > 100:
                    print(f"[screenshot] ✅ {name} 成功: {len(data)} bytes, {dt:.0f}ms")
                    return data, name
                else:
                    print(f"[screenshot] ❌ {name} 返回空/无效 ({dt:.0f}ms)")
            except Exception as e:
                print(f"[screenshot] ❌ {name} 异常: {e}")
        print("[screenshot] ❌ 所有截图方式均失败")
        return None, "all_failed"

    # ─── L1: uiautomator2 ───
    def _capture_via_uia2(self) -> Optional[bytes]:
        if self._d is None:
            return None
        img = self._d.screenshot()
        if isinstance(img, bytes):
            return img
        if hasattr(img, 'save'):
            buf = io.BytesIO()
            img.save(buf, format='PNG')
            return buf.getvalue()
        if isinstance(img, str):
            with open(img, 'rb') as f:
                return f.read()
        return None

    # ─── L2: adb screencap (兜底) ───
    def _capture_via_adb(self) -> Optional[bytes]:
        try:
            r = subprocess.run(
                self._adb_base() + ["exec-out", "screencap", "-p"],
                capture_output=True, timeout=15)
            if r.returncode == 0 and r.stdout and len(r.stdout) > 100:
                return r.stdout
        except Exception as e:
            print(f"[screenshot] adb screencap 异常: {e}")
        return None

    def disconnect(self):
        if self._d:
            try:
                self._d.app.stop_all()
            except Exception:
                pass
            self._d = None

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *args):
        self.disconnect()
