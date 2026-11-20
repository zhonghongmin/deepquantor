"""宏观引擎输入组装（B3-a 生产接线）：market.macro_indicator → MacroInput。

口径（spec §1.2/§1.3）+ 实测偏差（E 级，已记追踪表 DL-01 备注）：
- 社融存量同比：akshare 无存量接口（spec 引用的 macro_china_social_financing 已下线）。
  以央行《2026年10月金融统计数据报告》锚点存量（469.16 万亿元，同比 7.2%）倒推增量
  累加重构水平序列再取同比；增量与锚点同为央行口径，趋势方向可用。
- 企业中长贷同比多增：无分项公开接口，以新增人民币贷款（全口径）同比多增作代理。
- 纯读库组装：本模块无状态机逻辑，判定全部由 dq.macro.run_macro 完成。
"""
from __future__ import annotations

import datetime as dt
from collections import defaultdict

from ..macro import MacroInput

# 央行《2026年10月金融统计数据报告》（2026-11-13 发布）：社融存量 469.16 万亿元
AFRE_ANCHOR_MONTH = "2026-10"
AFRE_ANCHOR_STOCK_YI = 4_691_600.0  # 亿元

TREND_DEADBAND = 0.1    # 同比序列 3 月变动死区（pct）
GDP_Q_TABLE_FALLBACK = "GDPCUM"


def _sign(delta: float, deadband: float = TREND_DEADBAND) -> int:
    """3 月变动 → 趋势方向 ∈ {-1,0,1}（|Δ|≤死区视为平稳）。"""
    if delta > deadband:
        return 1
    if delta < -deadband:
        return -1
    return 0


def _shift_month(month: str, k: int) -> str:
    """YYYY-MM 平移 k 个月。"""
    y, mo = int(month[:4]), int(month[5:7])
    idx = y * 12 + (mo - 1) + k
    return f"{idx // 12}-{idx % 12 + 1:02d}"


def tsf_stock_levels(incr: dict[str, float]) -> dict[str, float]:
    """社融增量(亿元) → 存量水平(亿元)：锚点月向后正推、向前倒推累加。"""
    months = sorted(set(incr) | {AFRE_ANCHOR_MONTH})
    levels = {AFRE_ANCHOR_MONTH: AFRE_ANCHOR_STOCK_YI}
    for i, m in enumerate(months):
        if m > AFRE_ANCHOR_MONTH:                      # 锚点之后正推
            levels[m] = levels.get(months[i - 1], 0.0) + incr.get(m, 0.0)
    for i in range(len(months) - 1, -1, -1):           # 锚点之前倒推
        m = months[i]
        if m < AFRE_ANCHOR_MONTH:
            levels[m] = levels.get(months[i + 1], AFRE_ANCHOR_STOCK_YI) - incr.get(
                months[i + 1], 0.0)
    return levels


def tsf_stock_yoy(levels: dict[str, float]) -> dict[str, float]:
    """存量水平 → 存量同比（%）。"""
    out = {}
    for m, s in levels.items():
        prev_key = _shift_month(m, -12)
        prev = levels.get(prev_key)
        if prev and prev > 0:
            out[m] = (s / prev - 1.0) * 100.0
    return out


def loan_yoy_extra(incr: dict[str, float]) -> dict[str, float]:
    """新增贷款「同比多增」幅度（%）：当月增量 / 去年同月增量 − 1。

    基期增量 ≤ 0（负增长月）无多增/少增语义，跳过该月。
    """
    out = {}
    for m, v in incr.items():
        base = incr.get(_shift_month(m, -12))
        if base is not None and base > 0 and v > 0:
            out[m] = (v / base - 1.0) * 100.0
    return out


def _quarter_month(period: str) -> str:
    """YYYY-Qn → 季末月 YYYY-MM（与月频 cutoff 同口径比较）。"""
    return f"{period[:4]}-{int(period[6]) * 3:02d}"


def build_macro_input(conn, dialect: str, month_end: dt.date,
                      table: str = "market.macro_indicator") -> MacroInput:
    """从 macro_indicator 组装引擎输入；数据不足时抛 ValueError（job 转 failed 上报）。"""
    ph = "%s" if dialect == "postgres" else "?"
    cur = conn.cursor()
    cutoff = month_end.strftime("%Y-%m")
    cur.execute(f"SELECT freq, indicator_code, period, val, yoy FROM {table}")
    vals: dict[str, list[tuple[str, float]]] = defaultdict(list)
    yoys: dict[str, list[tuple[str, float]]] = defaultdict(list)
    gdp_yoy: float | None = None
    gdp_quarter: str | None = None
    for freq, code, period, val, yoy in cur.fetchall():
        if freq == "Q":  # GDP 验证层：单季同比优先，缺则用累计行；按季末月对齐 cutoff
            if _quarter_month(period) > cutoff:
                continue
            if code == "GDP" and yoy is not None:
                gdp_yoy, gdp_quarter = float(yoy), period
            elif code == GDP_Q_TABLE_FALLBACK and yoy is not None and gdp_yoy is None:
                gdp_yoy, gdp_quarter = float(yoy), period
            continue
        if period > cutoff:
            continue
        if val is not None:
            vals[code].append((period, float(val)))
        if yoy is not None:
            yoys[code].append((period, float(yoy)))

    def _series(d, code, n=None):
        items = sorted(d.get(code) or [])
        tail = items[-n:] if n else items
        return tail

    # ---- 增长（PMI 预判层）----
    pmi = _series(vals, "PMI")
    if len(pmi) < 3:
        raise ValueError(f"PMI 序列不足 3 期（仅 {len(pmi)} 期），无法判定增长因子")
    pmi_month, pmi_series = pmi[-1][0], [v for _, v in pmi[-12:]]

    # ---- 通胀 ----
    cpi = _series(yoys, "CPI")
    if len(cpi) < 3:
        raise ValueError("CPI 同比序列不足 3 期")
    ppi = _series(yoys, "PPI")
    if len(ppi) < 3:
        raise ValueError("PPI 同比序列不足 3 期")
    cpi_vals = [v for _, v in cpi]
    cpi_trend = _sign(cpi_vals[-1] - cpi_vals[-4]) if len(cpi_vals) >= 4 else 0

    # ---- 货币（量）：M2 同比趋势 + M1−M2 剪刀差趋势 ----
    m2 = _series(yoys, "M2")
    m1 = _series(yoys, "M1")
    if len(m2) < 3 or len(m1) < 3:
        raise ValueError("M1/M2 同比序列不足 3 期")
    m2_map = dict(m2)
    spread = [(p, m1_v - m2_map[p]) for p, m1_v in sorted(m1) if p in m2_map]
    if len(spread) < 4:
        raise ValueError("M1−M2 剪刀差序列不足 4 期")
    m2_vals = [v for _, v in m2]
    m2_trend = _sign(m2_vals[-1] - m2_vals[-4]) if len(m2_vals) >= 4 else 0
    spread_trend = _sign(spread[-1][1] - spread[-4][1])

    # ---- 信用：社融存量同比 + 新增贷款同比多增 ----
    tsf_incr = dict(_series(vals, "TSF"))
    afre = tsf_stock_yoy(tsf_stock_levels(tsf_incr))
    if len(afre) < 4:
        raise ValueError("社融存量同比序列不足 4 期")
    afre_sorted = sorted(afre.items())
    afre_yoy = afre_sorted[-1][1]
    afre_yoy_3m_ago = afre_sorted[-4][1]

    loan = loan_yoy_extra(dict(_series(vals, "CREDIT")))
    if len(loan) < 4:
        raise ValueError("新增贷款同比多增序列不足 4 期")
    loan_sorted = sorted(loan.items())
    credit_month = loan_sorted[-1][0]
    ml_loan_yoy = loan_sorted[-1][1]
    ml_loan_yoy_3m_ago = loan_sorted[-4][1]

    # ---- 状态延续：沿用上一期 regime（未确认态处置 §1.4 ②）----
    cur.execute(
        f"SELECT regime FROM signal.macro_signal WHERE as_of < {ph} "
        f"ORDER BY as_of DESC LIMIT 1", (month_end.isoformat(),))
    row = cur.fetchone()
    prev_regime = row[0] if row else None

    return MacroInput(
        signal_date=month_end.isoformat(),
        pmi_month=pmi_month, pmi_series=pmi_series,
        gdp_yoy=gdp_yoy, gdp_quarter=gdp_quarter,
        cpi_month=cpi[-1][0], cpi_yoy=cpi_vals[-1], cpi_trend=cpi_trend,
        ppi_month=ppi[-1][0], ppi_series=[v for _, v in ppi],
        m2_trend=m2_trend, spread_trend=spread_trend, money_month=m2[-1][0],
        afre_yoy=afre_yoy, afre_yoy_3m_ago=afre_yoy_3m_ago,
        ml_loan_yoy=ml_loan_yoy, ml_loan_yoy_3m_ago=ml_loan_yoy_3m_ago,
        credit_month=credit_month,
        prev_regime=prev_regime,
        macro_detail_month=pmi_month,
    )
