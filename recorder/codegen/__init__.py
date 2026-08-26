"""代码生成层入口 - uiautomator2 + 配置驱动"""
from .uia2_codegen import Uia2Codegen

GENS = {"uia2": Uia2Codegen}
__all__ = ["Uia2Codegen", "GENS"]
