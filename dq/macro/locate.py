"""MC-02 / MC-09 状态定位（《数据策略总文档》§1.4）。

- MC-02：货币 × 信用九态二维定位（领先层）；增长 × 通胀四象限定位（确认层，归并规则）。
- MC-09：36 格查表（4 象限 × 9 货币信用态），命中即整行执行、不折减、不跨行组合。
- 范畴隔离：money_credit 九宫格只渲染流动性状态；regime 与 money_credit 互不推导。
- D-24 同月校验：两层六处 period 全等才允许出 36 格。
"""
from __future__ import annotations

from . import config as C


class PeriodMismatch(ValueError):
    """D-24：两层观测 period 不一致，拒绝出 36 格，只走方向模式。"""


def locate_money_credit(money: int, credit: int) -> str:
    """货币 × 信用 → 九态名（MC-02）。任一维取 0 即落到对应九态名，不沿用上期。"""
    if money not in (-1, 0, 1) or credit not in (-1, 0, 1):
        raise ValueError("money/credit ∈ {-1,0,1}")
    return C.MC_STATES[(money, credit)]


def locate_regime(growth: int, inflation: int) -> str:
    """增长 × 通胀 → 四象限（MC-02 确认层）。

    归并规则（纯函数，§1.4）：inflation=+1 → 增长收缩判滞胀、否则过热；
    inflation≤0 → 增长收缩判衰退、否则复苏。无第五状态。
    """
    if growth not in (-1, 0, 1) or inflation not in (-1, 0, 1):
        raise ValueError("growth/inflation ∈ {-1,0,1}")
    if inflation == 1:
        return "滞胀" if growth == -1 else "过热"
    return "衰退" if growth == -1 else "复苏"


def locate_phase(growth: int, inflation: int) -> tuple[str, float]:
    """象限主格（增长/通胀均非零）才有真实相位；中性区归并后固定 前期 / 0（§1.4）。"""
    regime = locate_regime(growth, inflation)
    if growth == 0 or inflation == 0:
        return "前期", 0.0
    return regime, -1.0  # -1 为哨兵：主象限，progress 由 phase.py 计算


def center_of(regime: str, mc: str) -> float:
    """36 格基准仓位中枢（%）。键不存在即查表违例。"""
    try:
        return C.EQUITY_CENTER[(regime, mc)]
    except KeyError as e:
        raise KeyError(f"36 格查表越界：{e}") from e


def assert_grid_orthogonality() -> None:
    """MC-09 反例断言辅助：mc=双宽 必须落在四象限不同行（非单一映射）。"""
    rows = {r: C.EQUITY_CENTER[(r, "双宽")] for r in C.REGIMES}
    if len(set(rows.values())) != 4:
        raise RuntimeError("双宽四行仓位必须互不相同（§1.4 ②）")


assert_grid_orthogonality()
