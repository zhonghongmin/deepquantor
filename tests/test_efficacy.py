"""MC-08 信号有效性离线评估单测（Spec §4.3 / 数据策略 §1.15.1）。"""
import pytest

from dq.macro.efficacy import (
    GrowthOutcome,
    McPeriod,
    _shift_month,
    evaluate_signal_efficacy,
    find_episodes,
)


def _history(spec: list[tuple[str, str]], flags: dict[str, list[str]] | None = None):
    flags = flags or {}
    return [McPeriod(p, mc, flags.get(p, [])) for p, mc in spec]


class TestEpisodes:
    def test_first_3_consecutive(self):
        h = _history([("2025-01", "双紧"), ("2025-02", "双宽"), ("2025-03", "双宽"),
                      ("2025-04", "双宽"), ("2025-05", "双宽")])
        eps = find_episodes(h)
        assert eps == [3]  # 首次连续 3 期在第 4 期（索引 3）触发

    def test_episode_dedup_then_retrigger(self):
        h = _history([
            ("2025-01", "双宽"), ("2025-02", "双宽"), ("2025-03", "双宽"),
            ("2025-04", "双宽"),          # 同段去重
            ("2025-05", "双紧"),          # 中断
            ("2025-06", "双宽"), ("2025-07", "双宽"), ("2025-08", "双宽"),
        ])
        eps = find_episodes(h)
        assert eps == [2, 7]  # 去重后新段重新触发

    def test_two_of_three_not_enough(self):
        h = _history([("2025-01", "双宽"), ("2025-02", "双宽"), ("2025-03", "紧货币·中性信用")])
        assert find_episodes(h) == []


class TestEvaluation:
    def _setup(self, warm_pattern: str = "111000"):
        periods = [f"2024-{m:02d}" for m in range(1, 13)] + [
            f"2025-{m:02d}" for m in range(1, 13)
        ]
        mc_cycle = ["双紧", "双宽", "双宽", "双宽", "双紧", "双紧"] * 2
        h = _history(list(zip(periods, mc_cycle, strict=False)))
        outcomes = [
            GrowthOutcome(p, warm_pattern[i % len(warm_pattern)] == "1",
                          published_at=f"{p}-15")
            for i, p in enumerate(periods)
        ]
        return h, outcomes

    def test_report_structure(self):
        h, oc = self._setup()
        rpt = evaluate_signal_efficacy(h, oc)
        assert rpt["signal_id"] == "mc_to_growth"
        for w in ("1-3m", "3-6m", "6-12m"):
            wv = rpt["lead_windows"][w]
            assert {"n_episodes", "hit_rate", "baseline", "ci95", "p_value",
                    "out_of_sample"} <= set(wv)
        assert rpt["n_episodes_total"] > 0

    def test_lookahead_missing_outcome_skipped(self):
        # 前视隔离：未来数据未发布 → 该 episode 该窗口跳过，不虚构
        h = _history([("2026-08", "双紧"), ("2026-09", "双宽"), ("2026-10", "双宽"),
                      ("2026-11", "双宽")])
        oc = [GrowthOutcome("2026-09", False, published_at="2026-10-15")]
        rpt = evaluate_signal_efficacy(h, oc)
        assert rpt["lead_windows"]["6-12m"]["n_episodes"] == 0
        assert rpt["lead_windows"]["6-12m"]["hit_rate"] is None

    def test_vintage_uniqueness_enforced(self):
        oc = [GrowthOutcome("2026-01", True, published_at="2026-02-15")] * 2
        with pytest.raises(ValueError):
            evaluate_signal_efficacy([], oc)  # 同期两条 = 修订，违反 vintage 一致

    def test_insufficient_samples_reference_grade(self):
        h = _history([("2026-08", "双紧"), ("2026-09", "双宽"), ("2026-10", "双宽"),
                      ("2026-11", "双宽")])
        oc = [GrowthOutcome("2026-09", True, published_at="2026-10-15")]
        rpt = evaluate_signal_efficacy(h, oc)
        assert rpt["verdict"] == "参考级"
        assert rpt["hit_rate_status"] == "pending"

    def test_invalid_flags_downgrade(self):
        # 失效条件触发 → 降级为参考级（T-7）
        h, oc = self._setup()
        h_with_flag = [
            McPeriod(p.period, p.money_credit,
                     ["credit_distortion"] if p.period == "2024-03" else [])
            for p in h
        ]
        rpt = evaluate_signal_efficacy(h_with_flag, oc)
        assert rpt["verdict"] == "参考级"

    def test_no_write_back_to_macro_signal(self):
        # 物理隔离：评估函数不接收/不返回任何 MacroSignal 对象（结构级断言）
        import inspect

        from dq.macro import efficacy
        sig = inspect.signature(evaluate_signal_efficacy)
        assert "macro_signal" not in sig.parameters
        assert not hasattr(efficacy, "write_macro_signal")


def test_shift_month():
    assert _shift_month("2025-10", 3) == "2026-01"
    assert _shift_month("2025-01", 12) == "2026-01"
