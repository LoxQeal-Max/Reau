"""录制核心：采集器 → Action 列表 + 代码生成"""
from __future__ import annotations
import time
from typing import Optional
from .bus import bus
from .ir.action import Action
from .collectors import COLLECTORS, BaseCollector
from .codegen import Uia2Codegen
from .codegen.element_data import ELEMENT_REGISTRY


class RecorderCore:
    def __init__(self, codegen=None):
        self.codegen = codegen or Uia2Codegen()
        self.collector: Optional[BaseCollector] = None
        self.actions: list[Action] = []
        self.recording = False

    def start(self, platform: str, **conn):
        if self.recording:
            raise RuntimeError("已在录制中")
        self.actions.clear()
        self.recording = True
        self.collector = COLLECTORS[platform](on_event=self._on_event, **conn)
        self.collector.start(self._on_event)
        bus.publish("recording_start", {"platform": platform, "ts": time.time()})

    def _on_event(self, a: Action):
        if not self.recording:
            return
        self._try_match_element(a)
        self.actions.append(a)
        bus.publish("action", a.to_dict())
        code = self.codegen.emit(a)
        bus.publish("code", {"code": code})

    def _try_match_element(self, a: Action):
        uia_attrs = a.params.get("uia") or {}
        element_def = a.params.get("element_def")
        if element_def:
            return
        matched = ELEMENT_REGISTRY.match_by_attrs(uia_attrs)
        if matched:
            a.params["element_def"] = matched.name
            a.params["element_matched"] = True
            print(f"[录制] 元素匹配: {matched.name}", flush=True)

    def stop(self) -> list[Action]:
        if self.collector:
            self.collector.stop()
        self.recording = False
        bus.publish("recording_done", {"count": len(self.actions)})
        return self.actions
