"""MC-01 四因子组状态判定（《数据策略总文档》§1.3）。

规则要点：
- 预判—验证分层（§1.3.0）：增长只由 PMI 判定，GDP 不参与当期 ±1；通胀以 CPI+PPI 预判。
- 货币只看量（§1.3.3，D-18 铁律：DR001/任何利率零输入）；信用只看社融+中长贷两项（§1.3.4）。
- 所有阈值取自 config，不硬编码；签名即契约 —— 传禁止入参直接抛错。
"""
from __future__ import annotations

from collections.abc import Sequence

from . import config as C


class IsolationViolation(ValueError):
    """隔离铁律违例：向判定函数传入口径禁止的入参。"""


def _trend(series: Sequence[float]) -> int:
    """序列趋势方向：+1 上 / -1 下 / 0 平（末值 vs 首值，零容差）。"""
    if not series:
        return 0
    if series[-1] > series[0]:
        return 1
    if series[-1] < series[0]:
        return -1
    return 0


def _ma3(series: Sequence[float]) -> float:
    return sum(series[-3:]) / 3.0


def _reject(name: str, value) -> None:
    if value is not None:
        raise IsolationViolation(f"{name} 属禁止入参（口径隔离）：不得传入 {name}")


# ---------------------------------------------------------------------------
# 增长 Growth（§1.3.1：仅 PMI）
# ---------------------------------------------------------------------------

def classify_growth(
    pmi_series: Sequence[float],
    *,
    gdp_yoy: float | None = None,      # 占位仅用于断言隔离，禁止传值
    rate_10y: float | None = None,     # 占位仅用于断言隔离（利率已出表）
) -> int:
    """增长状态 ∈ {+1,0,-1}，唯一主判据 = PMI（3 月均 + 趋势 + 连续 3 月规则）。

    判定次序（确定性）：扩张规则 → 收缩规则 → 兜底中性。
    断言不读取 GDP / 利率：传入即抛错（§1.11 测试要点）。
    """
    _reject("gdp_yoy", gdp_yoy)
    _reject("rate_10y", rate_10y)
    if len(pmi_series) < 3:
        raise ValueError("pmi_series 至少 3 期（3 月均判定）")

    ma3 = _ma3(pmi_series)
    prev_ma3 = _ma3(pmi_series[-6:-3]) if len(pmi_series) >= 6 else ma3
    trend_up = ma3 > prev_ma3
    trend_down = ma3 < prev_ma3
    last3 = list(pmi_series[-3:])
    mom = last3[-1] - last3[-2]

    # 扩张：3 月均 > 50.5 且趋势向上/持平；或连续 3 月 > 50 且环比不降
    if (ma3 > C.GROWTH_PMI_UPPER and not trend_down) or (
        all(v > 50.0 for v in last3) and mom >= 0
    ):
        return 1
    # 收缩：3 月均 < 49.5 且趋势向下；或连续 3 月 < 50 且环比走弱
    if (ma3 < C.GROWTH_PMI_LOWER and not trend_up) or (
        all(v < 50.0 for v in last3) and mom < 0
    ):
        return -1
    # 中性：荣枯线附近震荡（含规则间隙，保守兜底）
    return 0


# ---------------------------------------------------------------------------
# 通胀 Inflation（§1.3.2：CPI + PPI 传导预判）
# ---------------------------------------------------------------------------

def classify_inflation(
    cpi_yoy: float,
    cpi_trend: int,
    ppi_yoy: float,
    ppi_series: Sequence[float],
) -> tuple[int, str]:
    """通胀状态与 ppi_cpi_gap ∈ {扩张, 收敛, 一致}。

    - 上行(+1)：CPI > 3；或 PPI 3 月累计涨幅 > 1pct（成本端过热预判）。
    - 下行(-1)：CPI < 1 且趋势向下；或 PPI < 0 且连续下行（成本端通缩）。
    - 温和(0)：其余。
    - 背离标注：PPI 上而 CPI 未上 → gap=扩张；PPI 下而 CPI 仍高 → gap=收敛；否则一致。
    """
    if cpi_trend not in (-1, 0, 1):
        raise ValueError("cpi_trend ∈ {-1,0,1}")
    if len(ppi_series) < 3:
        raise ValueError("ppi_series 至少 3 期（3 月累计涨幅）")
    ppi_cum3 = ppi_series[-1] - ppi_series[-4] if len(ppi_series) >= 4 else (
        ppi_series[-1] - ppi_series[0]
    )
    ppi_down_run = all(
        ppi_series[i] < ppi_series[i - 1] for i in range(len(ppi_series) - 3, len(ppi_series))
    ) if len(ppi_series) >= 4 else False

    state = 0
    if cpi_yoy > C.INFLATION_CPI_UP or ppi_cum3 > C.INFLATION_PPI_CUM:
        state = 1
    elif (cpi_yoy < C.INFLATION_CPI_DOWN and cpi_trend < 0) or (
        ppi_yoy < 0 and ppi_down_run
    ):
        state = -1

    if state == 1 and ppi_cum3 > C.INFLATION_PPI_CUM and cpi_yoy <= C.INFLATION_CPI_UP:
        gap = "扩张"
    elif state == -1 and ppi_yoy < 0 and cpi_yoy >= C.INFLATION_CPI_DOWN:
        gap = "收敛"
    else:
        gap = "一致"
    return state, gap


# ---------------------------------------------------------------------------
# 货币 Money（§1.3.3：量唯一主判；DR001 / 任何利率零输入）
# ---------------------------------------------------------------------------

def classify_money(m2_trend: int, spread_trend: int) -> int:
    """货币量状态 ∈ {+1,0,-1}。

    入参为趋势方向：M2 同比趋势（总量）与 M1−M2 剪刀差趋势（活化度）。
    同向 → 取该方向；背离 → 保守取 0（设计默认，与信用背离处置同取向）；
    双 0 → 平稳 0。
    """
    for t in (m2_trend, spread_trend):
        if t not in (-1, 0, 1):
            raise ValueError("趋势入参 ∈ {-1,0,1}")
    if m2_trend == spread_trend:
        return m2_trend
    return 0  # 背离降中性


def classify_money_price(dr001: float | None = None, **forbidden) -> dict:
    """货币价辅助信号（D-18/D-30）：本期零产出占位。

    - 只接受 dr001 单入参；传任何第二利率（DR007/10Y/期限利差/NCD…）即抛错。
    - 输出仅 warn_flags / dr001_extreme 占位结构，不得参与判定。
    - 本期 warn_flags 恒为空（D-30 后移），仅保留签名与隔离断言。
    """
    if forbidden:
        raise IsolationViolation(
            f"classify_money_price 只接受 dr001 单入参，禁止：{sorted(forbidden)}"
        )
    if dr001 is None:
        return {"dr001_extreme": False, "warn_flags": []}
    if not isinstance(dr001, (int, float)):
        raise IsolationViolation("dr001 必须为数值")
    return {"dr001_extreme": False, "warn_flags": []}


# ---------------------------------------------------------------------------
# 信用 Credit（§1.3.4：社融 + 企业中长贷两项）
# ---------------------------------------------------------------------------

def classify_credit(
    afre_yoy: float,
    afre_yoy_3m_ago: float,
    ml_loan_yoy: float,
    ml_loan_yoy_3m_ago: float,
) -> tuple[int, bool]:
    """信用状态 ∈ {+1,0,-1}；返回 (state, diverged)。

    - 宽(+1)：社融存量同比趋势上行 且 企业中长贷同比多增（同向确认）。
    - 紧(-1)：社融趋势下行 或 中长贷同比少增（任一）。
    - 背离（社融上行但中长贷少增）→ 降 0，diverged=True（confidence=中，§1.12 假设 12）。
    - 阈值取 config（CREDIT_AFRE_DELTA / CREDIT_ML_DELTA）。
    """
    afre_delta = afre_yoy - afre_yoy_3m_ago
    loan_delta = ml_loan_yoy - ml_loan_yoy_3m_ago
    afre_up = afre_delta > C.CREDIT_AFRE_DELTA
    afre_down = afre_delta < -C.CREDIT_AFRE_DELTA
    loan_up = loan_delta > C.CREDIT_ML_DELTA
    loan_down = loan_delta < -C.CREDIT_ML_DELTA

    if afre_up and loan_up:
        return 1, False
    if afre_up and loan_down:
        return 0, True  # 靠政府债/票据冲量型背离，不得强判 ±1
    if afre_down or loan_down:
        return -1, False
    return 0, False
