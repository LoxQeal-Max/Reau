"""统一 Action IR：所有平台采集到的事件归一为此结构"""
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Dict, Any


class TargetKind(str, Enum):
    COORD = "coord"
    UIA = "uia"


class ActionType(str, Enum):
    TOUCH = "touch"
    SWIPE = "swipe"


@dataclass
class Action:
    type: str
    target: Dict[str, Any]
    platform: str = ""
    params: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = 0.0

    def to_dict(self) -> dict:
        return {
            "type": self.type,
            "target": {**self.target, "kind": self.target.get("kind", TargetKind.COORD)},
            "platform": self.platform,
            "params": self.params,
            "timestamp": self.timestamp,
        }
