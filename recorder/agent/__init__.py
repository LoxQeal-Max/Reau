"""Agent 模块 - AI Agent 与设备交互的标准接口

子模块:
- models: 数据模型 (DeviceAction, DeviceResult, ScreenState)
- device_interface: 设备接口实现
- verifier: 操作结果验证器
- llm_client: LLM 客户端（支持钉钉、企业内部 AI）
- ai_agent: AI Agent 核心逻辑
"""

from .models import (
    ActionType,
    DeviceAction,
    DeviceResult,
    ErrorCode,
    ScreenElement,
    ScreenState,
)

from .device_interface import DeviceInterface
from .verifier import ActionVerifier
from .llm_client import LLMClient, create_llm_client
from .ai_agent import AIAgent

__all__ = [
    "ActionType",
    "DeviceAction",
    "DeviceResult",
    "ErrorCode",
    "ScreenElement",
    "ScreenState",
    "DeviceInterface",
    "ActionVerifier",
    "LLMClient",
    "create_llm_client",
    "AIAgent",
]
