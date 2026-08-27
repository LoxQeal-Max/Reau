"""Uiautomator2 代码生成器：UI 树优先 + 模板匹配 + 坐标兜底

回放策略：
  1. 元素数据配置匹配 → d('resourceId=...').click() 等
  2. uiautomator2 选择器 → d(text="...").click() / d(resourceId="...").click()
  3. 有截图模板 → cv2.matchTemplate 图像匹配定位
  4. 无选择器 → d.click(x, y) 坐标兜底
"""
from __future__ import annotations
import os
from ..ir.action import Action
from .element_data import ELEMENT_REGISTRY


class Uia2Codegen:
    def __init__(self, **_):
        pass

    def emit(self, a: Action) -> str:
        if a.type == "touch":
            return self._gen_touch(a)
        elif a.type == "swipe":
            return self._gen_swipe(a)
        elif a.type == "long_press":
            return self._gen_long_press(a)
        elif a.type == "input_text":
            return self._gen_input_text(a)
        else:
            return f"# 未支持: {a.type}"

    def _gen_touch(self, a: Action) -> str:
        x, y = a.target.get("value", (0, 0))
        uia = a.params.get("uia") or {}
        element_def = a.params.get("element_def")
        template = a.params.get("template", "")

        if element_def:
            return self._gen_by_element_def(element_def, x, y)

        if uia and template:
            selector = self._uia_selector(uia)
            if selector:
                return self._gen_hybrid_click(selector, template, x, y)

        if uia:
            selector = self._uia_selector(uia)
            if selector:
                selector_display = selector.replace('"', '\\"')
                return (
                    f'print("点击: " + "{selector_display}")\n'
                    f'try:\n'
                    f'    d({selector}).click()\n'
                    f'    print("  已点击")\n'
                    f'except Exception as e:\n'
                    f'    print(f"  选择器点击失败: {{e}}，使用坐标: ({x}, {y})")\n'
                    f'    d.click({x}, {y})'
                )

        if template:
            return self._gen_by_template(template, x, y)

        return f'print(f"点击: 坐标 ({x}, {y})")\nd.click({x}, {y})'

    @staticmethod
    def _gen_hybrid_click(selector: str, template_path: str, fallback_x: int, fallback_y: int) -> str:
        safe_path = template_path.replace("\\", "/")
        selector_display = selector.replace('"', '\\"')
        return (
            f'print("点击: " + "{selector_display}" + " + 模板 {safe_path}")\n'
            f'clicked = False\n'
            f'try:\n'
            f'    d({selector}).click()\n'
            f'    print("  选择器点击成功")\n'
            f'    clicked = True\n'
            f'except Exception as e:\n'
            f'    print(f"  选择器点击失败: {{e}}")\n'
            f'if not clicked:\n'
            f'    try:\n'
            f'        tpl = cv2.imread("{safe_path}")\n'
            f'        if tpl is not None:\n'
            f'            # 检查模板特征\n'
            f'            tpl_gray = cv2.cvtColor(tpl, cv2.COLOR_BGR2GRAY)\n'
            f'            tpl_std = cv2.meanStdDev(tpl_gray)[1][0][0]\n'
            f'            if tpl_std < 5.0:\n'
            f'                print("  模板特征不足，使用兜底坐标")\n'
            f'                d.click({fallback_x}, {fallback_y})\n'
            f'                clicked = True\n'
            f'            else:\n'
            f'                th, tw = tpl.shape[:2]\n'
            f'                screen_img = np.array(d.screenshot())\n'
            f'                screen_bgr = cv2.cvtColor(screen_img, cv2.COLOR_RGB2BGR)\n'
            f'                result = cv2.matchTemplate(screen_bgr, tpl, cv2.TM_CCOEFF_NORMED)\n'
            f'                _, conf, _, max_loc = cv2.minMaxLoc(result)\n'
            f'                print(f"  模板匹配度: {{conf:.2f}}")\n'
            f'                if conf >= 0.75:\n'
            f'                    tx, ty = max_loc[0] + tw//2, max_loc[1] + th//2\n'
            f'                    print(f"  模板定位点击: ({{tx}}, {{ty}})")\n'
            f'                    d.click(tx, ty)\n'
            f'                    clicked = True\n'
            f'    except Exception as e:\n'
            f'        print(f"  模板匹配异常: {{e}}")\n'
            f'if not clicked:\n'
            f'    print(f"  使用兜底坐标: ({fallback_x}, {fallback_y})")\n'
            f'    d.click({fallback_x}, {fallback_y})'
        )

    def _gen_swipe(self, a: Action) -> str:
        value = a.target.get("value", (0, 0, 0, 0))
        if len(value) == 4:
            sx, sy, ex, ey = value
        else:
            sx, sy, ex, ey = value[0], value[1], value[2], value[3]
        duration = a.params.get("duration", 0.5)
        direction = a.params.get("direction", "")
        
        import math
        dx = ex - sx
        dy = ey - sy
        distance = math.sqrt(dx * dx + dy * dy)
        speed = distance / duration if duration > 0 else distance
        
        if duration < 0.3:
            return self._gen_fast_swipe(sx, sy, ex, ey, duration, direction, distance)
        elif duration < 0.6:
            return self._gen_medium_swipe(sx, sy, ex, ey, duration, direction, distance)
        else:
            return (
                f'# 滑动 ({direction}) 耗时 {duration:.2f}s\n'
                f'd.swipe({sx}, {sy}, {ex}, {ey}, duration={duration:.2f})'
            )

    def _gen_long_press(self, a: Action) -> str:
        x, y = a.target.get("value", (0, 0))
        duration = a.params.get("duration", 1.0)
        uia = a.params.get("uia") or {}
        template = a.params.get("template", "")

        if template:
            safe_path = template.replace("\\", "/")
            return (
                f'print("长按: 模板 {safe_path}")\n'
                f'try:\n'
                f'    tpl = cv2.imread("{safe_path}")\n'
                f'    if tpl is not None:\n'
                f'        # 检查模板特征\n'
                f'        tpl_gray = cv2.cvtColor(tpl, cv2.COLOR_BGR2GRAY)\n'
                f'        tpl_std = cv2.meanStdDev(tpl_gray)[1][0][0]\n'
                f'        if tpl_std < 5.0:\n'
                f'            print("  模板特征不足，使用兜底坐标")\n'
                f'            d.long_click({x}, {y}, duration={duration:.2f})\n'
                f'        else:\n'
                f'            th, tw = tpl.shape[:2]\n'
                f'            screen_img = np.array(d.screenshot())\n'
                f'            screen_bgr = cv2.cvtColor(screen_img, cv2.COLOR_RGB2BGR)\n'
                f'            result = cv2.matchTemplate(screen_bgr, tpl, cv2.TM_CCOEFF_NORMED)\n'
                f'            _, conf, _, max_loc = cv2.minMaxLoc(result)\n'
                f'            if conf >= 0.60:\n'
                f'                tx, ty = max_loc[0] + tw//2, max_loc[1] + th//2\n'
                f'                print(f"  模板定位长按: ({{tx}}, {{ty}}) conf={{conf:.2f}}")\n'
                f'                d.long_click(tx, ty, duration={duration:.2f})\n'
                f'            else:\n'
                f'                print(f"  匹配度过低({{conf:.2f}})，使用兜底坐标")\n'
                f'                d.long_click({x}, {y}, duration={duration:.2f})\n'
                f'    else:\n'
                f'        d.long_click({x}, {y}, duration={duration:.2f})\n'
                f'except Exception as e:\n'
                f'    print(f"  异常: {{e}}，使用兜底坐标")\n'
                f'    d.long_click({x}, {y}, duration={duration:.2f})'
            )

        if uia:
            selector = self._uia_selector(uia)
            if selector:
                selector_display = selector.replace('"', '\\"')
                return (
                    f'print("长按: " + "{selector_display}")\n'
                    f'try:\n'
                    f'    d({selector}).long_click(duration={duration:.2f})\n'
                    f'    print("  已长按")\n'
                    f'except Exception as e:\n'
                    f'    print(f"  选择器长按失败: {{e}}，使用坐标: ({x}, {y})")\n'
                    f'    d.long_click({x}, {y}, duration={duration:.2f})'
                )

        return (
            f'print(f"长按: 坐标 ({x}, {y}) 时长={duration:.2f}s")\n'
            f'd.long_click({x}, {y}, duration={duration:.2f})'
        )

    def _gen_input_text(self, a: Action) -> str:
        text = a.params.get("text", "")
        safe_text = text.replace('"', '\\"')
        return (
            f'print("输入文字: {safe_text}")\n'
            f'd.send_keys("{safe_text}")'
        )

    @staticmethod
    def _gen_fast_swipe(sx: int, sy: int, ex: int, ey: int, duration: float, direction: str, distance: float) -> str:
        steps = max(2, min(4, int(distance / 200)))
        lines = [
            f'# 快速滑动 ({direction}) 距离={distance:.0f}px 耗时={duration:.2f}s',
            f'# 分段加速滑动: {steps}段',
            f'start_x, start_y = {sx}, {sy}',
        ]
        for i in range(1, steps + 1):
            t = i / steps
            frac = t * t
            step_x = sx + (ex - sx) * frac
            step_y = sy + (ey - sy) * frac
            step_dur = duration / steps * 0.4
            lines.append(f'end_x, end_y = {step_x:.0f}, {step_y:.0f}')
            lines.append(f'd.swipe(start_x, start_y, end_x, end_y, duration={step_dur:.3f})')
            if i < steps:
                lines.append(f'start_x, start_y = end_x, end_y')
                lines.append(f'_sleep(0.02)')
        return '\n'.join(lines)

    @staticmethod
    def _gen_medium_swipe(sx: int, sy: int, ex: int, ey: int, duration: float, direction: str, distance: float) -> str:
        steps = max(3, min(5, int(distance / 250)))
        lines = [
            f'# 中速滑动 ({direction}) 距离={distance:.0f}px 耗时={duration:.2f}s',
            f'# 分段加速滑动: {steps}段 (先慢后快)',
            f'start_x, start_y = {sx}, {sy}',
        ]
        for i in range(1, steps + 1):
            t = i / steps
            frac = t * t
            step_x = sx + (ex - sx) * frac
            step_y = sy + (ey - sy) * frac
            step_dur = duration / steps
            lines.append(f'end_x, end_y = {step_x:.0f}, {step_y:.0f}')
            lines.append(f'd.swipe(start_x, start_y, end_x, end_y, duration={step_dur:.3f})')
            if i < steps:
                lines.append(f'start_x, start_y = end_x, end_y')
                lines.append(f'_sleep(0.03)')
        return '\n'.join(lines)

    @staticmethod
    def _gen_by_template(template_path: str, fallback_x: int, fallback_y: int) -> str:
        safe_path = template_path.replace("\\", "/")
        return (
            f'print(f"点击: 模板 {safe_path}")\n'
            f'try:\n'
            f'    tpl = cv2.imread("{safe_path}")\n'
            f'    if tpl is None:\n'
            f'        print("  模板加载失败，使用兜底坐标")\n'
            f'        d.click({fallback_x}, {fallback_y})\n'
            f'    else:\n'
            f'        # 检查模板特征是否充足\n'
            f'        tpl_gray = cv2.cvtColor(tpl, cv2.COLOR_BGR2GRAY)\n'
            f'        tpl_std = cv2.meanStdDev(tpl_gray)[1][0][0]\n'
            f'        print(f"  模板特征值: {tpl_std:.1f}")\n'
            f'        if tpl_std < 5.0:\n'
            f'            print("  模板特征不足（纯色区域），直接使用兜底坐标")\n'
            f'            d.click({fallback_x}, {fallback_y})\n'
            f'        else:\n'
            f'            th, tw = tpl.shape[:2]\n'
            f'            best_conf = 0.0\n'
            f'            best_tx, best_ty = {fallback_x}, {fallback_y}\n'
            f'            for attempt in range(2):\n'
            f'                screen_img = np.array(d.screenshot())\n'
            f'                screen_bgr = cv2.cvtColor(screen_img, cv2.COLOR_RGB2BGR)\n'
            f'                result = cv2.matchTemplate(screen_bgr, tpl, cv2.TM_CCOEFF_NORMED)\n'
            f'                _, conf, _, max_loc = cv2.minMaxLoc(result)\n'
            f'                tx = max_loc[0] + tw // 2\n'
            f'                ty = max_loc[1] + th // 2\n'
            f'                print(f"  尝试{{attempt+1}}/2: 匹配度={{conf:.2f}}")\n'
            f'                if conf > best_conf:\n'
            f'                    best_conf = conf\n'
            f'                    best_tx, best_ty = tx, ty\n'
            f'                if conf >= 0.75:\n'
            f'                    break\n'
            f'                if attempt < 1:\n'
            f'                    _sleep(0.15)\n'
            f'            print(f"  最佳匹配度: {{best_conf:.2f}}")\n'
            f'            if best_conf >= 0.75:\n'
            f'                print(f"  模板定位点击: ({{best_tx}}, {{best_ty}})")\n'
            f'                d.click(best_tx, best_ty)\n'
            f'            elif best_conf >= 0.60:\n'
            f'                print(f"  可接受匹配度，尝试点击: ({{best_tx}}, {{best_ty}})")\n'
            f'                d.click(best_tx, best_ty)\n'
            f'            else:\n'
            f'                print(f"  匹配度过低，使用兜底坐标: ({fallback_x}, {fallback_y})")\n'
            f'                d.click({fallback_x}, {fallback_y})\n'
            f'except Exception as e:\n'
            f'    print(f"  异常: {{e}}，使用兜底坐标: ({fallback_x}, {fallback_y})")\n'
            f'    d.click({fallback_x}, {fallback_y})'
        )

    def emit_to_script(self, actions: list[Action], output_path: str):
        has_template = any(
            a.params.get("template")
            for a in actions
        )
        lines = [
            '# -*- encoding=utf8 -*-',
            '"""Auto-generated by 录制自动化插件 (uiautomator2)"""',
            'import uiautomator2 as u2',
            'import time',
        ]
        if has_template:
            lines.extend([
                'import cv2',
                'import numpy as np',
                '',
                'cv2.setLogLevel(3)',
            ])
        lines.extend([
            '',
            'd = u2.connect()',
            '',
            'def run():',
        ])
        for i, a in enumerate(actions):
            code = self.emit(a)
            for line in code.split('\n'):
                lines.append(f'    {line}')
            if i < len(actions) - 1:
                lines.append('    time.sleep(1)')
            lines.append('')
        lines.append('')
        lines.append('if __name__ == "__main__":')
        lines.append('    run()')

        os.makedirs(os.path.dirname(output_path) or '.', exist_ok=True)
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines))

    @staticmethod
    def _gen_by_element_def(element_name: str, x: int, y: int) -> str:
        elem = ELEMENT_REGISTRY.get(element_name)
        if not elem:
            return f'd.click({x}, {y})'

        selectors = []
        if elem.resourceId:
            selectors.append(f'resourceId="{elem.resourceId}"')
        if elem.text:
            selectors.append(f'text="{elem.text}"')
        if elem.contentDesc:
            selectors.append(f'description="{elem.contentDesc}"')
        if elem.className:
            selectors.append(f'className="{elem.className}"')
        if elem.xpath:
            selectors.append(f'xpath="{elem.xpath}"')

        if not selectors:
            return f'd.click({x}, {y})'

        selector = selectors[0]
        return (
            f'try:\n'
            f'    d({selector}).click()\n'
            f'except:\n'
            f'    d.click({x}, {y})'
        )

    _GENERIC_CLASSES = {
        "android.widget.FrameLayout",
        "android.widget.LinearLayout",
        "android.widget.RelativeLayout",
        "android.widget.ConstraintLayout",
        "androidx.constraintlayout.widget.ConstraintLayout",
        "android.view.View",
        "android.view.ViewGroup",
        "android.widget.TextView",
        "android.widget.ImageView",
        "android.widget.Button",
    }

    @staticmethod
    def _uia_selector(attrs: dict) -> str:
        if attrs.get("resourceId"):
            rid = attrs["resourceId"]
            if ":" not in rid:
                rid = rid.split(":id/")[-1] if ":id/" in rid else rid
            return f'resourceId="{rid}"'
        if attrs.get("text"):
            return f'text="{attrs["text"]}"'
        if attrs.get("contentDesc"):
            return f'description="{attrs["contentDesc"]}"'
        cls_name = attrs.get("className", "")
        if cls_name and cls_name not in Uia2Codegen._GENERIC_CLASSES:
            return f'className="{cls_name}"'
        return ""
