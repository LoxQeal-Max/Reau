"""设备接口数据模型 - AI Agent 与设备交互的标准协议"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional
from enum import Enum


class ActionType(Enum):
    """操作类型"""
    CLICK = "click"
    SWIPE = "swipe"
    LONG_PRESS = "long_press"
    INPUT_TEXT = "input_text"
    WAIT = "wait"
    SCREENSHOT = "screenshot"
    GET_STATE = "get_state"


class ErrorCode(Enum):
    """错误码"""
    SUCCESS = 0
    DEVICE_NOT_CONNECTED = 1001
    DEVICE_DISCONNECTED = 1002
    SCREENSHOT_FAILED = 2001
    UI_DUMP_FAILED = 2002
    CLICK_FAILED = 3001
    CLICK_VERIFY_FAILED = 3002
    SWIPE_FAILED = 3101
    LONG_PRESS_FAILED = 3201
    INPUT_FAILED = 3301
    TEMPLATE_NOT_FOUND = 4001
    TEMPLATE_MATCH_LOW = 4002
    SELECTOR_NOT_FOUND = 4003
    TIMEOUT = 5001
    UNKNOWN_ERROR = 9999


@dataclass
class DeviceAction:
    """设备操作"""
    type: ActionType
    target: dict = field(default_factory=dict)
    params: dict = field(default_factory=dict)
    
    @classmethod
    def click_by_coord(cls, x: int, y: int) -> DeviceAction:
        return cls(
            type=ActionType.CLICK,
            target={"kind": "coord", "x": x, "y": y}
        )
    
    @classmethod
    def click_by_text(cls, text: str,
                      fallback_x: int = 0, fallback_y: int = 0) -> DeviceAction:
        target = {"kind": "text", "text": text}
        if fallback_x or fallback_y:
            target["fallback"] = {"x": fallback_x, "y": fallback_y}
        return cls(type=ActionType.CLICK, target=target)
    
    @classmethod
    def click_by_resource_id(cls, resource_id: str) -> DeviceAction:
        return cls(
            type=ActionType.CLICK,
            target={"kind": "resource_id", "resource_id": resource_id}
        )
    
    @classmethod
    def click_by_template(cls, template_path: str, 
                           fallback_x: int = 0, fallback_y: int = 0) -> DeviceAction:
        return cls(
            type=ActionType.CLICK,
            target={
                "kind": "template", 
                "template_path": template_path,
                "fallback": {"x": fallback_x, "y": fallback_y}
            }
        )
    
    @classmethod
    def swipe(cls, sx: int, sy: int, ex: int, ey: int, duration: float = 0.5) -> DeviceAction:
        return cls(
            type=ActionType.SWIPE,
            target={"kind": "coord", "start": (sx, sy), "end": (ex, ey)},
            params={"duration": duration}
        )
    
    @classmethod
    def long_press(cls, x: int, y: int, duration: float = 1.0) -> DeviceAction:
        return cls(
            type=ActionType.LONG_PRESS,
            target={"kind": "coord", "x": x, "y": y},
            params={"duration": duration}
        )
    
    @classmethod
    def input_text(cls, text: str) -> DeviceAction:
        return cls(
            type=ActionType.INPUT_TEXT,
            target={"kind": "input"},
            params={"text": text}
        )
    
    @classmethod
    def wait(cls, seconds: float) -> DeviceAction:
        return cls(
            type=ActionType.WAIT,
            params={"seconds": seconds}
        )
    
    @classmethod
    def screenshot(cls) -> DeviceAction:
        return cls(type=ActionType.SCREENSHOT)
    
    @classmethod
    def get_state(cls) -> DeviceAction:
        return cls(type=ActionType.GET_STATE)


@dataclass
class ScreenElement:
    """屏幕 UI 元素"""
    text: str = ""
    resource_id: str = ""
    content_desc: str = ""
    class_name: str = ""
    bounds: tuple = (0, 0, 0, 0)
    enabled: bool = True
    selected: bool = False
    checked: bool = False


@dataclass
class ScreenState:
    """屏幕状态"""
    screenshot: Optional[bytes] = None
    screenshot_path: str = ""
    ui_elements: list = field(default_factory=list)
    page_name: str = ""
    device_width: int = 0
    device_height: int = 0
    timestamp: float = 0.0
    
    def get_element_by_text(self, text: str) -> Optional[ScreenElement]:
        for elem in self.ui_elements:
            if elem.text == text:
                return elem
        return None
    
    def get_elements_by_text_contains(self, keyword: str) -> list:
        return [e for e in self.ui_elements if keyword in e.text]


@dataclass
class DeviceResult:
    """设备操作结果"""
    success: bool = False
    code: ErrorCode = ErrorCode.UNKNOWN_ERROR
    message: str = ""
    screen_state: Optional[ScreenState] = None
    action_detail: dict = field(default_factory=dict)
    execution_time: float = 0.0
    
    @classmethod
    def success(cls, screen_state: Optional[ScreenState] = None, 
                detail: Optional[dict] = None) -> DeviceResult:
        return cls(
            success=True,
            code=ErrorCode.SUCCESS,
            message="操作成功",
            screen_state=screen_state,
            action_detail=detail or {},
        )
    
    @classmethod
    def failure(cls, code: ErrorCode, message: str = "",
                detail: Optional[dict] = None) -> DeviceResult:
        return cls(
            success=False,
            code=code,
            message=message or code.name,
            action_detail=detail or {},
        )
    
    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "code": self.code.value,
            "code_name": self.code.name,
            "message": self.message,
            "execution_time": self.execution_time,
            "detail": self.action_detail,
        }
