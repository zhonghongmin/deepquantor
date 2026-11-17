"""宏观策略引擎 - 自动化测试（项目规约：所有功能形成自动化测试）。

覆盖文档 §1.12 实现要点：
  - 每个 classify_* 单因子状态判定
  - locate_regime / locate_money_credit 状态空间全覆盖
  - map_equity_weight 20 格状态空间全覆盖 + 边界
  - map_style_tilt 枚举合法性
  - map_asset_alloc 四项之和=1
  - run_macro 总装配契约 + 文档要求的「双紧+滞胀」反例断言
"""
import os
import sys

import pytest

# cli/ 根目录，使 dq 包可导入
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dq.macro.config import EQUITY_WEIGHT  # noqa: E402
from dq.macro.engine import (  # noqa: E402
    MacroInput,
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

# ---------------------------------------------------------------------------
# 1.3 单因子状态判定
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("gdp,pmi,expect", [
    (6.0, 51.0, 1),    # 扩张
    (4.0, 51.0, 0),    # 中性（gdp 在 3~5）
    (2.0, 51.0, -1),   # 收缩（gdp<3）
    (6.0, 49.0, -1),   # 收缩（pmi<50）
    (4.0, 49.0, -1),   # 收缩
    (4.0, 50.0, 0),    # 中性（pmi 恰好 50）
])
def test_classify_growth(gdp, pmi, expect):
    assert classify_growth(gdp, pmi) == expect


@pytest.mark.parametrize("cpi,ppi,ct,pt,expect", [
    (0.5, 0.0, 0, 0, -1),    # 通缩压力
    (2.0, 0.0, 0, 0, 0),     # 温和
    (4.0, 0.0, 0, 0, 1),     # 过热
    (2.0, -2.0, 0, -1, -1),  # ppi<0 且趋势向下
    (2.0, 6.0, 0, 1, 1),     # ppi 快速抬升
])
def test_classify_inflation(cpi, ppi, ct, pt, expect):
    assert classify_inflation(cpi, ppi, ct, pt) == expect


@pytest.mark.parametrize("m2t,spread,expect", [
    (1, 1, 1),
    (-1, -1, -1),
    (0, 0, 0),
    (-1, 1, 0),   # 方向相反 → 中性
])
def test_classify_money(m2t, spread, expect):
    assert classify_money(m2t, spread) == expect


@pytest.mark.parametrize("sf,credit,expect", [
    (1, 1, 1),
    (-1, -1, -1),
    (0, 0, 0),
    (1, -1, 0),
])
def test_classify_credit(sf, credit, expect):
    assert classify_credit(sf, credit) == expect


@pytest.mark.parametrize("rate,spread,expect", [
    (-1, 0, 1),
    (1, 0, -1),
    (0, 1, 1),
    (0, -1, -1),
    (0, 0, 0),
])
def test_classify_rate(rate, spread, expect):
    assert classify_rate(rate, spread) == expect


@pytest.mark.parametrize("usd,cny,u10,fed,expect", [
    (-1, -1, -1, -1, 1),  # 全面友好
    (1, 1, 1, 1, -1),     # 全面收紧
    (0, 0, 0, 0, 0),      # 平稳
    (1, -1, 0, 0, -1),    # 美元涨/人民币贬背离 → 审慎
])
def test_classify_external(usd, cny, u10, fed, expect):
    assert classify_external(usd, cny, u10, fed) == expect


# ---------------------------------------------------------------------------
# 1.4 状态定位
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("g,i,expect", [
    (1, -1, "复苏"), (1, 0, "复苏"), (1, 1, "过热"),
    (0, -1, "盘整"), (0, 0, "盘整"), (0, 1, "过热"),
    (-1, -1, "衰退"), (-1, 0, "衰退"), (-1, 1, "滞胀"),
])
def test_locate_regime(g, i, expect):
    assert locate_regime(g, i) == expect


@pytest.mark.parametrize("m,c,expect", [
    (1, 1, "双宽"), (1, 0, "宽货币紧信用"), (1, -1, "宽货币紧信用"),
    (0, 1, "紧货币宽信用"), (0, 0, "双紧"), (0, -1, "双紧"),
    (-1, 1, "紧货币宽信用"), (-1, 0, "双紧"), (-1, -1, "双紧"),
])
def test_locate_money_credit(m, c, expect):
    assert locate_money_credit(m, c) == expect


# ---------------------------------------------------------------------------
# 1.5 基准权益仓位（20 格状态空间全覆盖）
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("key", list(EQUITY_WEIGHT.keys()))
def test_map_equity_weight_coverage(key):
    regime, mc = key
    lo, hi = EQUITY_WEIGHT[key]
    eq = map_equity_weight(regime, mc)
    assert 0.0 <= eq <= 1.0
    assert eq == pytest.approx((lo + hi) / 200.0)


def test_map_equity_weight_boundary_values():
    assert map_equity_weight("复苏", "双宽") == pytest.approx(0.90)   # 85~95 中值
    assert map_equity_weight("滞胀", "双紧") == pytest.approx(0.375)  # 30~45 中值 ≤ 0.45


# ---------------------------------------------------------------------------
# 1.6 风格偏好（枚举合法性）
# ---------------------------------------------------------------------------

SIZES = {"大盘", "小盘", "均衡"}
VGS = {"价值", "成长", "均衡"}
CDS = {"周期", "防御", "均衡"}

@pytest.mark.parametrize("regime", ["复苏", "过热", "滞胀", "衰退", "盘整"])
def test_map_style_tilt_enum(regime):
    st = map_style_tilt(regime)
    assert st.size in SIZES
    assert st.value_growth in VGS
    assert st.cycle_defensive in CDS


# ---------------------------------------------------------------------------
# 1.7 大类资产配置（四项之和=1，且 stock==equity_weight）
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("env,eq", [
    ("避险", 0.375), ("衰退宽货币", 0.625),
    ("风险", 0.90), ("均衡", 0.575),
])
def test_map_asset_alloc_sum(env, eq):
    alloc = map_asset_alloc(env, eq)
    assert alloc.total() == pytest.approx(1.0)
    assert alloc.stock == pytest.approx(eq)
    assert alloc.bond >= 0 and alloc.gold >= 0 and alloc.cash >= 0
    # 避险环境现金舱必须为正
    if env == "避险":
        assert alloc.cash > 0


# ---------------------------------------------------------------------------
# 1.12 总装配
# ---------------------------------------------------------------------------

def _run(**kw):
    base = dict(gdp_yoy=0.0, pmi_3m=50.0, cpi_yoy=0.0, ppi_yoy=0.0,
                m2_yoy_trend=0, spread_trend=0, sf_yoy_trend=0,
                credit_yoy_trend=0, rate_10y_trend=0, term_spread_trend=0,
                usd_idx_trend=0, usdcny_trend=0, us10y_trend=0, fed_trend=0,
                confidence="中")
    base.update(kw)
    return run_macro(MacroInput(signal_date="2026-09-15", **base))


def test_run_macro_recovery_dual_easing():
    """复苏 + 双宽 → 高仓、进攻姿态。"""
    sig = _run(gdp_yoy=6.0, pmi_3m=51.0,            # 增长 +1
               cpi_yoy=2.0,                          # 通胀温和
               m2_yoy_trend=1, spread_trend=1,       # 宽货币
               sf_yoy_trend=1, credit_yoy_trend=1)  # 宽信用
    assert sig.regime == "复苏"
    assert sig.money_credit == "双宽"
    assert sig.equity_weight == pytest.approx(0.90)
    assert sig.asset_alloc.total() == pytest.approx(1.0)
    assert sig.asset_alloc.stock == pytest.approx(sig.equity_weight)
    assert sig.style_tilt.value_growth == "成长"


def test_run_macro_stagflation_dual_tight_invariant():
    """文档硬约束：双紧 + 滞胀 → equity_weight ≤ 0.45 且 cash > 0。"""
    sig = _run(gdp_yoy=2.0,                          # 增长 -1
               cpi_yoy=4.0,                          # 通胀 +1 → 滞胀
               m2_yoy_trend=-1, spread_trend=-1,     # 紧货币
               sf_yoy_trend=-1, credit_yoy_trend=-1) # 紧信用 → 双紧
    assert sig.regime == "滞胀"
    assert sig.money_credit == "双紧"
    assert sig.equity_weight <= 0.45
    assert sig.asset_alloc.cash > 0
    assert sig.asset_alloc.total() == pytest.approx(1.0)


def test_run_macro_contract_factors_audit_only():
    """factors 字段仅记录离散状态用于审计，不得参与评分（文档 §1.8）。"""
    sig = _run(gdp_yoy=6.0, pmi_3m=51.0)
    assert set(sig.factors.keys()) == {"growth", "inflation", "money", "credit", "rate", "external"}
    assert all(v in (-1, 0, 1) for v in sig.factors.values())
