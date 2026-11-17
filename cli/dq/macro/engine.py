"""宏观策略引擎 - 纯函数 + 总装配。

对应《量化选股系统·宏观策略文档》v1.0：
  §1.3 单因子状态判定（规则，非因子评分）
  §1.4 周期 / 货币信用状态定位
  §1.5 状态 → 基准权益仓位（查表取中值）
  §1.6 风格偏好映射
  §1.7 大类资产配置
  §1.12 实现要点（纯函数 + 可测试）

设计约束（策略总文档 §3.1）：宏观层是状态机 + 查表，**不计算因子评分**，
因此本模块无任何 IC/IR / 分层 / 正交 / 加权 machinery。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .config import ASSET_ENV_WEIGHTS, EQUITY_WEIGHT, STYLE_TILT
from .schema import AssetAlloc, MacroSignal, StyleTilt

# ----------------------------------------------------------------------------
# §1.3 单因子状态判定：给定指标值，返回 ∈ {-1, 0, +1}
#   这些函数只做离散状态分类，结果仅供状态定位与审计，不加权合成任何评分。
# ----------------------------------------------------------------------------

def classify_growth(gdp_yoy: float, pmi_3m: float) -> int:
    """增长：扩张(+1) / 中性(0) / 收缩(-1)。"""
    if gdp_yoy >= 5 and pmi_3m > 50:
        return 1
    if gdp_yoy < 3 or pmi_3m < 50:
        return -1
    return 0


def classify_inflation(cpi_yoy: float, ppi_yoy: float,
                       cpi_trend: int = 0, ppi_trend: int = 0) -> int:
    """通胀：上行(+1) / 温和(0) / 下行(-1)。"""
    if cpi_yoy < 1 or (ppi_yoy < 0 and ppi_trend < 0):
        return -1
    if cpi_yoy > 3 or (ppi_yoy > 5 and ppi_trend > 0):
        return 1
    return 0


def classify_money(m2_yoy_trend: int, spread_trend: int) -> int:
    """货币：宽松(+1) / 中性(0) / 收紧(-1)。信息为趋势方向(±1)。"""
    if m2_yoy_trend >= 0 and spread_trend > 0:
        return 1
    if m2_yoy_trend < 0 and spread_trend < 0:
        return -1
    return 0


def classify_credit(sf_yoy_trend: int, credit_yoy_trend: int) -> int:
    """信用：宽信用(+1) / 中性(0) / 紧信用(-1)。"""
    if sf_yoy_trend > 0 and credit_yoy_trend > 0:
        return 1
    if sf_yoy_trend < 0 and credit_yoy_trend < 0:
        return -1
    return 0


def classify_rate(rate_10y_trend: int, term_spread_trend: int) -> int:
    """利率：宽松(+1) / 中性(0) / 收紧(-1)。"""
    if rate_10y_trend < 0 or term_spread_trend > 0:
        return 1
    if rate_10y_trend > 0 or term_spread_trend < 0:
        return -1
    return 0


def classify_external(usd_idx_trend: int, usdcny_trend: int,
                      us10y_trend: int = 0, fed_trend: int = 0) -> int:
    """海外：友好(+1) / 中性(0) / 收紧(-1)。

    背离处理（§1.3.6）：若美元指数与 USDCNY 方向相反，视为中国特有风险，
    取更审慎一侧（收紧），二者不相互抵消。
    """
    if usd_idx_trend != 0 and usdcny_trend != 0 and (usd_idx_trend * usdcny_trend) < 0:
        return -1
    bull = sum([usd_idx_trend < 0, usdcny_trend < 0, us10y_trend < 0, fed_trend < 0])
    bear = sum([usd_idx_trend > 0, usdcny_trend > 0, us10y_trend > 0, fed_trend > 0])
    if bull > bear:
        return 1
    if bear > bull:
        return -1
    return 0


# ----------------------------------------------------------------------------
# §1.4 状态定位模型：离散状态 → 状态空间
# ----------------------------------------------------------------------------

# 增长＼通胀： 下行(-1) / 温和(0) / 上行(+1)
_REGIME_TABLE = {
    (1, -1): "复苏", (1, 0): "复苏", (1, 1): "过热",
    (0, -1): "盘整", (0, 0): "盘整", (0, 1): "过热",
    (-1, -1): "衰退", (-1, 0): "衰退", (-1, 1): "滞胀",
}


def locate_regime(growth: int, inflation: int) -> str:
    """第一维：周期象限（增长 × 通胀）。返回 4 主象限 + 盘整。"""
    return _REGIME_TABLE[(growth, inflation)]


def locate_money_credit(money: int, credit: int) -> str:
    """第二维：货币信用组合（货币 × 信用）。

    三态({-1,0,+1})压成二元(宽/非宽)：仅严格 >0 视为「宽」，中性(0)
    归入「非宽」侧（保守倾向，使双紧成为最不友好的兜底状态）。
    共 4 种组合：双宽 / 宽货币紧信用 / 紧货币宽信用 / 双紧。
    """
    if money > 0 and credit > 0:
        return "双宽"
    if money > 0 and credit <= 0:
        return "宽货币紧信用"
    if money <= 0 and credit > 0:
        return "紧货币宽信用"
    return "双紧"


# ----------------------------------------------------------------------------
# §1.5 基准权益仓位（查表，取区间中值；无连续加权评分）
# ----------------------------------------------------------------------------

def map_equity_weight(regime: str, mc: str) -> float:
    """状态 → 基准权益仓位中枢（0~1 比例）。取区间 (lo+hi)/2 再 /100。"""
    lo, hi = EQUITY_WEIGHT[(regime, mc)]
    return (lo + hi) / 200.0


# ----------------------------------------------------------------------------
# §1.6 风格偏好映射
# ----------------------------------------------------------------------------

def map_style_tilt(regime: str) -> StyleTilt:
    """状态 → 风格偏好（size / value_growth / cycle_defensive）。"""
    size, vg, cd = STYLE_TILT[regime]
    return StyleTilt(size=size, value_growth=vg, cycle_defensive=cd)


# ----------------------------------------------------------------------------
# §1.7 大类资产配置
# ----------------------------------------------------------------------------

def _env_of(regime: str, mc: str) -> str:
    """环境类别判定：决定 bond/gold/cash 的相对权重。"""
    if regime == "滞胀" or mc == "双紧":
        return "避险"
    if regime == "衰退" and mc in ("双宽", "宽货币紧信用"):
        return "衰退宽货币"
    if regime in ("复苏", "过热"):
        return "风险"
    return "均衡"


def map_asset_alloc(env: str, equity_weight: float) -> AssetAlloc:
    """状态环境 → 大类资产配置（stock = equity_weight，剩余按权重分配）。"""
    bw, gw, cw = ASSET_ENV_WEIGHTS[env]
    total = bw + gw + cw
    remain = 1.0 - equity_weight
    bond = round(remain * bw / total, 4)
    gold = round(remain * gw / total, 4)
    cash = round(remain - bond - gold, 4)
    return AssetAlloc(stock=equity_weight, bond=bond, gold=gold, cash=cash)


# ----------------------------------------------------------------------------
# §1.12 总装配
# ----------------------------------------------------------------------------

@dataclass
class MacroInput:
    """宏观引擎输入：最新可得指标值 + 趋势方向。均为原始语义，不含评分。"""
    signal_date: str
    gdp_yoy: float = 0.0
    pmi_3m: float = 50.0
    cpi_yoy: float = 0.0
    ppi_yoy: float = 0.0
    cpi_trend: int = 0
    ppi_trend: int = 0
    m2_yoy_trend: int = 0
    spread_trend: int = 0
    sf_yoy_trend: int = 0
    credit_yoy_trend: int = 0
    rate_10y_trend: int = 0
    term_spread_trend: int = 0
    usd_idx_trend: int = 0
    usdcny_trend: int = 0
    us10y_trend: int = 0
    fed_trend: int = 0
    confidence: str = "中"
    next_review: str = ""


def _next_review_date(signal_date: str) -> str:
    """下月同日（月末溢出收敛到 28 号）。"""
    d = datetime.strptime(signal_date, "%Y-%m-%d")
    year, month = d.year + (d.month // 12), d.month % 12 + 1
    return datetime(year, month, min(d.day, 28)).strftime("%Y-%m-%d")


def run_macro(inp: MacroInput) -> MacroSignal:
    """宏观总装配：指标 → 6 因子状态 → 周期象限 + 货币信用 → 配置。

    纯函数（无副作用、无 I/O）。数据源由 MacroInput 注入，便于单测 mock。
    """
    g = classify_growth(inp.gdp_yoy, inp.pmi_3m)
    i = classify_inflation(inp.cpi_yoy, inp.ppi_yoy, inp.cpi_trend, inp.ppi_trend)
    m = classify_money(inp.m2_yoy_trend, inp.spread_trend)
    c = classify_credit(inp.sf_yoy_trend, inp.credit_yoy_trend)
    r = classify_rate(inp.rate_10y_trend, inp.term_spread_trend)
    e = classify_external(inp.usd_idx_trend, inp.usdcny_trend, inp.us10y_trend, inp.fed_trend)

    regime = locate_regime(g, i)
    mc = locate_money_credit(m, c)
    eq = map_equity_weight(regime, mc)
    style = map_style_tilt(regime)
    env = _env_of(regime, mc)
    alloc = map_asset_alloc(env, eq)

    return MacroSignal(
        signal_date=inp.signal_date,
        regime=regime,
        money_credit=mc,
        equity_weight=eq,
        style_tilt=style,
        asset_alloc=alloc,
        confidence=inp.confidence,
        next_review=inp.next_review or _next_review_date(inp.signal_date),
        factors={"growth": g, "inflation": i, "money": m,
                 "credit": c, "rate": r, "external": e},
    )
