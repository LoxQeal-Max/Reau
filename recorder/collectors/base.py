"""采集器抽象基类：所有平台采集器实现统一接口"""
from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Callable, Optional
from ..ir.action import Action


class BaseCollector(ABC):
    """子类需在 start() 中启动采集线程，事件回调到 on_event"""

    def __init__(self, on_event: Optional[Callable[[Action], None]] = None, **conn):
        self.on_event = on_event
        self.conn = conn
        self.running = False
        self._recorded_actions: list = []

    def emit(self, action: Action):
        """子类采集到事件后调用此方法上抛"""
        self._recorded_actions.append(action)
        if self.on_event and self.running:
            self.on_event(action)

    @abstractmethod
    def start(self, on_event: Callable[[Action], None]):
        """启动采集，事件经 on_event 上抛"""

    @abstractmethod
    def stop(self):
        """停止采集，释放资源"""

    def snapshot(self) -> dict:
        """采集一次 UI 树快照（供 Agent 查询）"""
        raise NotImplementedError(f"{self.__class__.__name__} 暂未实现 snapshot")
