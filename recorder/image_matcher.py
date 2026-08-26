"""图像匹配模块 - 基于 OpenCV 模板定位

用于回放时通过截图模板找到元素位置，替代纯坐标点击。
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

import cv2
import numpy as np


@dataclass
class MatchResult:
    x: int
    y: int
    confidence: float
    width: int
    height: int

    @property
    def success(self) -> bool:
        return self.confidence >= 0.6


class ImageMatcher:
    """基于 OpenCV 的模板匹配器"""

    def __init__(self, threshold: float = 0.6):
        self.threshold = threshold

    def match(self, screen_img: np.ndarray, template_path: str) -> Optional[MatchResult]:
        """在全屏截图中查找模板位置

        Args:
            screen_img: 全屏截图 (BGR numpy array)
            template_path: 模板图片路径

        Returns:
            MatchResult 或 None
        """
        if not os.path.exists(template_path):
            return None

        template = cv2.imread(template_path, cv2.IMREAD_COLOR)
        if template is None:
            return None

        th, tw = template.shape[:2]
        sh, sw = screen_img.shape[:2]

        if th > sh or tw > sw:
            return None

        result = cv2.matchTemplate(screen_img, template, cv2.TM_CCOEFF_NORMED)
        _, confidence, _, max_loc = cv2.minMaxLoc(result)

        if confidence < self.threshold:
            return MatchResult(
                x=max_loc[0] + tw // 2,
                y=max_loc[1] + th // 2,
                confidence=confidence,
                width=tw,
                height=th,
            )

        center_x = max_loc[0] + tw // 2
        center_y = max_loc[1] + th // 2

        return MatchResult(
            x=center_x,
            y=center_y,
            confidence=confidence,
            width=tw,
            height=th,
        )

    def match_multi(self, screen_img: np.ndarray, template_path: str,
                    threshold: float = 0.6, max_count: int = 5) -> list[MatchResult]:
        """查找多个匹配位置（非极大值抑制）"""
        if not os.path.exists(template_path):
            return []

        template = cv2.imread(template_path, cv2.IMREAD_COLOR)
        if template is None:
            return []

        th, tw = template.shape[:2]
        result = cv2.matchTemplate(screen_img, template, cv2.TM_CCOEFF_NORMED)
        locations = np.where(result >= threshold)
        points = list(zip(*locations[::-1]))

        results: list[MatchResult] = []
        for pt in points[:max_count]:
            results.append(MatchResult(
                x=pt[0] + tw // 2,
                y=pt[1] + th // 2,
                confidence=float(result[pt[1], pt[0]]),
                width=tw,
                height=th,
            ))

        return results


def load_image(file_path: str) -> Optional[np.ndarray]:
    """加载图片为 BGR numpy array"""
    if not os.path.exists(file_path):
        return None
    return cv2.imread(file_path, cv2.IMREAD_COLOR)


def load_image_from_bytes(data: bytes) -> Optional[np.ndarray]:
    """从 bytes 加载图片"""
    nparr = np.frombuffer(data, np.uint8)
    return cv2.imdecode(nparr, cv2.IMREAD_COLOR)
