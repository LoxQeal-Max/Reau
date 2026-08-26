"""录制自动化插件 - recorder 包入口"""
from .recorder_core import RecorderCore
from .ir.action import Action
from .bus import bus

__all__ = ["RecorderCore", "Action", "bus"]
