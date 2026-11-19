"""MC-03 相位插值与基准仓位（《数据策略总文档》§1.4 相位与 ① 相位过渡倾斜）。

- 每个主象限（增长/通胀均非零）按「驱动下一翻转的变量」连续水平做滚动窗口
  min-max 归一化得 phase_progress ∈ [0,1]；< 0.5 → 前期，≥ 0.5 → 后期。
- 驱动变量一律取预判层：复苏/滞胀 → PPI 同比，过热/衰退 → PMI；GDP 不作驱动。
- 中性区归并后固定 前期 / 0（由 locate.locate_phase 处理）。
- 后期线性插值向时钟下一象限倾斜，翻转瞬间零跳变。
"""
from __future__ import annotations

from collections.abc import Sequence

from . import config as C
from .locate import center_of


def phase_progress(
    regime: str,
    pmi_series: Sequence[float],
    ppi_series: Sequence[float],
    window: int = C.PHASE_WINDOW_W,
) -> float:
    """phase_progress ∈ [0,1]（滚动窗口 min-max 归一化）。

    方向语义（§1.4 相位表）：
    - 复苏：通胀自谷底回升 → norm(PPI)
    - 过热：增长沿上行腿推进 → norm(PMI)
    - 滞胀：通胀自峰位回落 → 1 − norm(PPI)
    - 衰退：增长自谷底回升 → norm(PMI)
    窗口内 max==min（无波动）→ 0.0。
    """
    driver = C.PHASE_DRIVER[regime]
    series = list(ppi_series if driver == "ppi" else pmi_series)[-window:]
    if not series:
        raise ValueError(f"相位驱动序列缺失：{regime} 需要 {driver}")
    lo, hi = min(series), max(series)
    if hi == lo:
        norm = 0.0
    else:
        norm = (series[-1] - lo) / (hi - lo)
    if regime == "滞胀":
        norm = 1.0 - norm
    return round(min(max(norm, 0.0), 1.0), 6)


def phase_of(regime: str, progress: float) -> str:
    return "后期" if progress >= 0.5 else "前期"


def interpolate_weight(regime: str, mc: str, phase: str, progress: float) -> float:
    """equity_weight_base（%）：前期取中枢；后期沿时钟向下一象限线性插值。

    w_eff = center(regime,mc) + p·(center(next,mc) − center(regime,mc))，
    p = clamp((progress − 0.5)/0.5, 0, 1)。后期末端 p→1 时 w_eff → center(next)，
    翻转后进入下一象限前期即取 center(next)，两端相等，零跳变。
    插值中货币信用组合保持不变（仅象限沿时钟滑动）。
    """
    base = center_of(regime, mc)
    if phase != "后期":
        return base
    p = min(max((progress - 0.5) / 0.5, 0.0), 1.0)
    nxt = C.CLOCK_NEXT[regime]
    return base + p * (center_of(nxt, mc) - base)
