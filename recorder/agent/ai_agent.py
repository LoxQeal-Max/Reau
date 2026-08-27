"""AI Agent - 使用视觉 LLM 进行任务规划和执行"""
from __future__ import annotations
import json
import time
from typing import Optional

from .llm_client import LLMClient
from .device_interface import DeviceInterface
from .models import DeviceAction, ScreenState

SYSTEM_PROMPT = """你是一个 Android 自动化测试 Agent。每一步你都会收到当前手机屏幕的截图和 UI 元素列表。

你的任务：根据截图内容判断当前界面状态，决定下一步操作。

可用操作（以 JSON 格式输出）：
1. 点击：{"type": "click", "target": {"kind": "text", "text": "按钮文字"}}
   或坐标点击：{"type": "click", "target": {"kind": "coord", "x": 500, "y": 800}}
2. 滑动：{"type": "swipe", "target": {"x1": 500, "y1": 1000, "x2": 500, "y2": 500, "duration": 300}}
3. 长按：{"type": "long_press", "target": {"kind": "coord", "x": 500, "y": 800}, "params": {"duration": 1.0}}
4. 输入：{"type": "input_text", "target": {"kind": "text", "text": "输入框文字"}, "params": {"text": "要输入的内容"}}
5. 完成：{"type": "complete", "task_completed": true}

决策优先级：
1. 先看截图理解界面，结合下方 UI 元素列表精确定位
2. 优先使用文字定位（kind: text），坐标为兜底
3. 遇到弹窗先关闭
4. 操作之间等待 0.3-1.0 秒
5. 如果任务已完成，返回 {"type": "complete", "task_completed": true}

重要：只输出 JSON，不要输出其他文字。如果无法确定操作，返回 {"type": "complete", "task_completed": true}。"""


class AIAgent:
    """AI Agent - 使用视觉 LLM 执行自动化任务"""

    def __init__(self, llm_client: LLMClient, device: DeviceInterface):
        self.llm = llm_client
        self.device = device
        self.conversation_history: list = []

    def execute_task(self, task: str, max_steps: int = 20) -> dict:
        """执行任务"""
        self.conversation_history = []

        results = []
        current_step = 0
        task_completed = False

        self.conversation_history.append({
            "role": "user",
            "content": f"请完成以下任务：{task}"
        })

        while not task_completed and current_step < max_steps:
            current_step += 1

            state = self.device.get_state()
            state_desc = self._describe_state(state)
            screenshot_data = state.screenshot

            self.conversation_history.append({
                "role": "user",
                "content": f"当前屏幕状态：\n{state_desc}\n\n请决定下一步操作。"
            })

            llm_response = self.llm.chat_with_image(
                messages=self.conversation_history,
                image_data=screenshot_data,
                system_prompt=SYSTEM_PROMPT
            )

            # 释放截图内存
            del screenshot_data
            state.screenshot = None

            if not llm_response:
                fallback_result = self._fallback_action(state)
                if fallback_result:
                    results.append(f"步骤 {current_step} (规则): {fallback_result}")
                    self.conversation_history.append({
                        "role": "assistant",
                        "content": f"[规则匹配] {fallback_result}"
                    })
                else:
                    results.append(f"步骤 {current_step}: LLM 不可用，任务失败")
                    break
            else:
                action_data = self._parse_llm_response(llm_response)

                self.conversation_history.append({
                    "role": "assistant",
                    "content": llm_response
                })

                if action_data:
                    if action_data.get("task_completed"):
                        task_completed = True
                        results.append("✅ 任务完成！")
                        break

                    result = self._execute_action(action_data)
                    results.append(f"步骤 {current_step}: {result}")
                else:
                    if "完成" in llm_response or "done" in llm_response.lower():
                        task_completed = True
                        results.append("✅ AI 判断任务已完成")
                    else:
                        results.append(f"步骤 {current_step}: 无法解析 AI 响应")

            if len(self.conversation_history) > 12:
                self.conversation_history = self.conversation_history[-12:]

        return {
            "task": task,
            "completed": task_completed,
            "steps": current_step,
            "results": results,
        }

    def _describe_state(self, state: ScreenState) -> str:
        """描述当前屏幕状态（文本辅助信息）"""
        description = []
        description.append(f"屏幕分辨率: {state.device_width}x{state.device_height}")
        description.append(f"当前页面: {state.page_name or '未知'}")
        description.append(f"UI 元素数量: {len(state.ui_elements)}")
        description.append("")

        key_elements = []
        for elem in state.ui_elements[:30]:
            text = elem.text or ""
            res_id = elem.resource_id or ""
            bounds = elem.bounds or (0, 0, 0, 0)

            if text or res_id:
                key_elements.append({
                    "text": text,
                    "resource_id": res_id,
                    "bounds": list(bounds),
                })

        if key_elements:
            description.append("可交互元素（用于精确定位）:")
            for i, elem in enumerate(key_elements, 1):
                desc = f"  {i}. "
                if elem["text"]:
                    desc += f"文字='{elem['text']}' "
                if elem["resource_id"]:
                    desc += f"ID='{elem['resource_id']}' "
                desc += f"位置={elem['bounds']}"
                description.append(desc)
        else:
            description.append("当前无可交互元素")

        description.append("")
        description.append("请结合截图和上述元素列表，输出下一步操作的 JSON。")

        return "\n".join(description)

    def _parse_llm_response(self, response: str) -> Optional[dict]:
        """解析 LLM 响应为操作"""
        try:
            json_start = response.find("{")
            json_end = response.rfind("}") + 1

            if json_start >= 0 and json_end > json_start:
                json_str = response[json_start:json_end]
                action_data = json.loads(json_str)
                return action_data
        except json.JSONDecodeError:
            pass

        action = {
            "type": "",
            "target": {},
            "task_completed": False,
        }

        response_lower = response.lower()

        if any(word in response for word in ["完成", "已完成", "不需要", "无需"]):
            action["task_completed"] = True
            return action

        if "点击" in response or "click" in response_lower:
            action["type"] = "click"
        elif "滑动" in response or "swipe" in response_lower:
            action["type"] = "swipe"
        elif "长按" in response or "long_press" in response_lower:
            action["type"] = "long_press"
        elif "输入" in response or "input" in response_lower or "type" in response_lower:
            action["type"] = "input_text"
        else:
            return None

        if "文字" in response or "text" in response_lower:
            import re
            for pattern in ["'[^']*'", '"[^"]*"']:
                matches = re.findall(pattern, response)
                if matches:
                    action["target"] = {
                        "kind": "text",
                        "text": matches[0].strip("'\"")
                    }
                    break

        if not action["target"]:
            action["target"] = {"kind": "text", "text": response[:20]}

        return action

    def _execute_action(self, action_data: dict) -> str:
        """执行解析后的操作"""
        action_type = action_data.get("type", "")
        target = action_data.get("target", {})
        params = action_data.get("params", {})

        try:
            if action_type == "click":
                kind = target.get("kind", "text")
                if kind == "coord":
                    x = target.get("x", 0)
                    y = target.get("y", 0)
                    device_action = DeviceAction.click_by_coord(x, y)
                    action_desc = f"坐标点击 ({x}, {y})"
                elif kind == "text":
                    text = target.get("text", "")
                    fallback_x = target.get("x", 0)
                    fallback_y = target.get("y", 0)
                    device_action = DeviceAction.click_by_text(
                        text=text,
                        fallback_x=fallback_x,
                        fallback_y=fallback_y
                    )
                    action_desc = f"文字点击 '{text}'"
                elif kind == "resource_id":
                    res_id = target.get("resource_id", "")
                    device_action = DeviceAction.click_by_resource_id(res_id)
                    action_desc = f"ID点击 '{res_id}'"
                else:
                    device_action = DeviceAction.click_by_coord(
                        target.get("x", 0), target.get("y", 0)
                    )
                    action_desc = f"点击 {target}"
                result = self.device.execute(device_action)

            elif action_type == "swipe":
                device_action = DeviceAction.swipe(
                    sx=target.get("x1", 0),
                    sy=target.get("y1", 0),
                    ex=target.get("x2", 0),
                    ey=target.get("y2", 0),
                    duration=params.get("duration", 0.3)
                )
                result = self.device.execute(device_action)
                action_desc = f"滑动 ({target.get('x1')},{target.get('y1')}) → ({target.get('x2')},{target.get('y2')})"

            elif action_type == "long_press":
                kind = target.get("kind", "coord")
                if kind == "coord":
                    device_action = DeviceAction.long_press(
                        x=target.get("x", 0),
                        y=target.get("y", 0),
                        duration=params.get("duration", 1.0)
                    )
                else:
                    device_action = DeviceAction.long_press(
                        x=target.get("x", 0),
                        y=target.get("y", 0),
                        duration=params.get("duration", 1.0)
                    )
                result = self.device.execute(device_action)
                action_desc = f"长按 ({target.get('x', 0)},{target.get('y', 0)})"

            elif action_type == "input_text":
                device_action = DeviceAction.input_text(
                    text=params.get("text", "")
                )
                result = self.device.execute(device_action)
                action_desc = f"输入文字 '{params.get('text')}'"

            elif action_type == "complete":
                return "✅ AI 判断任务完成"

            else:
                return f"未知操作类型: {action_type}"

            status = "✅" if result.success else "❌"
            detail = result.detail
            if isinstance(detail, dict):
                method = detail.get("method", "")
                if method == "template":
                    conf = detail.get("confidence", 0)
                    return f"{status} {action_desc} (模板匹配度={conf:.2f})"
                elif method == "fallback":
                    reason = detail.get("reason", "")
                    return f"{status} {action_desc} (兜底: {reason})"

            return f"{status} {action_desc}"

        except Exception as e:
            return f"❌ 执行失败: {str(e)}"

    def _fallback_action(self, state: ScreenState) -> Optional[str]:
        """规则匹配后备方案"""
        target_texts = ["确定", "开始", "领取", "战斗", "进入", "确认", "知道了", "关闭", "同意", "下一步"]

        for text in target_texts:
            elem = state.get_element_by_text(text)
            if elem:
                x1, y1, x2, y2 = elem.bounds
                cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
                action = DeviceAction.click_by_coord(cx, cy)
                result = self.device.execute(action)
                return f"点击 '{text}': {'成功' if result.success else '失败'}"

        return None
