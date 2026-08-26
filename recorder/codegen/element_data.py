"""元素数据配置：定义 UI 元素的定位方式

借鉴 Auto_test 的 element_data.py 思路，用配置文件定义可识别的 UI 元素。
录制时匹配配置中的元素名，回放时用 uiautomator2 的选择器定位。

支持的定位方式（优先级从高到低）：
  1. resourceId  - Android resource-id
  2. text        - 控件文本
  3. contentDesc - content-description
  4. className   - 控件类名
  5. xpath       - XPath 表达式
  6. coord       - 纯坐标兜底

用法：
  from recorder.codegen.element_data import ELEMENT_REGISTRY

  ELEMENT_REGISTRY.register("login_button", resourceId="com.example:id/btn_login")
  ELEMENT_REGISTRY.register("home_title", text="首页")
  ELEMENT_REGISTRY.register("submit_btn", xpath='//*[@text="提交"]')
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional, Dict, List


@dataclass
class ElementDef:
    name: str
    resourceId: Optional[str] = None
    text: Optional[str] = None
    contentDesc: Optional[str] = None
    className: Optional[str] = None
    xpath: Optional[str] = None
    description: str = ""


class ElementRegistry:
    def __init__(self):
        self._elements: Dict[str, ElementDef] = {}

    def register(self, name: str, **kwargs) -> ElementDef:
        elem = ElementDef(name=name, **kwargs)
        self._elements[name] = elem
        return elem

    def get(self, name: str) -> Optional[ElementDef]:
        return self._elements.get(name)

    def list_all(self) -> List[ElementDef]:
        return list(self._elements.values())

    def match_by_attrs(self, attrs: dict) -> Optional[ElementDef]:
        if not attrs:
            return None
        for elem in self._elements.values():
            if elem.resourceId and attrs.get("resourceId"):
                if elem.resourceId == attrs["resourceId"]:
                    return elem
            if elem.text and attrs.get("text"):
                if elem.text == attrs["text"]:
                    return elem
            if elem.contentDesc and attrs.get("contentDesc"):
                if elem.contentDesc == attrs["contentDesc"]:
                    return elem
        return None

    def clear(self):
        self._elements.clear()


ELEMENT_REGISTRY = ElementRegistry()


def load_default_elements():
    ELEMENT_REGISTRY.clear()
    ELEMENT_REGISTRY.register("home_back_button", resourceId="com.android.systemui:id/back")
    ELEMENT_REGISTRY.register("home_home_button", resourceId="com.android.systemui:id/home")
    ELEMENT_REGISTRY.register("home_recent_button", resourceId="com.android.systemui:id/recent")
    ELEMENT_REGISTRY.register("settings", text="设置")
    ELEMENT_REGISTRY.register("ok", text="确定")
    ELEMENT_REGISTRY.register("cancel", text="取消")
    ELEMENT_REGISTRY.register("allow", text="允许")
    ELEMENT_REGISTRY.register("deny", text="拒绝")
