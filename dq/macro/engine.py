"""宏观策略引擎总装配（MC-05，Spec §4）。

流水线（《数据策略总文档》§1.4）：
  四因子判定(MC-01) → 九态定位(MC-02) → 四象限归并 → D-24 同月校验 →
  相位插值基准仓(MC-03) → 未确认态处置(MC-07) → 因子评分有界微调(MC-10) →
  风格/五项资产配置(MC-04) → MacroSignal 组装(MC-05，§1.7 契约)。

纯函数：无 I/O、无副作用；落库由 job-macro 调用方完成。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from . import config as C
from .alloc import build_asset_alloc, map_style_tilt, validate_asset_alloc
from .classify import (
    IsolationViolation,
    classify_credit,
    classify_growth,
    classify_inflation,
    classify_money,
    classify_money_price,
)
from .locate import PeriodMismatch, center_of, locate_money_credit, locate_regime
from .position import interpolate_weight, phase_of, phase_progress
from .schema import MacroSignal
from .score import FactorScore


@dataclass
class MacroInput:
    """宏观引擎输入：预判层为主，GDP 仅作验证层（§1.3.0）。"""

    signal_date: str
    # ---- 增长（PMI 预判层；GDP 验证层）----
    pmi_month: str | None = None
    pmi_series: list[float] | None = None          # 升序月度 PMI，≥3 期
    pmi_up_streak: int = 0                          # 连续扩张期数（升级确认用）
    gdp_yoy: float | None = None                    # 验证层，不参与当期判定
    gdp_quarter: str | None = None
    # ---- 通胀 ----
    cpi_month: str | None = None
    cpi_yoy: float | None = None
    cpi_trend: int = 0
    cpi_core_yoy: float | None = None
    ppi_month: str | None = None
    ppi_series: list[float] | None = None           # 升序月度 PPI 同比，≥3 期
    # ---- 货币（量唯一主判；DR001 零输入）----
    m2_trend: int | None = None                     # M2 同比趋势 ∈ {-1,0,1}
    spread_trend: int | None = None                 # M1−M2 剪刀差趋势
    money_month: str | None = None
    # ---- 信用（社融 + 企业中长贷两项）----
    afre_yoy: float | None = None                   # 社融存量同比
    afre_yoy_3m_ago: float | None = None
    ml_loan_yoy: float | None = None                # 新增企业中长贷同比
    ml_loan_yoy_3m_ago: float | None = None
    credit_month: str | None = None
    # ---- 状态延续与升级确认（§1.4 ②）----
    prev_regime: str | None = None
    upgrade_streak: int = 0                         # 「扩张+中长贷多增」连续期数
    loan_up_now: bool | None = None                 # 当期中长贷是否同比多增
    # ---- 分项明细（§1.2.2，只下传中观，不进状态机）----
    macro_detail_month: str | None = None
    cpi_up: list[str] = field(default_factory=list)
    cpi_down: list[str] = field(default_factory=list)
    ppi_up: list[str] = field(default_factory=list)
    ppi_down: list[str] = field(default_factory=list)
    ppi_note: str = ""
    trade_export_up: list[str] = field(default_factory=list)
    trade_export_down: list[str] = field(default_factory=list)
    trade_import_up: list[str] = field(default_factory=list)
    trade_import_down: list[str] = field(default_factory=list)
    # ---- MC-10 因子评分微调 ----
    factor_scores: dict[str, float | None] | None = None
    factor_weights: dict[str, float] = field(default_factory=lambda: dict(C.FACTOR_WEIGHTS))
    kappa: float = C.KAPPA_DEFAULT
    macro_factor_enabled: bool = True
    # ---- 展示副本（只读，不写回判定）----
    forecast_signals: list[dict] = field(default_factory=list)


def _next_review(signal_date: str) -> str:
    d = datetime.strptime(signal_date, "%Y-%m-%d")
    year, month = d.year + d.month // 12, d.month % 12 + 1
    return datetime(year, month, min(d.day, 28)).strftime("%Y-%m-%d")


def _gdp_state(gdp_yoy: float | None) -> int | None:
    """GDP 分档（§1.12 假设 11）：≥5% → +1 / 3–5% → 0 / <3% → −1。仅验证用。"""
    if gdp_yoy is None:
        return None
    if gdp_yoy >= 5.0:
        return 1
    if gdp_yoy >= 3.0:
        return 0
    return -1


def _confidence(
    idx: int,
    *,
    gdp_verified: bool | None,
    divergence: bool,
    gap: str,
    credit_diverged: bool,
    policy_divergence: bool,
    unconfirmed: bool,
    degraded: bool,
) -> str:
    """置信度阶梯：高(0)/中(1)/低(2)。GDP 一致上调一档，背离下调一档；
    PPI/CPI 背离与信用背离封顶为「中」；政策背离、未确认态、降级运行各再降一档。"""
    i = idx
    if gdp_verified is True:
        i -= 1
    if divergence:
        i += 1
    i = max(i, 0)
    if gap != "一致" or credit_diverged:
        i = max(i, 1)
    if policy_divergence or unconfirmed or degraded:
        i += 1
    i = min(max(i, 0), 2)
    return C.CONFIDENCE_LADDER[i]


def run_macro(inp: MacroInput) -> MacroSignal:
    """宏观总装配：输入最新可得指标 → MacroSignal（§1.7 契约）。"""
    audit: dict[str, Any] = {}

    # ---- 1. 四因子判定（MC-01）----
    full_mode = all(
        x is not None
        for x in (inp.pmi_series, inp.cpi_yoy, inp.ppi_series, inp.m2_trend,
                  inp.spread_trend, inp.afre_yoy)
    )
    if not full_mode:
        # 降级运行（§1.4）：仅货币信用齐备即可输出九态基调，象限沿用上期。
        if inp.m2_trend is None or inp.spread_trend is None or inp.afre_yoy is None:
            raise ValueError("降级运行至少需要 M1/M2 与社融/中长贷齐备")
        if inp.prev_regime is None:
            raise ValueError("降级运行需 prev_regime（象限沿用上期）")

    growth = classify_growth(inp.pmi_series) if inp.pmi_series else None
    if inp.cpi_yoy is not None and inp.ppi_series:
        inflation, gap = classify_inflation(
            inp.cpi_yoy, inp.cpi_trend, inp.ppi_series[-1], inp.ppi_series
        )
    else:
        inflation, gap = None, "一致"
    money = classify_money(inp.m2_trend, inp.spread_trend)
    credit, credit_diverged = classify_credit(
        inp.afre_yoy, inp.afre_yoy_3m_ago or inp.afre_yoy,
        inp.ml_loan_yoy or 0.0, inp.ml_loan_yoy_3m_ago or 0.0,
    )
    mc = locate_money_credit(money, credit)

    # ---- 2. 确认层象限与相位 ----
    periods = {
        "pmi": inp.pmi_month, "cpi": inp.cpi_month, "ppi": inp.ppi_month,
        "money": inp.money_month, "credit": inp.credit_month,
        "macro_detail": inp.macro_detail_month,
    }
    period_mismatch = len(set(periods.values())) != 1
    if growth is None or inflation is None:
        regime = inp.prev_regime
        phase, progress = "前期", 0.0
        degraded = True
    elif period_mismatch:
        # D-24（§1.4）：两层 period 不一致 → 拒绝出 36 格，只走方向模式并标 period_mismatch
        if inp.prev_regime is None:
            raise PeriodMismatch(f"两层六处 period 不全等且无上期象限可沿用：{periods}")
        regime = inp.prev_regime
        phase, progress = "前期", 0.0
        degraded = True
    else:
        regime = locate_regime(growth, inflation)
        degraded = False
        if growth != 0 and inflation != 0:
            progress = phase_progress(regime, inp.pmi_series, inp.ppi_series)
            phase = phase_of(regime, progress)
        else:
            phase, progress = "前期", 0.0  # 中性区归并：固定前期/0

    # ---- 3. D-24 同月校验留痕（方向模式仍需标 period_mismatch）----
    if period_mismatch:
        audit["period_mismatch"] = periods

    # ---- 4. MC-07 未确认态处置 ----
    sub_label = None
    policy_divergence = money == 1 and growth == -1  # 宽货币 × 增长收缩
    if not degraded and regime == "复苏" and inp.prev_regime not in (None, "复苏"):
        confirmed = (
            inp.upgrade_streak >= C.UPGRADE_MIN_STREAK
            and inp.pmi_up_streak >= C.UPGRADE_PMI_MIN_STREAK
            and bool(inp.loan_up_now)
        )
        if not confirmed:
            regime = inp.prev_regime  # 保持上期
            sub_label = C.UNCONFIRMED_SUB_LABEL
    elif policy_divergence:
        sub_label = C.UNCONFIRMED_SUB_LABEL

    # ---- 5. 基准仓位（MC-03 相位插值）----
    if sub_label == C.UNCONFIRMED_SUB_LABEL and regime != locate_regime(
        growth or 0, inflation or 0
    ):
        # 未确认升级：保持上期象限，取区间下沿（§1.4 ②）
        base = max(0.0, center_of(regime, mc) - C.UNCONFIRMED_HALF_BAND) / 100.0
        phase, progress = "前期", 0.0
    else:
        base = interpolate_weight(regime, mc, phase, progress) / 100.0

    # ---- 6. MC-10 因子评分有界微调 ----
    fs = FactorScore(
        inp.factor_scores or {},
        weights=inp.factor_weights,
        kappa=inp.kappa,
        enabled=inp.macro_factor_enabled,
    )
    equity_weight, equity_weight_base = fs.adjust(base, regime, mc)

    # ---- 7. MC-04 风格与配置 ----
    style = map_style_tilt(regime)
    alloc = build_asset_alloc(regime, mc, equity_weight)

    # ---- 8. 验证层与 vintage ----
    gdp_state = _gdp_state(inp.gdp_yoy)
    if growth is None:
        data_quality = "preliminary"
        consistent = None
    elif gdp_state is None:
        data_quality = "preliminary"
        consistent = None
    else:
        consistent = growth == gdp_state
        data_quality = "gdp_verified" if consistent else "divergence"

    vintage = {
        "nowcast_only": gdp_state is None,
        "pmi_month": inp.pmi_month or inp.money_month or "",
        "cpi_month": inp.cpi_month or inp.money_month or "",
        "ppi_month": inp.ppi_month or inp.money_month or "",
        "gdp_verified_quarter": inp.gdp_quarter,
        "gdp_anchor": inp.gdp_yoy,
        "data_quality": data_quality,
        "ppi_cpi_gap": gap,
    }
    growth_verified = {
        "pmi_state": growth if growth is not None else (growth or 0),
        "gdp_state": gdp_state,
        "consistent": consistent,
        "note": "GDP 仅事后校验，不改当期判定",
    }
    if growth is None:
        growth_verified["pmi_state"] = 0

    # ---- 9. 置信度 ----
    confidence = _confidence(
        1,
        gdp_verified=consistent,
        divergence=data_quality == "divergence",
        gap=gap,
        credit_diverged=credit_diverged,
        policy_divergence=policy_divergence,
        unconfirmed=sub_label == C.UNCONFIRMED_SUB_LABEL and not policy_divergence,
        degraded=degraded,
    )

    # ---- 10. 契约组装 ----
    factors = {
        "growth": growth if growth is not None else 0,
        "inflation": inflation if inflation is not None else 0,
        "money": money,
        "credit": credit,
    }
    # §3 快照一致：factors.growth == growth_verified.pmi_state
    growth_verified["pmi_state"] = factors["growth"]

    for f in inp.forecast_signals:
        if f.get("hit_rate_status") not in ("pending", "valid", "invalid"):
            raise ValueError("forecast_signals.hit_rate_status 非法")
        if f.get("hit_rate_status") != "pending" and not f.get("_backtested"):
            raise ValueError("未回测的预测信号 hit_rate_status 只能是 pending（§1.7 只读派生）")

    audit["factor_score"] = fs.audit()
    audit["equity_weight_base"] = round(equity_weight_base, 6)
    audit["credit_diverged"] = credit_diverged
    audit["degraded"] = degraded
    audit["policy_divergence"] = policy_divergence
    audit["sub_label"] = sub_label

    return MacroSignal(
        signal_date=inp.signal_date,
        regime=regime,
        phase=phase,
        phase_progress=round(progress, 6),
        money_credit=mc,
        equity_weight=round(equity_weight, 6),
        style_tilt=style,
        asset_alloc=alloc,
        confidence=confidence,
        vintage=vintage,
        next_review=_next_review(inp.signal_date),
        factors=factors,
        money_detail={"volume": money, "month": inp.money_month or ""},
        credit_detail={
            "volume": credit,
            "afre_yoy": inp.afre_yoy,
            "ml_loan_yoy": inp.ml_loan_yoy,
            "month": inp.credit_month or "",
        },
        macro_detail={
            "month": inp.macro_detail_month or inp.credit_month or "",
            "cpi": {"up": inp.cpi_up, "down": inp.cpi_down, "core_yoy": inp.cpi_core_yoy},
            "ppi": {"up": inp.ppi_up, "down": inp.ppi_down, "note": inp.ppi_note},
            "trade": {
                "export_up": inp.trade_export_up, "export_down": inp.trade_export_down,
                "import_up": inp.trade_import_up, "import_down": inp.trade_import_down,
            },
        },
        growth_verified=growth_verified,
        forecast_signals=list(inp.forecast_signals),
        equity_weight_base=round(equity_weight_base, 6),
        sub_label=sub_label,
        audit=audit,
    )


__all__ = [
    "MacroInput", "MacroSignal", "IsolationViolation", "PeriodMismatch",
    "classify_money_price", "validate_asset_alloc", "run_macro",
]
