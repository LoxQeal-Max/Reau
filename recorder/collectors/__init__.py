"""采集层入口 - Android (uiautomator2)"""
from .base import BaseCollector
from .android_uia import AndroidUiaCollector

COLLECTORS = {"android": AndroidUiaCollector}
__all__ = ["BaseCollector", "COLLECTORS"]
