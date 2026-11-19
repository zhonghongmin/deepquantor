"""MC-05 / MC-07 / MC-04 总装与契约单测（Spec §3/§4.2，含 T-1 反例与隔离断言）。"""
import json

import pytest
from jsonschema import Draft202012Validator

from dq.macro import config as C
from dq.macro.engine import MacroInput, run_macro
from dq.macro.locate import PeriodMismatch
from dq.macro.schema import load_schema

PERIOD = "2026-10"


def full_input(**kw) -> MacroInput:
    """完整两层输入（增长扩张 / 通胀温和 / 双宽 → 复苏、中性区前期）。"""
    base = dict(
        signal_date="2026-11-15",
        pmi_month=PERIOD, pmi_series=[50.2, 50.4, 50.6, 50.8, 51.0],
        cpi_month=PERIOD, cpi_yoy=2.0, cpi_trend=0, cpi_core_yoy=0.6,
        ppi_month=PERIOD, ppi_series=[0.2, 0.3, 0.4],
        m2_trend=1, spread_trend=1, money_month=PERIOD,
        afre_yoy=8.9, afre_yoy_3m_ago=8.0, ml_loan_yoy=3.2, ml_loan_yoy_3m_ago=2.4,
        credit_month=PERIOD,
        macro_detail_month=PERIOD,
        cpi_up=["食品烟酒"], cpi_down=["教育文化娱乐"],
        ppi_up=["采掘", "原材料"], ppi_down=["加工"], ppi_note="上游强、中游弱",
        trade_export_up=["机电产品"], trade_export_down=["纺织服装"],
        factor_scores={"growth": None, "inflation": None, "money": None, "credit": None},
    )
    base.update(kw)
    return MacroInput(**base)


def _validate(signal):
    schema = load_schema()
    errors = list(Draft202012Validator(schema).iter_errors(signal.to_contract_dict()))
    assert not errors, [e.message for e in errors]


# ---------------------------------------------------------------------------
# MC-05：契约与落库
# ---------------------------------------------------------------------------

class TestContract:
    def test_full_run_passes_schema(self):
        s = run_macro(full_input())
        _validate(s)

    def test_no_extra_fields(self):
        # 多余字段 = 0：契约 JSON 键集合与 Schema 顶层完全一致
        s = run_macro(full_input())
        d = s.to_contract_dict()
        expected = {
            "signal_date", "regime", "phase", "phase_progress", "money_credit",
            "equity_weight", "style_tilt", "asset_alloc", "confidence", "vintage",
            "next_review", "factors", "money_detail", "credit_detail",
            "macro_detail", "growth_verified", "forecast_signals",
        }
        assert set(d) == expected

    def test_factors_only_four_no_rate(self):
        s = run_macro(full_input())
        assert set(s.factors) == {"growth", "inflation", "money", "credit"}
        assert "rate" not in s.factors

    def test_money_detail_d18_zero_dr001(self):
        s = run_macro(full_input())
        assert set(s.money_detail) == {"volume", "month"}
        blob = json.dumps(s.to_contract_dict(), ensure_ascii=False)
        for banned in ("price", "dr001", "quadrant", "anchor_", "corridor", "ncd"):
            assert banned not in blob.lower()

    def test_credit_detail_two_judges_only(self):
        s = run_macro(full_input())
        assert set(s.credit_detail) == {"volume", "afre_yoy", "ml_loan_yoy", "month"}
        assert s.factors["credit"] == s.credit_detail["volume"]

    def test_asset_alloc_five_sum_one(self):
        s = run_macro(full_input())
        a = s.asset_alloc
        assert set(a) == {"stock", "bond", "commodity", "gold", "cash"}
        assert a["commodity"] == 0.0
        assert abs(sum(a.values()) - 1.0) < 1e-6
        assert a["stock"] == pytest.approx(s.equity_weight)

    def test_snapshot_consistency_growth(self):
        # §3：factors.growth == growth_verified.pmi_state；GDP 不反写
        s = run_macro(full_input(gdp_yoy=4.5, gdp_quarter="2026Q3"))
        assert s.factors["growth"] == s.growth_verified["pmi_state"] == 1
        assert s.growth_verified["gdp_state"] == 0  # 4.5% → 0 档
        assert s.vintage["data_quality"] == "divergence"  # PMI 扩张 vs GDP 3–5%

    def test_db_row_shape(self):
        s = run_macro(full_input())
        row = s.to_db_row(run_id="r-001")
        for col in ("as_of", "regime", "money_credit", "growth_s", "inflation_s",
                    "money_s", "credit_s", "equity_weight", "style_json",
                    "asset_alloc_json", "confidence", "run_id", "signal_json"):
            assert col in row
        assert json.loads(row["signal_json"]) == s.to_contract_dict()


# ---------------------------------------------------------------------------
# MC-02 反例 T-1：mc=双宽 且 增长收缩 → 衰退 / 62.5% / confidence 降级
# ---------------------------------------------------------------------------

class TestT1DoubleWideRecession:
    def test_t1(self):
        s = run_macro(full_input(
            pmi_series=[49.9, 49.5, 49.2, 48.8, 48.5],  # 收缩
        ))
        assert s.money_credit == "双宽"
        assert s.regime == "衰退"
        assert s.audit["equity_weight_base"] == pytest.approx(0.625)  # 62.5%，不折减
        assert s.confidence == "低"  # 降级
        assert s.sub_label == C.UNCONFIRMED_SUB_LABEL  # 副标签：政策发力·待经济确认


# ---------------------------------------------------------------------------
# MC-07：字段隔离 / 未确认升级 / 副标签
# ---------------------------------------------------------------------------

class TestMC07:
    def test_upgrade_unconfirmed_holds_prev_regime(self):
        # 升级未确认：连续期数不足 → regime 保持上期（过热）、取区间下沿、降档、副标签
        s = run_macro(full_input(
            prev_regime="过热", upgrade_streak=1, pmi_up_streak=1, loan_up_now=True,
        ))
        assert s.regime == "过热"
        expected_low = C.EQUITY_CENTER[("过热", "双宽")] - C.UNCONFIRMED_HALF_BAND
        assert s.audit["equity_weight_base"] == pytest.approx(expected_low / 100.0)
        assert s.sub_label == C.UNCONFIRMED_SUB_LABEL
        assert s.confidence == "低"

    def test_upgrade_confirmed_when_streak_met(self):
        s = run_macro(full_input(
            prev_regime="过热", upgrade_streak=3, pmi_up_streak=2, loan_up_now=True,
        ))
        assert s.regime == "复苏"
        assert s.sub_label is None
        assert s.audit["equity_weight_base"] == pytest.approx(0.90)

    def test_downstream_cannot_derive_regime_from_mc(self):
        # 契约测试：同一 money_credit 下不同 growth 给出不同 regime → 互不推导
        s1 = run_macro(full_input(pmi_series=[49.9, 49.5, 49.2, 48.8, 48.5]))   # 衰退
        s2 = run_macro(full_input())                                             # 复苏
        assert s1.money_credit == s2.money_credit == "双宽"
        assert s1.regime != s2.regime

    def test_forecast_isolation(self):
        # 同一 as_of 下改写 forecast_signals，周期字段逐字段全等（T-5 隔离反例）
        fc = [{
            "signal_id": "ppi_cpi_long", "chain": "PPI→CPI成本传导(§1.3.2)",
            "basis_period": PERIOD, "lead_window": "3-6m", "direction": "up",
            "confidence": "medium", "hit_rate_status": "pending",
            "invalid_if": ["ppi_cpi_gap=expand"], "as_of": "2026-10-31",
        }]
        s1 = run_macro(full_input())
        s2 = run_macro(full_input(forecast_signals=fc))
        keys = ("regime", "phase", "phase_progress", "money_credit",
                "equity_weight", "asset_alloc", "confidence", "factors")
        for k in keys:
            assert getattr(s1, k) == getattr(s2, k)

    def test_forecast_pending_only(self):
        fc = [{
            "signal_id": "x", "chain": "c", "basis_period": PERIOD,
            "lead_window": "1-2m", "direction": "up", "confidence": "reference",
            "hit_rate_status": "valid", "invalid_if": [], "as_of": "2026-10-31",
        }]
        with pytest.raises(ValueError):
            run_macro(full_input(forecast_signals=fc))  # 未回测只能 pending


# ---------------------------------------------------------------------------
# 预判—验证分层（§1.11）
# ---------------------------------------------------------------------------

class TestNowcastVerification:
    def test_no_gdp_runs(self):
        s = run_macro(full_input())
        assert s.vintage["nowcast_only"] is True
        assert s.vintage["data_quality"] == "preliminary"

    def test_gdp_divergence_downgrades_confidence(self):
        # GDP 极差但 PMI 强扩张 → growth 仍 +1（PMI 决定）、divergence、降一档
        s = run_macro(full_input(gdp_yoy=2.0, gdp_quarter="2026Q3"))
        assert s.factors["growth"] == 1
        assert s.vintage["data_quality"] == "divergence"
        assert s.confidence == "低"

    def test_gdp_consistent_upgrades_confidence(self):
        s = run_macro(full_input(gdp_yoy=5.5, gdp_quarter="2026Q3"))
        assert s.growth_verified["consistent"] is True
        assert s.vintage["data_quality"] == "gdp_verified"
        assert s.confidence == "高"

    def test_phase_no_drift_with_gdp(self):
        # 同一交易日同一序列，GDP 未发布 vs 已发布（含修订）：相位与基准仓位完全相同
        s1 = run_macro(full_input())
        s2 = run_macro(full_input(gdp_yoy=5.5, gdp_quarter="2026Q3"))
        assert s1.phase_progress == s2.phase_progress
        assert s1.audit["equity_weight_base"] == s2.audit["equity_weight_base"]

    def test_ppi_leads_cpi_confidence_medium(self):
        # PPI 3 月累计 >1pct、CPI 仍在 1–3% → inflation=+1、gap=扩张、confidence=中
        s = run_macro(full_input(ppi_series=[0.0, 0.5, 1.2]))
        assert s.factors["inflation"] == 1
        assert s.vintage["ppi_cpi_gap"] == "扩张"
        assert s.confidence == "中"


# ---------------------------------------------------------------------------
# D-24 同月校验 / 降级运行
# ---------------------------------------------------------------------------

class TestPeriodAndDegraded:
    def test_period_mismatch_rejected(self):
        # 两层不同 period 被拒（MC-09 验收）
        with pytest.raises(PeriodMismatch):
            run_macro(full_input(credit_month="2026-09"))

    def test_degraded_mode_money_credit_only(self):
        # 降级运行：仅 M1/M2 + 社融齐备 → 九态照出、象限沿用上期、confidence 降一档
        s = run_macro(MacroInput(
            signal_date="2026-11-15",
            m2_trend=1, spread_trend=1, money_month=PERIOD,
            afre_yoy=8.9, afre_yoy_3m_ago=8.0, ml_loan_yoy=3.2, ml_loan_yoy_3m_ago=2.4,
            credit_month=PERIOD, prev_regime="衰退",
        ))
        assert s.money_credit == "双宽"
        assert s.regime == "衰退"  # 沿用上期
        assert s.audit["degraded"] is True
        assert s.confidence == "低"

    def test_degraded_requires_prev_regime(self):
        with pytest.raises(ValueError):
            run_macro(MacroInput(
                signal_date="2026-11-15",
                m2_trend=1, spread_trend=1, money_month=PERIOD,
                afre_yoy=8.9, afre_yoy_3m_ago=8.0,
                ml_loan_yoy=3.2, ml_loan_yoy_3m_ago=2.4, credit_month=PERIOD,
            ))


# ---------------------------------------------------------------------------
# MC-03/MC-04 端到端：36 格整行执行 + 微调贯通
# ---------------------------------------------------------------------------

class TestEndToEndGrid:
    def test_extreme_stagflation_double_tight(self):
        # 双紧 + 滞胀 → base ≤ 0.45 且 cash > 0（§1.11 反例）
        s = run_macro(full_input(
            pmi_series=[49.9, 49.5, 49.2, 48.8, 48.5],
            cpi_yoy=3.8, cpi_trend=1, ppi_series=[2.0, 2.4, 2.8],
            m2_trend=-1, spread_trend=-1,
            afre_yoy=7.0, afre_yoy_3m_ago=7.6,
            ml_loan_yoy=1.0, ml_loan_yoy_3m_ago=2.0,
            factor_scores={"growth": 1.0, "inflation": 1.0, "money": 1.0, "credit": 1.0},
        ))
        assert s.regime == "滞胀" and s.money_credit == "双紧"
        assert s.audit["equity_weight_base"] <= 0.45
        assert s.asset_alloc["cash"] > 0

    def test_phase_tilt_changes_stock_only_ratio(self):
        # 相位倾斜端到端：复苏后期向过热倾斜；非股四类等比缩放，五项仍合计 1
        s = run_macro(full_input(
            pmi_series=[50.3, 50.6, 50.9, 51.2],           # 扩张
            cpi_yoy=0.5, cpi_trend=-1,                      # CPI<1 且下行 → 下行
            ppi_series=[-1.0, -0.8, -0.6, -0.4, -0.2, 0.0, 0.1],  # 回升未过热
        ))
        assert s.regime == "复苏" and s.factors["inflation"] == -1
        assert s.phase == "后期"
        # 复苏后期双宽：90 → 向过热 71.5 倾斜
        assert s.audit["equity_weight_base"] == pytest.approx(0.715)
        a = s.asset_alloc
        assert abs(sum(a.values()) - 1.0) < 1e-6
        assert a["stock"] == pytest.approx(s.equity_weight)
        # 等比缩放：非股内部结构不变（bond:gold:cash = 3:3:4）
        assert a["bond"] / a["gold"] == pytest.approx(1.0)
        assert a["cash"] / a["gold"] == pytest.approx(4.0 / 3.0)
