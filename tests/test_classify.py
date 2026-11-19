"""MC-01 四因子组状态判定单测（Spec §4.1 / 数据策略 §1.3 全部分组路径）。"""
import pytest

from dq.macro.classify import (
    IsolationViolation,
    classify_credit,
    classify_growth,
    classify_inflation,
    classify_money,
    classify_money_price,
)

# ---------------------------------------------------------------------------
# 增长（§1.3.1：仅 PMI）
# ---------------------------------------------------------------------------

class TestGrowth:
    def test_expansion_ma3_above_upper_trend_up(self):
        # 3 月均 > 50.5 且趋势向上
        assert classify_growth([50.2, 50.4, 50.6, 50.8, 51.0]) == 1

    def test_expansion_ma3_above_upper_trend_flat(self):
        # 3 月均 > 50.5 且趋势持平（前 3 月均相等）
        assert classify_growth([50.6, 50.6, 50.6, 50.6, 50.6]) == 1

    def test_expansion_3m_above_50_mom_not_down(self):
        # 连续 3 月 > 50 且环比不降（3 月均 ≤ 50.5 也可由本路径判扩张）
        assert classify_growth([49.0, 50.1, 50.2, 50.3]) == 1

    def test_neutral_band(self):
        assert classify_growth([49.8, 50.0, 50.2]) == 0

    def test_contraction_ma3_below_lower_trend_down(self):
        # 3 月均 < 49.5 且趋势向下
        assert classify_growth([49.8, 49.4, 49.0, 48.6, 48.2]) == -1

    def test_contraction_3m_below_50_mom_down(self):
        # 连续 3 月 < 50 且环比走弱
        assert classify_growth([50.5, 49.9, 49.5, 49.0]) == -1

    def test_gap_case_falls_to_neutral(self):
        # 规则间隙：3 月均 > 50.5 但趋势向下 → 保守中性（确定性兜底）
        assert classify_growth([51.5, 51.3, 51.2, 51.0, 50.8, 50.6]) == 0

    def test_isolation_no_gdp_input(self):
        # GDP 恒为验证层：作为入参传入即抛错（§1.11）
        with pytest.raises(IsolationViolation):
            classify_growth([50.0, 50.1, 50.2], gdp_yoy=5.0)

    def test_isolation_no_rate_input(self):
        # 利率已出表：传入即抛错
        with pytest.raises(IsolationViolation):
            classify_growth([50.0, 50.1, 50.2], rate_10y=2.5)

    def test_needs_3_periods(self):
        with pytest.raises(ValueError):
            classify_growth([50.0, 50.1])


# ---------------------------------------------------------------------------
# 通胀（§1.3.2：CPI + PPI 传导预判）
# ---------------------------------------------------------------------------

class TestInflation:
    def test_cpi_above_3_up(self):
        state, gap = classify_inflation(3.5, 1, 1.0, [0.5, 0.8, 1.0])
        assert state == 1

    def test_ppi_cum_above_1pct_up_with_gap_expand(self):
        # PPI 3 月累计涨幅 > 1pct、CPI 未上（≤3）→ +1、gap=扩张（上行偏早）
        state, gap = classify_inflation(1.8, 0, 1.2, [0.0, 0.4, 0.8, 1.2])
        assert state == 1
        assert gap == "扩张"

    def test_cpi_below_1_trend_down(self):
        state, gap = classify_inflation(0.5, -1, 0.3, [0.3, 0.3, 0.3])
        assert state == -1

    def test_ppi_negative_consecutive_down_with_gap_converge(self):
        # PPI < 0 连续下行、CPI 仍高（≥1）→ -1、gap=收敛（下行偏早）
        state, gap = classify_inflation(2.2, 0, -0.6, [0.4, -0.2, -0.4, -0.6])
        assert state == -1
        assert gap == "收敛"

    def test_mild(self):
        state, gap = classify_inflation(2.0, 0, 0.5, [0.3, 0.4, 0.5])
        assert state == 0
        assert gap == "一致"

    def test_ppi_cum_needs_3_periods(self):
        with pytest.raises(ValueError):
            classify_inflation(2.0, 0, 0.5, [0.4, 0.5])


# ---------------------------------------------------------------------------
# 货币（§1.3.3：量唯一主判，DR001 零输入）
# ---------------------------------------------------------------------------

class TestMoney:
    @pytest.mark.parametrize("m2,spread,expect", [
        (1, 1, 1),    # 同向宽松
        (-1, -1, -1), # 同向收紧
        (0, 0, 0),    # 平稳
        (1, -1, 0),   # 背离降中性
        (-1, 1, 0),   # 背离降中性
        (1, 0, 0),    # 单边背离降中性
        (0, 1, 0),
    ])
    def test_money_three_states(self, m2, spread, expect):
        assert classify_money(m2, spread) == expect

    def test_price_signal_isolated_placeholder(self):
        # D-30 后移：本期零产出占位；DR001 极值也不改变任何判定字段
        out1 = classify_money_price(dr001=1.98)
        out2 = classify_money_price(dr001=0.01)
        assert out1 == out2 == {"dr001_extreme": False, "warn_flags": []}

    def test_price_signal_rejects_other_rates(self):
        # 只接受 dr001 单入参：DR007 / 10Y / NCD 等一律抛错（无锚）
        with pytest.raises(IsolationViolation):
            classify_money_price(dr001=1.5, dr007=2.0)
        with pytest.raises(IsolationViolation):
            classify_money_price(dr001=1.5, yield_10y=2.5)
        with pytest.raises(IsolationViolation):
            classify_money_price(dr001=1.5, ncd_1y_aaa=2.1)


# ---------------------------------------------------------------------------
# 信用（§1.3.4：社融 + 企业中长贷两项）
# ---------------------------------------------------------------------------

class TestCredit:
    def test_double_up_wide_credit(self):
        # 社融上行 且 中长贷多增 → 宽信用
        assert classify_credit(8.9, 8.0, 3.2, 2.4) == (1, False)

    def test_divergence_afre_up_loan_down(self):
        # 社融上行但中长贷少增（政府债/票据冲量）→ 降 0，diverged=True
        assert classify_credit(9.0, 8.0, 2.0, 3.0) == (0, True)

    def test_afre_down_tight(self):
        # 社融趋势下行 → 紧信用（「或」语义）
        assert classify_credit(7.8, 8.5, 3.2, 3.0) == (-1, False)

    def test_loan_down_tight(self):
        # 中长贷同比少增 → 紧信用
        assert classify_credit(8.5, 8.4, 1.0, 2.0) == (-1, False)

    def test_small_deltas_neutral(self):
        # 两项 3 月变动均在阈值内 → 平稳中性
        assert classify_credit(8.5, 8.45, 3.0, 2.8) == (0, False)

    def test_afre_m2_gap_not_accepted(self):
        # 信用判定签名无货币量入参：结构级隔离（参数表即契约）
        import inspect
        sig = inspect.signature(classify_credit)
        assert "m2" not in sig.parameters
        assert "afre_m2_gap" not in sig.parameters
