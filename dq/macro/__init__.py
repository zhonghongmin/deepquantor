"""宏观策略引擎包（dq.macro）。

口径源：《数据策略总文档》§1；Spec：《量化选股系统·宏观主线与展示页开发Spec》§3/§4。
"""
from .engine import MacroInput, run_macro
from .schema import MacroSignal, load_schema

__all__ = ["MacroInput", "MacroSignal", "run_macro", "load_schema"]
