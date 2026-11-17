"""宏观策略引擎包。"""
from .engine import (
    classify_credit,
    classify_external,
    classify_growth,
    classify_inflation,
    classify_money,
    classify_rate,
    locate_money_credit,
    locate_regime,
    map_asset_alloc,
    map_equity_weight,
    map_style_tilt,
    run_macro,
)
from .schema import AssetAlloc, MacroSignal, StyleTilt

__all__ = [
    "classify_growth", "classify_inflation", "classify_money",
    "classify_credit", "classify_rate", "classify_external",
    "locate_regime", "locate_money_credit",
    "map_equity_weight", "map_style_tilt", "map_asset_alloc",
    "run_macro", "MacroInput",
    "MacroSignal", "StyleTilt", "AssetAlloc",
]
