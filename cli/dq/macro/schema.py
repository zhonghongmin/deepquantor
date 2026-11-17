"""宏观策略引擎 - 数据结构定义。

对应《量化选股系统·宏观策略文档》v1.0 §1.8 输出契约。
所有对外字段均为中文字符串 / 数值，可直接 JSON 序列化供下游消费。
"""
from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass
class StyleTilt:
    """风格偏好（约束中观行业选择 + 微观选股池）。"""
    size: str
    value_growth: str
    cycle_defensive: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass
class AssetAlloc:
    """大类资产配置（股/债/金/现金），四项之和必须为 1.0。"""
    stock: float
    bond: float
    gold: float
    cash: float

    def total(self) -> float:
        return round(self.stock + self.bond + self.gold + self.cash, 6)

    def to_dict(self) -> dict[str, float]:
        return asdict(self)


@dataclass
class MacroSignal:
    """宏观引擎每次运行产出的结构化信号（§1.8 契约）。"""
    signal_date: str
    regime: str
    money_credit: str
    equity_weight: float
    style_tilt: StyleTilt
    asset_alloc: AssetAlloc
    confidence: str
    next_review: str
    factors: dict[str, int]

    def to_dict(self) -> dict:
        return {
            "signal_date": self.signal_date,
            "regime": self.regime,
            "money_credit": self.money_credit,
            "equity_weight": self.equity_weight,
            "style_tilt": self.style_tilt.to_dict(),
            "asset_alloc": self.asset_alloc.to_dict(),
            "confidence": self.confidence,
            "next_review": self.next_review,
            "factors": self.factors,
        }
