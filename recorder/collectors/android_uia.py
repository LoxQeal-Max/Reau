"""Android 采集器：uiautomator2 + getevent 混合方案

  1. uiautomator2 (HTTP 端口转发) → dump UI 树，每 0.5s 刷新
  2. adb exec-out getevent -l → 监听触摸事件（独立 ADB 通道，不冲突）
  3. 坐标匹配 UI 控件 → 生成选择器优先 + 坐标兜底的 Action
"""
from __future__ import annotations
import os
import re
import time
import threading
import subprocess
import xml.etree.ElementTree as ET
from typing import Optional

from .base import BaseCollector
from ..ir.action import Action, TargetKind


_EV_LINE = re.compile(
    r"(?:\[[\s\d.]+\]\s*)?(/dev/input/event\d+):\s+(EV_ABS|EV_SYN|EV_KEY)\s+(\S+)\s+(.+)$")

_LABEL_MAP = {"DOWN": 1, "UP": 0, "PRESSED": 1, "RELEASED": 0, "TRUE": 1, "FALSE": 0}

def _parse_value(token: str) -> int:
    token = token.strip()
    if token in _LABEL_MAP:
        return _LABEL_MAP[token]
    try:
        return int(token, 16)
    except ValueError:
        try:
            return int(token)
        except ValueError:
            return 0


class AndroidUiaCollector(BaseCollector):
    def __init__(self, on_event=None, device_serial: str = "", adb_path: str = "",
                 enable_screenshot: bool = False, screenshot_dir: str = "",
                 enable_template: bool = False, template_dir: str = "",
                 template_size: int = 120, swipe_threshold: int = 30,
                 session_dir: str = "", **_):
        super().__init__(on_event)
        self.device_serial = device_serial
        self.adb_path = adb_path or self._find_adb()
        self._proc: Optional[subprocess.Popen] = None
        self._ge_thread: Optional[threading.Thread] = None
        self._ui_thread: Optional[threading.Thread] = None
        self._d = None
        self._xmin = self._xmax = self._ymin = self._ymax = None
        self._screen_w = self._screen_h = 0
        self._touch_devices: set = set()
        self._pending_x: Optional[int] = None
        self._pending_y: Optional[int] = None
        self._last_emit_ts = 0.0
        self._ui_cache: list[dict] = []
        self._ui_cache_lock = threading.Lock()
        self._ui_cache_ts = 0.0
        self._enable_screenshot = enable_screenshot
        self._screenshot_dir = screenshot_dir or (os.path.join(session_dir, "screenshots") if session_dir else "out/screenshots")
        self._shot_count = 0
        self._enable_template = enable_template
        self._template_dir = template_dir or (os.path.join(session_dir, "templates") if session_dir else "out/templates")
        self._template_size = template_size
        self._template_count = 0
        self._swipe_threshold = swipe_threshold
        self._touch_start_x: Optional[int] = None
        self._touch_start_y: Optional[int] = None
        self._touch_start_ts: float = 0.0

    @staticmethod
    def _find_adb():
        import os
        candidates = []
        try:
            from airtest.core.android.adb import ADB
            candidates.append(ADB().adb_path)
        except Exception:
            pass
        try:
            import airtest.core.android.adb as mod
            pkg_dir = os.path.dirname(mod.__file__)
            candidates.append(os.path.join(pkg_dir, "static", "adb", "windows", "adb.exe"))
            candidates.append(os.path.join(pkg_dir, "static", "adb", "mac", "adb"))
            candidates.append(os.path.join(pkg_dir, "static", "adb", "linux", "adb"))
        except Exception:
            pass
        try:
            import uiautomator2 as u2
            pkg = os.path.dirname(u2.__file__)
            for root, dirs, files in os.walk(pkg):
                for f in files:
                    if f == "adb.exe":
                        candidates.append(os.path.join(root, f))
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

    def _adb_run(self, args: list, timeout: int = 10) -> Optional[str]:
        try:
            creation_flags = 0
            if hasattr(subprocess, 'CREATE_NO_WINDOW'):
                creation_flags = subprocess.CREATE_NO_WINDOW
            r = subprocess.run(
                self._adb_base() + args,
                capture_output=True, text=True,
                encoding="utf-8", errors="ignore", timeout=timeout,
                creationflags=creation_flags)
            return r.stdout
        except Exception:
            return None

    # ---------- 生命周期 ----------
    def start(self, on_event):
        self.on_event = on_event
        self.running = True
        self._init_uiautomator2()
        self._init_scale()
        self._ui_thread = threading.Thread(target=self._ui_cache_loop, daemon=True)
        self._ui_thread.start()
        self._ge_thread = threading.Thread(target=self._getevent_loop, daemon=True)
        self._ge_thread.start()

    def _init_uiautomator2(self):
        import uiautomator2 as u2
        try:
            if self.device_serial:
                self._d = u2.connect(self.device_serial)
            else:
                self._d = u2.connect()
            info = self._d.info
            self._screen_w = info.get("displayWidth", 1080)
            self._screen_h = info.get("displayHeight", 2520)
            model = info.get("productName", "unknown")
            print(f"[android] 设备: {model} 屏[{self._screen_w}x{self._screen_h}]", flush=True)
        except Exception as e:
            print(f"[android] uiautomator2 连接失败: {e}", flush=True)
            self._screen_w = 1080
            self._screen_h = 2520

    def _init_scale(self):
        try:
            out = self._adb_run(["shell", "getevent", "-lp"], timeout=5) or ""
            cur_dev = None
            best_xmax = -1
            for line in out.splitlines():
                low = line.lower()
                m_dev = re.match(r"\s*add device\s+\d+:\s*(/dev/input/event\d+)", low)
                if m_dev:
                    cur_dev = m_dev.group(1)
                    continue
                if cur_dev and "abs_mt_position_x" in low:
                    self._touch_devices.add(cur_dev)
                    m = re.search(r"min\s+(-?\d+)\s*,?\s*max\s+(-?\d+)", low)
                    if m:
                        xmax = int(m.group(2))
                        if xmax > best_xmax:
                            best_xmax = xmax
                            self._xmin, self._xmax = int(m.group(1)), xmax
                elif cur_dev and "abs_mt_position_y" in low:
                    m = re.search(r"min\s+(-?\d+)\s*,?\s*max\s+(-?\d+)", low)
                    if m and self._xmax == best_xmax:
                        self._ymin, self._ymax = int(m.group(1)), int(m.group(2))
            if self._touch_devices:
                print(f"[android] 触摸屏: {self._touch_devices} "
                      f"X[{self._xmin},{self._xmax}] Y[{self._ymin},{self._ymax}]", flush=True)
        except Exception as e:
            print(f"[android] _init_scale 异常: {e}", flush=True)

    def _scale(self, raw_x: int, raw_y: int):
        sx = float(raw_x)
        sy = float(raw_y)
        if self._xmax and self._xmax != self._screen_w:
            sx = raw_x * self._screen_w / self._xmax
        if self._ymax and self._ymax != self._screen_h:
            sy = raw_y * self._screen_h / self._ymax
        return int(round(sx)), int(round(sy))

    # ---------- UI 树缓存线程 (uiautomator2) ----------
    def _ui_cache_loop(self):
        print("[android] UI 树缓存线程启动 (uiautomator2)", flush=True)
        while self.running:
            try:
                if self._d:
                    xml_str = self._d.dump_hierarchy()
                    if xml_str:
                        cache = self._parse_ui_xml(xml_str)
                        with self._ui_cache_lock:
                            self._ui_cache = cache
                            self._ui_cache_ts = time.time()
            except Exception as e:
                pass
            if not self.running:
                break
            time.sleep(0.5)
        print("[android] UI 树缓存线程停止", flush=True)

    def _parse_ui_xml(self, xml_str: str) -> list[dict]:
        cache = []
        try:
            root = ET.fromstring(xml_str)
            self._walk_xml(root, cache)
        except Exception:
            pass
        return cache

    def _walk_xml(self, node: ET.Element, out: list):
        bounds_str = node.get("bounds", "")
        text = node.get("text", "")
        rid = node.get("resource-id", "")
        cls = node.get("class", "")
        desc = node.get("content-desc", "")
        if bounds_str:
            try:
                parts = bounds_str.replace("][", ",").replace("[", "").replace("]", "")
                coords = [int(x) for x in parts.split(",")]
                if len(coords) == 4:
                    x1, y1, x2, y2 = coords
                    out.append({
                        "text": text,
                        "resource_id": rid,
                        "class": cls,
                        "content_desc": desc,
                        "bounds": (x1, y1, x2, y2),
                    })
            except Exception:
                pass
        for child in node:
            self._walk_xml(child, out)

    def _find_node_at(self, x: int, y: int) -> Optional[dict]:
        with self._ui_cache_lock:
            cache = list(self._ui_cache)
        if not cache:
            return None
        best = None
        best_area = float("inf")
        for item in cache:
            x1, y1, x2, y2 = item["bounds"]
            if x1 <= x <= x2 and y1 <= y <= y2:
                area = (x2 - x1) * (y2 - y1)
                if area < best_area:
                    best_area = area
                    best = item
        return best

    # ---------- getevent 监听线程 ----------
    def _getevent_loop(self):
        try:
            self._getevent_loop_impl()
        except Exception as e:
            print(f"[android] getevent 异常: {e}", flush=True)

    def _getevent_loop_impl(self):
        cmd = self._adb_base() + ["exec-out", "getevent", "-l"]
        print(f"[android] 启动 getevent (exec-out): {' '.join(cmd)}", flush=True)
        try:
            creation_flags = 0
            if hasattr(subprocess, 'CREATE_NO_WINDOW'):
                creation_flags = subprocess.CREATE_NO_WINDOW
            self._proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                bufsize=0, creationflags=creation_flags)
        except FileNotFoundError:
            print("[android] 找不到 adb", flush=True)
            return
        print("[android] getevent 已启动，等待触摸...", flush=True)
        buf = b""
        line_count = 0
        while self.running:
            chunk = self._proc.stdout.read(4096)
            if not chunk:
                if self._proc.poll() is not None:
                    break
                continue
            buf += chunk
            while b"\n" in buf:
                line_bytes, buf = buf.split(b"\n", 1)
                try:
                    line = line_bytes.decode("utf-8", errors="ignore").rstrip("\r")
                except Exception:
                    continue
                if line:
                    line_count += 1
                    if line_count <= 5 or line_count % 50 == 0:
                        print(f"[android] GE #{line_count}: {line}", flush=True)
                    self._handle_line(line)
        try:
            self._proc.wait(timeout=2)
        except Exception:
            pass

    def _handle_line(self, line: str):
        m = _EV_LINE.match(line)
        if not m:
            print(f"[android] NO MATCH: {line}", flush=True)
            return
        dev_path, evtype, code, raw_val = m.groups()
        # 动态学习触摸设备：游戏运行中可能切换触摸上报路径，
        # 见到 ABS_MT_POSITION_X/Y 事件的设备即时加入白名单，避免滑动事件被丢弃
        if evtype == "EV_ABS" and code in ("ABS_MT_POSITION_X", "ABS_MT_POSITION_Y"):
            if dev_path not in self._touch_devices:
                self._touch_devices.add(dev_path)
                print(f"[android] 动态加入触摸设备: {dev_path}", flush=True)
        if self._touch_devices and dev_path not in self._touch_devices:
            return
        val = _parse_value(raw_val)
        if evtype == "EV_ABS":
            if code == "ABS_MT_TRACKING_ID":
                if val >= 0x80000000 or val == -1:
                    self._flush_touch()
                else:
                    self._touch_start_x = None
                    self._touch_start_y = None
            elif code == "ABS_MT_POSITION_X":
                self._pending_x = val
            elif code == "ABS_MT_POSITION_Y":
                self._pending_y = val
                if self._touch_start_x is None and self._pending_x is not None:
                    sx, sy = self._scale(self._pending_x, val)
                    self._touch_start_x = sx
                    self._touch_start_y = sy
                    self._touch_start_ts = time.time()
        elif evtype == "EV_KEY":
            if code == "BTN_TOUCH" and val == 0:
                self._flush_touch()

    def _flush_touch(self):
        x, y = self._pending_x, self._pending_y
        if x is None or y is None:
            return
        now = time.time()
        if now - self._last_emit_ts < 0.15:
            self._pending_x = self._pending_y = None
            self._touch_start_x = self._touch_start_y = None
            return
        sx, sy = self._scale(x, y)
        if self._screen_w and (sx < 0 or sx > self._screen_w or sy < 0 or sy > self._screen_h):
            self._pending_x = self._pending_y = None
            self._touch_start_x = self._touch_start_y = None
            return

        is_swipe = False
        is_long_press = False
        duration = 0.0
        
        if self._touch_start_x is not None and self._touch_start_y is not None:
            import math
            dx = sx - self._touch_start_x
            dy = sy - self._touch_start_y
            distance = math.sqrt(dx * dx + dy * dy)
            duration = now - self._touch_start_ts
            
            # 检测长按: 移动距离小且持续时间长
            if distance < self._swipe_threshold and duration >= 0.5:
                is_long_press = True
            elif distance >= self._swipe_threshold and duration > 0.05:
                is_swipe = True

        if is_swipe:
            self._emit_swipe(sx, sy, now)
        elif is_long_press:
            self._emit_long_press(sx, sy, now, duration)
        else:
            self._emit_touch(sx, sy, now)

        self._last_emit_ts = now
        self._pending_x = self._pending_y = None
        self._touch_start_x = self._touch_start_y = None

    def _emit_touch(self, sx: int, sy: int, now: float):
        node = self._find_node_at(sx, sy)
        uia_attrs = {}
        if node:
            if node.get("text"):
                uia_attrs["text"] = node["text"]
            elif node.get("resource_id"):
                rid = node["resource_id"]
                short_rid = rid.split(":id/")[-1] if ":id/" in rid else rid
                uia_attrs["resourceId"] = short_rid
            elif node.get("content_desc"):
                uia_attrs["contentDesc"] = node["content_desc"]
            elif node.get("class"):
                uia_attrs["className"] = node["class"]

        kind_desc = "UIA" if uia_attrs else "坐标"
        scale_info = f"(屏幕{self._screen_w}x{self._screen_h}, 触摸X[{self._xmin},{self._xmax}]Y[{self._ymin},{self._ymax}])"
        print(f"[android] 点击: ({sx},{sy}) {kind_desc} {scale_info}", flush=True)

        action_params = {"uia": uia_attrs, "element": node or {}}
        shot_path = self._try_screenshot(sx, sy)
        if shot_path:
            action_params["screenshot"] = shot_path
        template_path = self._try_template(sx, sy)
        if template_path:
            action_params["template"] = template_path
            print(f"[android] 模板已裁剪: {template_path}", flush=True)

        self.emit(Action(
            type="touch",
            target={"kind": TargetKind.COORD, "value": (sx, sy)},
            platform="android",
            timestamp=now,
            params=action_params,
        ))

    def _emit_long_press(self, sx: int, sy: int, now: float, duration: float):
        node = self._find_node_at(sx, sy)
        uia_attrs = {}
        if node:
            if node.get("text"):
                uia_attrs["text"] = node["text"]
            elif node.get("resource_id"):
                rid = node["resource_id"]
                short_rid = rid.split(":id/")[-1] if ":id/" in rid else rid
                uia_attrs["resourceId"] = short_rid
            elif node.get("content_desc"):
                uia_attrs["contentDesc"] = node["content_desc"]
            elif node.get("class"):
                uia_attrs["className"] = node["class"]

        kind_desc = "UIA" if uia_attrs else "坐标"
        print(f"[android] 长按: ({sx},{sy}) {kind_desc} 时长={duration:.2f}s", flush=True)

        action_params = {"uia": uia_attrs, "element": node or {}, "duration": duration}
        shot_path = self._try_screenshot(sx, sy)
        if shot_path:
            action_params["screenshot"] = shot_path
        template_path = self._try_template(sx, sy)
        if template_path:
            action_params["template"] = template_path

        self.emit(Action(
            type="long_press",
            target={"kind": TargetKind.COORD, "value": (sx, sy)},
            platform="android",
            timestamp=now,
            params=action_params,
        ))

    def _emit_swipe(self, end_x: int, end_y: int, now: float):
        start_x = self._touch_start_x
        start_y = self._touch_start_y
        dx = end_x - start_x
        dy = end_y - start_y
        import math
        distance = math.sqrt(dx * dx + dy * dy)
        duration = now - self._touch_start_ts
        direction = "down" if abs(dy) > abs(dx) else ("left" if dx < 0 else "right") if abs(dx) > abs(dy) else ("up" if dy < 0 else "down")

        if abs(dx) > abs(dy):
            direction = "left" if dx < 0 else "right"
        else:
            direction = "up" if dy < 0 else "down"

        print(f"[android] 滑动: ({start_x},{start_y}) -> ({end_x},{end_y}) "
              f"距离={distance:.0f}px 方向={direction} 时长={duration:.2f}s", flush=True)

        action_params = {
            "start": (start_x, start_y),
            "end": (end_x, end_y),
            "distance": distance,
            "direction": direction,
            "duration": duration,
        }

        self.emit(Action(
            type="swipe",
            target={"kind": TargetKind.COORD, "value": (start_x, start_y, end_x, end_y)},
            platform="android",
            timestamp=now,
            params=action_params,
        ))

    # ---------- 可选截图 ----------
    def _try_screenshot(self, click_x: int = 0, click_y: int = 0) -> Optional[str]:
        if not self._enable_screenshot or self._d is None:
            return None
        try:
            import os
            from datetime import datetime
            os.makedirs(self._screenshot_dir, exist_ok=True)
            img = self._d.screenshot()
            if hasattr(img, 'save'):
                import io
                buf = io.BytesIO()
                img.save(buf, format='PNG')
                data = buf.getvalue()
            elif isinstance(img, bytes):
                data = img
            else:
                return None
            ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
            path = os.path.join(self._screenshot_dir, f"shot_{self._shot_count:04d}_{ts}.png")
            with open(path, 'wb') as f:
                f.write(data)
            self._shot_count += 1
            return path
        except Exception as e:
            print(f"[android] 截图失败: {e}", flush=True)
            return None

    # ---------- 可选模板裁剪 ----------
    def _try_template(self, click_x: int, click_y: int) -> Optional[str]:
        if not self._enable_template or self._d is None:
            return None
        try:
            import os
            import numpy as np
            from datetime import datetime
            os.makedirs(self._template_dir, exist_ok=True)
            img = self._d.screenshot()
            if not hasattr(img, 'save'):
                return None

            tpl_size = self._template_size
            node = self._find_node_at(click_x, click_y)
            if node:
                x1, y1, x2, y2 = node.get("bounds", (0, 0, 0, 0))
                w, h = x2 - x1, y2 - y1
                if w > 0 and h > 0 and w <= 300 and h <= 300:
                    tpl_size = max(w, h) + 20
                    print(f"[android] 模板尺寸调整: {self._template_size} -> {tpl_size} (UI节点 {w}x{h})", flush=True)

            half = tpl_size // 2
            x1 = max(0, click_x - half)
            y1 = max(0, click_y - half)
            x2 = min(self._screen_w, click_x + half)
            y2 = min(self._screen_h, click_y + half)

            if x2 - x1 < 15 or y2 - y1 < 15:
                return None

            cropped = img.crop((x1, y1, x2, y2))

            arr = np.array(cropped)
            if arr.size > 0:
                std_val = arr.std()
                if std_val < 5:
                    print(f"[android] 模板特征过少(std={std_val:.1f})，可能是纯色区域", flush=True)

            ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
            path = os.path.join(self._template_dir, f"tpl_{self._template_count:04d}_{ts}.png")
            cropped.save(path, 'PNG')
            self._template_count += 1
            try:
                rel_path = os.path.relpath(path, os.getcwd())
            except ValueError:
                rel_path = path
            print(f"[android] 模板裁剪: ({click_x},{click_y}) 区域({x1},{y1})-({x2},{y2}) 尺寸{tpl_size}", flush=True)
            return rel_path
        except Exception as e:
            print(f"[android] 模板裁剪失败: {e}", flush=True)
            return None

    # ---------- 停止 ----------
    def stop(self):
        self.running = False
        if self._proc:
            try:
                self._proc.terminate()
            except Exception:
                pass
        if self._ge_thread:
            self._ge_thread.join(timeout=3)
        if self._ui_thread:
            self._ui_thread.join(timeout=3)
        if self._d:
            try:
                self._d.disconnect()
            except Exception:
                pass

    def snapshot(self) -> dict:
        return {"screen": {"width": self._screen_w, "height": self._screen_h},
                "ui_cache_size": len(self._ui_cache)}