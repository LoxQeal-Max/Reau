"""设备接口 - AI Agent 与设备交互的标准接口"""
from __future__ import annotations
import os
import time
import threading
from typing import Optional

from .models import (
    ActionType,
    DeviceAction,
    DeviceResult,
    ErrorCode,
    ScreenElement,
    ScreenState,
)


class DeviceInterface:
    """设备接口基类 - 为 AI Agent 提供标准操作接口
    
    使用示例:
        device = DeviceInterface(serial="xxx")
        device.connect()
        state = device.get_state()
        result = device.execute(DeviceAction.click_by_text("确定"))
    """
    
    def __init__(self, serial: str = "", adb_path: str = ""):
        self.serial = serial
        self.adb_path = adb_path
        self._d = None
        self._connected = False
        self._screen_state: Optional[ScreenState] = None
        self._lock = threading.Lock()
    
    @property
    def is_connected(self) -> bool:
        return self._connected and self._d is not None
    
    def connect(self) -> bool:
        try:
            import uiautomator2 as u2
            if self.serial:
                self._d = u2.connect(self.serial)
            else:
                self._d = u2.connect()
            self._connected = True
            info = self._d.info
            self.serial = info.get("serial", self.serial)
            self._log(f"已连接设备: {info.get('productName')} [{info.get('displayWidth')}x{info.get('displayHeight')}]")
            return True
        except Exception as e:
            self._log(f"连接设备失败: {e}")
            self._connected = False
            return False
    
    def disconnect(self):
        self._d = None
        self._connected = False
        self._log("已断开连接")
    
    def get_state(self, include_screenshot: bool = True, 
                  include_ui: bool = True) -> ScreenState:
        """获取当前屏幕状态"""
        with self._lock:
            if not self._check_connected():
                return ScreenState()
            
            state = ScreenState(timestamp=time.time())
            
            try:
                info = self._d.info
                state.device_width = info.get("displayWidth", 0)
                state.device_height = info.get("displayHeight", 0)
            except Exception:
                pass
            
            if include_screenshot:
                try:
                    img = self._d.screenshot()
                    if hasattr(img, 'save'):
                        import io
                        buf = io.BytesIO()
                        img.save(buf, format='PNG')
                        state.screenshot = buf.getvalue()
                    elif isinstance(img, bytes):
                        state.screenshot = img
                except Exception as e:
                    self._log(f"截图失败: {e}")
            
            if include_ui:
                try:
                    hierarchy = self._d.dump_hierarchy()
                    state.ui_elements = self._parse_hierarchy(hierarchy)
                except Exception as e:
                    self._log(f"UI dump失败: {e}")
            
            self._screen_state = state
            return state
    
    def execute(self, action: DeviceAction) -> DeviceResult:
        """执行操作，返回结果"""
        start_time = time.time()
        
        with self._lock:
            if not self._check_connected():
                return DeviceResult.failure(
                    code=ErrorCode.DEVICE_NOT_CONNECTED,
                    message="设备未连接"
                )
            
            try:
                result = self._execute_action(action)
                result.execution_time = time.time() - start_time
                return result
            except Exception as e:
                self._log(f"执行异常: {e}")
                return DeviceResult.failure(
                    code=ErrorCode.UNKNOWN_ERROR,
                    message=str(e),
                    detail={"action": action.type.value}
                )
    
    def _execute_action(self, action: DeviceAction) -> DeviceResult:
        """执行具体操作"""
        action_type = action.type
        
        if action_type == ActionType.CLICK:
            return self._do_click(action)
        elif action_type == ActionType.SWIPE:
            return self._do_swipe(action)
        elif action_type == ActionType.LONG_PRESS:
            return self._do_long_press(action)
        elif action_type == ActionType.INPUT_TEXT:
            return self._do_input_text(action)
        elif action_type == ActionType.WAIT:
            return self._do_wait(action)
        elif action_type == ActionType.SCREENSHOT:
            return self._do_screenshot()
        elif action_type == ActionType.GET_STATE:
            state = self.get_state()
            return DeviceResult.success(screen_state=state)
        else:
            return DeviceResult.failure(
                code=ErrorCode.UNKNOWN_ERROR,
                message=f"不支持的操作类型: {action_type}"
            )
    
    def _do_click(self, action: DeviceAction) -> DeviceResult:
        """执行点击"""
        target = action.target
        kind = target.get("kind", "")
        
        if kind == "coord":
            x, y = target.get("x", 0), target.get("y", 0)
            try:
                self._d.click(x, y)
                self._log(f"坐标点击: ({x}, {y})")
                return DeviceResult.success(
                    detail={"method": "coord", "x": x, "y": y}
                )
            except Exception as e:
                return DeviceResult.failure(
                    code=ErrorCode.CLICK_FAILED,
                    message=str(e),
                    detail={"method": "coord", "x": x, "y": y}
                )
        
        elif kind == "text":
            text = target.get("text", "")
            fallback = target.get("fallback", {})
            try:
                self._d(text=text).click()
                self._log(f"文字点击: '{text}'")
                return DeviceResult.success(
                    detail={"method": "text", "text": text}
                )
            except Exception:
                try:
                    self._d(resourceId=text).click()
                    self._log(f"resourceId点击: {text}")
                    return DeviceResult.success(
                        detail={"method": "resourceId", "text": text}
                    )
                except Exception:
                    if fallback:
                        fx = fallback.get("x", 0)
                        fy = fallback.get("y", 0)
                        try:
                            self._d.click(fx, fy)
                            self._log(f"兜底坐标点击: ({fx}, {fy})")
                            return DeviceResult.success(
                                detail={"method": "fallback", "reason": "文字未找到，使用兜底坐标", "x": fx, "y": fy}
                            )
                        except Exception:
                            pass
                    return DeviceResult.failure(
                        code=ErrorCode.SELECTOR_NOT_FOUND,
                        message=f"未找到元素: {text}",
                        detail={"method": "text", "text": text}
                    )
        
        elif kind == "resource_id":
            resource_id = target.get("resource_id", "")
            try:
                selector = f'resourceId="{resource_id}"'
                self._d(selector).click()
                self._log(f"resourceId点击: {resource_id}")
                return DeviceResult.success(
                    detail={"method": "resourceId", "resource_id": resource_id}
                )
            except Exception as e:
                return DeviceResult.failure(
                    code=ErrorCode.SELECTOR_NOT_FOUND,
                    message=f"未找到元素: {resource_id}",
                    detail={"method": "resourceId", "resource_id": resource_id}
                )
        
        elif kind == "template":
            template_path = target.get("template_path", "")
            fallback = target.get("fallback", {})
            fx = fallback.get("x", 0) if isinstance(fallback, dict) else 0
            fy = fallback.get("y", 0) if isinstance(fallback, dict) else 0
            return self._click_by_template(template_path, fx, fy)
        
        else:
            return DeviceResult.failure(
                code=ErrorCode.CLICK_FAILED,
                message=f"未知的点击目标类型: {kind}"
            )
    
    def _click_by_template(self, template_path: str, 
                            fallback_x: int = 0, fallback_y: int = 0) -> DeviceResult:
        """通过模板匹配点击"""
        try:
            import cv2
            import numpy as np
            
            tpl = cv2.imread(template_path)
            if tpl is None:
                return DeviceResult.failure(
                    code=ErrorCode.TEMPLATE_NOT_FOUND,
                    message=f"模板加载失败: {template_path}",
                    detail={"fallback": True, "x": fallback_x, "y": fallback_y}
                )
            
            # 检查模板特征是否充足
            tpl_gray = cv2.cvtColor(tpl, cv2.COLOR_BGR2GRAY)
            tpl_std = cv2.meanStdDev(tpl_gray)[1][0][0]
            self._log(f"模板特征值: {tpl_std:.1f}")
            
            if tpl_std < 5.0:
                # 特征不足，直接用兜底坐标
                if fallback_x > 0 and fallback_y > 0:
                    self._d.click(fallback_x, fallback_y)
                    self._log(f"模板特征不足，使用兜底坐标: ({fallback_x}, {fallback_y})")
                    return DeviceResult.success(
                        detail={
                            "method": "fallback",
                            "reason": "low_feature",
                            "x": fallback_x,
                            "y": fallback_y,
                        }
                    )
                else:
                    return DeviceResult.failure(
                        code=ErrorCode.TEMPLATE_MATCH_LOW,
                        message=f"模板特征不足且无兜底坐标",
                        detail={"tpl_std": float(tpl_std)}
                    )
            
            # 多次尝试匹配
            best_conf = 0.0
            best_tx, best_ty = fallback_x, fallback_y
            
            for attempt in range(2):
                screen_img = np.array(self._d.screenshot())
                screen_bgr = cv2.cvtColor(screen_img, cv2.COLOR_RGB2BGR)
                
                result = cv2.matchTemplate(screen_bgr, tpl, cv2.TM_CCOEFF_NORMED)
                _, conf, _, max_loc = cv2.minMaxLoc(result)
                
                self._log(f"尝试{attempt+1}/2: 匹配度={conf:.2f}")
                
                if conf > best_conf:
                    best_conf = conf
                    th, tw = tpl.shape[:2]
                    best_tx = max_loc[0] + tw // 2
                    best_ty = max_loc[1] + th // 2
                
                if conf >= 0.75:
                    break
                if attempt < 1:
                    import time as _time
                    _time.sleep(0.15)
            
            self._log(f"最佳匹配度: {best_conf:.2f}")
            
            if best_conf >= 0.60:
                self._d.click(int(best_tx), int(best_ty))
                self._log(f"模板点击: ({int(best_tx)}, {int(best_ty)}) conf={best_conf:.2f}")
                return DeviceResult.success(
                    detail={
                        "method": "template",
                        "template_path": template_path,
                        "confidence": float(best_conf),
                        "x": int(best_tx),
                        "y": int(best_ty),
                    }
                )
            elif fallback_x > 0 and fallback_y > 0:
                self._d.click(fallback_x, fallback_y)
                self._log(f"匹配度过低，使用兜底坐标: ({fallback_x}, {fallback_y})")
                return DeviceResult.success(
                    detail={
                        "method": "fallback",
                        "reason": "low_confidence",
                        "confidence": float(best_conf),
                        "x": fallback_x,
                        "y": fallback_y,
                    }
                )
            else:
                return DeviceResult.failure(
                    code=ErrorCode.TEMPLATE_MATCH_LOW,
                    message=f"匹配度过低: {best_conf:.2f}",
                    detail={"confidence": float(best_conf)}
                )
        except Exception as e:
            if fallback_x > 0 and fallback_y > 0:
                try:
                    self._d.click(fallback_x, fallback_y)
                    return DeviceResult.success(
                        detail={
                            "method": "fallback",
                            "reason": "exception",
                            "error": str(e),
                            "x": fallback_x,
                            "y": fallback_y,
                        }
                    )
                except Exception:
                    pass
            return DeviceResult.failure(
                code=ErrorCode.CLICK_FAILED,
                message=str(e),
                detail={"method": "template", "template_path": template_path}
            )
    
    def _do_swipe(self, action: DeviceAction) -> DeviceResult:
        """执行滑动"""
        target = action.target
        start = target.get("start", (0, 0))
        end = target.get("end", (0, 0))
        duration = action.params.get("duration", 0.5)
        
        try:
            sx, sy = start
            ex, ey = end
            self._d.swipe(sx, sy, ex, ey, duration=duration)
            self._log(f"滑动: ({sx},{sy}) -> ({ex},{ey}) duration={duration:.2f}s")
            return DeviceResult.success(
                detail={
                    "start": (sx, sy),
                    "end": (ex, ey),
                    "duration": duration,
                }
            )
        except Exception as e:
            return DeviceResult.failure(
                code=ErrorCode.SWIPE_FAILED,
                message=str(e),
                detail={"start": start, "end": end, "duration": duration}
            )
    
    def _do_long_press(self, action: DeviceAction) -> DeviceResult:
        """执行长按"""
        target = action.target
        x, y = target.get("x", 0), target.get("y", 0)
        duration = action.params.get("duration", 1.0)
        
        try:
            self._d.long_click(x, y, duration=duration)
            self._log(f"长按: ({x}, {y}) duration={duration:.2f}s")
            return DeviceResult.success(
                detail={"x": x, "y": y, "duration": duration}
            )
        except Exception as e:
            return DeviceResult.failure(
                code=ErrorCode.LONG_PRESS_FAILED,
                message=str(e),
                detail={"x": x, "y": y, "duration": duration}
            )
    
    def _do_input_text(self, action: DeviceAction) -> DeviceResult:
        """执行输入文字"""
        text = action.params.get("text", "")
        
        try:
            self._d.send_keys(text)
            self._log(f"输入文字: '{text}'")
            return DeviceResult.success(
                detail={"text": text}
            )
        except Exception as e:
            return DeviceResult.failure(
                code=ErrorCode.INPUT_FAILED,
                message=str(e),
                detail={"text": text}
            )
    
    def _do_wait(self, action: DeviceAction) -> DeviceResult:
        """等待"""
        seconds = action.params.get("seconds", 1.0)
        time.sleep(seconds)
        return DeviceResult.success(
            detail={"seconds": seconds}
        )
    
    def _do_screenshot(self) -> DeviceResult:
        """截图"""
        state = self.get_state(include_screenshot=True, include_ui=False)
        if state.screenshot:
            return DeviceResult.success(screen_state=state)
        else:
            return DeviceResult.failure(
                code=ErrorCode.SCREENSHOT_FAILED,
                message="截图失败"
            )
    
    def _parse_hierarchy(self, hierarchy: dict) -> list:
        """解析 UI 层级"""
        elements = []
        
        def traverse(node):
            if not isinstance(node, dict):
                return
            
            bounds_str = node.get("@bounds", "[0,0][0,0]")
            try:
                bounds = self._parse_bounds(bounds_str)
            except Exception:
                bounds = (0, 0, 0, 0)
            
            element = ScreenElement(
                text=node.get("@text", ""),
                resource_id=node.get("@resource-id", ""),
                content_desc=node.get("@content-desc", ""),
                class_name=node.get("@class", ""),
                bounds=bounds,
                enabled=node.get("@enabled", "true") == "true",
                selected=node.get("@selected", "false") == "true",
                checked=node.get("@checked", "false") == "true",
            )
            
            if element.text or element.resource_id or element.content_desc:
                elements.append(element)
            
            for child in node.get("children", []):
                traverse(child)
        
        traverse(hierarchy)
        return elements
    
    @staticmethod
    def _parse_bounds(bounds_str: str) -> tuple:
        """解析 bounds 字符串 [x1,y1][x2,y2]"""
        import re
        pattern = r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]'
        match = re.match(pattern, bounds_str)
        if match:
            return tuple(map(int, match.groups()))
        return (0, 0, 0, 0)
    
    def _check_connected(self) -> bool:
        """检查连接状态"""
        if not self._connected or self._d is None:
            self._log("设备未连接")
            return False
        try:
            self._d.info
            return True
        except Exception:
            self._connected = False
            self._d = None
            return False
    
    def _log(self, message: str):
        print(f"[Device] {message}", flush=True)
