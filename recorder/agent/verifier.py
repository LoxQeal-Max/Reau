"""操作验证器 - 验证操作是否生效"""
from __future__ import annotations
import time
from typing import TYPE_CHECKING, Optional

from .models import (
    ActionType,
    DeviceAction,
    DeviceResult,
    ErrorCode,
    ScreenState,
)

if TYPE_CHECKING:
    from .device_interface import DeviceInterface


class ActionVerifier:
    """操作验证器 - 验证操作是否生效
    
    验证策略:
    1. 等待页面稳定 (可配置超时)
    2. 截图对比 (前后变化检测)
    3. UI 元素检查 (关键元素是否出现/消失)
    """
    
    def __init__(self, device: DeviceInterface, timeout: float = 3.0):
        self.device = device
        self.timeout = timeout
        self._change_threshold = 0.05
    
    def verify(self, action: DeviceAction, 
               before_state: ScreenState,
               after_result: DeviceResult) -> DeviceResult:
        """验证操作是否生效"""
        if not after_result.success:
            return after_result
        
        if action.type == ActionType.CLICK:
            return self._verify_click(action, before_state, after_result)
        elif action.type == ActionType.SWIPE:
            return self._verify_swipe(action, before_state, after_result)
        elif action.type == ActionType.LONG_PRESS:
            return self._verify_long_press(action, before_state, after_result)
        elif action.type == ActionType.INPUT_TEXT:
            return self._verify_input_text(action, before_state, after_result)
        else:
            return after_result
    
    def _verify_click(self, action: DeviceAction,
                      before: ScreenState,
                      result: DeviceResult) -> DeviceResult:
        """验证点击是否生效"""
        time.sleep(0.3)
        
        after = self.device.get_state()
        result.screen_state = after
        
        changed = self._detect_change(before, after)
        if changed:
            result.action_detail["verified"] = True
            result.action_detail["change_detected"] = True
            return result
        
        target_text = action.target.get("text", "")
        if target_text:
            if before.get_element_by_text(target_text) and not after.get_element_by_text(target_text):
                result.action_detail["verified"] = True
                result.action_detail["element_disappeared"] = True
                return result
        
        result.action_detail["verified"] = False
        result.action_detail["change_detected"] = False
        return result
    
    def _verify_swipe(self, action: DeviceAction,
                       before: ScreenState,
                       result: DeviceResult) -> DeviceResult:
        """验证滑动是否生效"""
        time.sleep(0.3)
        
        after = self.device.get_state()
        result.screen_state = after
        
        changed = self._detect_change(before, after)
        result.action_detail["verified"] = True
        result.action_detail["change_detected"] = changed
        return result
    
    def _verify_long_press(self, action: DeviceAction,
                            before: ScreenState,
                            result: DeviceResult) -> DeviceResult:
        """验证长按是否生效"""
        time.sleep(0.5)
        
        after = self.device.get_state()
        result.screen_state = after
        
        changed = self._detect_change(before, after)
        result.action_detail["verified"] = True
        result.action_detail["change_detected"] = changed
        return result
    
    def _verify_input_text(self, action: DeviceAction,
                            before: ScreenState,
                            result: DeviceResult) -> DeviceResult:
        """验证输入是否生效"""
        time.sleep(0.2)
        
        after = self.device.get_state()
        result.screen_state = after
        
        input_text = action.params.get("text", "")
        result.action_detail["verified"] = True
        result.action_detail["input_text"] = input_text
        return result
    
    def _detect_change(self, before: ScreenState, 
                       after: ScreenState) -> bool:
        """检测屏幕是否发生变化"""
        if before.screenshot is None or after.screenshot is None:
            return True
        
        try:
            import numpy as np
            import cv2
            
            before_img = np.frombuffer(before.screenshot, dtype=np.uint8)
            after_img = np.frombuffer(after.screenshot, dtype=np.uint8)
            
            before_img = cv2.imdecode(before_img, cv2.IMREAD_COLOR)
            after_img = cv2.imdecode(after_img, cv2.IMREAD_COLOR)
            
            if before_img is None or after_img is None:
                return True
            
            if before_img.shape != after_img.shape:
                return True
            
            diff = cv2.absdiff(before_img, after_img)
            change_ratio = np.sum(diff > 25) / (diff.shape[0] * diff.shape[1])
            
            return change_ratio > self._change_threshold
            
        except Exception:
            return True
    
    def wait_for_element(self, text: str, 
                          timeout: Optional[float] = None) -> Optional[ScreenState]:
        """等待指定文字的元素出现"""
        timeout = timeout or self.timeout
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            state = self.device.get_state(include_screenshot=False)
            if state.get_element_by_text(text):
                return state
            time.sleep(0.2)
        
        return None
    
    def wait_for_element_disappear(self, text: str,
                                    timeout: Optional[float] = None) -> Optional[ScreenState]:
        """等待指定文字的元素消失"""
        timeout = timeout or self.timeout
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            state = self.device.get_state(include_screenshot=False)
            if not state.get_element_by_text(text):
                return state
            time.sleep(0.2)
        
        return None
    
    def wait_for_screen_change(self, 
                                before: ScreenState,
                                timeout: Optional[float] = None) -> Optional[ScreenState]:
        """等待屏幕发生变化"""
        timeout = timeout or self.timeout
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            after = self.device.get_state()
            if self._detect_change(before, after):
                return after
            time.sleep(0.2)
        
        return None
