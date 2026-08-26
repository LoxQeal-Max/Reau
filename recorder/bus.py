"""进程内事件总线（采集层 -> 代码生成/编辑器/WebUI 三方订阅）"""
from __future__ import annotations
from collections import defaultdict
from typing import Callable, Any
import threading


class EventBus:
    """简易 pub/sub 总线，线程安全。

    用途：
      采集器产出 Action -> bus.publish("action", action)
      WebUI 后端订阅 -> 实时推前端看板
      编辑器桥接订阅 -> 实时插代码
    """

    def __init__(self):
        self._subscribers: dict[str, list[Callable[[Any], None]]] = defaultdict(list)
        self._lock = threading.Lock()

    def subscribe(self, topic: str, handler: Callable[[Any], None]):
        with self._lock:
            self._subscribers[topic].append(handler)

    def publish(self, topic: str, data: Any = None):
        with self._lock:
            handlers = list(self._subscribers.get(topic, []))
        for h in handlers:
            try:
                h(data)
            except Exception as e:
                print(f"[bus] handler error topic={topic}: {e}")

    def stream(self):
        """占位：供异步迭代接入 WebSocket。P3 接入。"""
        raise NotImplementedError("async stream 在 webui/backend 实现")


# 单例
bus = EventBus()
