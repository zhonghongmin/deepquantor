"""MC-04 风格偏好与大类资产配置（《数据策略总文档》§1.5 / §1.6）。

- style_tilt 由象限映射决定，不参与仓位微调（§1.17 ③）。
- asset_alloc：stock = equity_weight；其余四项按基准行等比缩放
  ratio = (100 − w_eff) / (100 − center_stock)，保持五项和 = 1、commodity 恒 0.0。
- 校验断言：五项和 ≠ 1、缺 commodity、commodity ≠ 0 → 抛错。
"""
from __future__ import annotations

from . import config as C


def map_style_tilt(regime: str) -> dict[str, str]:
    """象限 → 三维风格偏好（§1.5 表，枚举收敛到 §1.7 契约）。"""
    return dict(C.STYLE_TILT[regime])


def build_asset_alloc(regime: str, mc: str, equity_weight: float) -> dict[str, float]:
    """基准行 + 等比缩放 → 五项占比（小数，和 = 1.0，stock == equity_weight）。"""
    try:
        row = C.ASSET_ALLOC_BASE[(regime, mc)]
        center_stock = C.EQUITY_CENTER[(regime, mc)]
    except KeyError as e:
        raise KeyError(f"36 行基准配置查表越界：{e}") from e
    w_pct = equity_weight * 100.0
    denom = 100.0 - center_stock
    ratio = (100.0 - w_pct) / denom if denom > 0 else 0.0

    alloc = {
        "stock": round(equity_weight, 6),
        "bond": round(row["bond"] / 100.0 * ratio, 6),
        "commodity": round(row["commodity"] / 100.0 * ratio, 6),  # 本期恒 0.0
        "gold": round(row["gold"] / 100.0 * ratio, 6),
        "cash": round(row["cash"] / 100.0 * ratio, 6),
    }
    validate_asset_alloc(alloc, equity_weight)
    return alloc


def validate_asset_alloc(alloc: dict, equity_weight: float) -> None:
    """§1.6 ③ 校验断言：五项 ≥0、合计 = 1、含 commodity=0、stock == equity_weight。"""
    required = {"stock", "bond", "commodity", "gold", "cash"}
    if set(alloc) != required:
        raise ValueError(f"asset_alloc 字段缺失/多余：{set(alloc) ^ required}")
    if alloc["commodity"] != 0.0:
        raise ValueError("本期 commodity 必须为 0.0（结构性占位，D-17）")
    if any(v < 0 for v in alloc.values()):
        raise ValueError("asset_alloc 不得出现负值")
    total = round(sum(alloc.values()), 6)
    if abs(total - 1.0) > 1e-6:
        raise ValueError(f"五项合计 ≠ 1.0：{total}")
    if abs(alloc["stock"] - equity_weight) > 1e-6:
        raise ValueError("stock 必须等于 equity_weight")
