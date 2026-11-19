"""DL-05 质量校验 + SC-03 时点断言 + CLI 四件套。"""
from __future__ import annotations

import datetime as dt

import pytest

from dq.cli import JobContext, JobResult, JobRunner, MemoryStatusSink, register_job
from dq.data.quality import (
    Alert,
    QualityConfig,
    check_completeness,
    check_outliers,
    check_timeliness,
    run_quality_checks,
)
from dq.data.trading_day import assert_latest_trading_day


class TestQuality:
    """验收：1 缺口 + 1 滞后 + 1 越界 → 恰 3 条；全合规 → 0 条；改阈值判定随之变。"""

    def _cfg(self, **kw):
        base = dict(
            expected_dates=["2026-01-02", "2026-01-05"],
            expected_latest="2026-01-05",
            max_lag_days=1,
            bounds={"close": (0.0, 100.0)},
        )
        base.update(kw)
        return QualityConfig(**base)

    def test_three_alerts_one_each(self):
        alerts = run_quality_checks(
            dates={"2026-01-02"},                       # 缺 2026-01-05 → completeness
            latest=dt.date(2026, 1, 3),                  # 滞后 2 天 > 1 → timeliness
            latest_row={"close": 150.0},                 # 越界 → outlier
            cfg=self._cfg(), target="PMI",
        )
        types = [a.rule_type for a in alerts]
        assert types == ["completeness", "timeliness", "outlier"]

    def test_all_clean_zero_alerts(self):
        alerts = run_quality_checks(
            dates={"2026-01-02", "2026-01-05"},
            latest=dt.date(2026, 1, 5),
            latest_row={"close": 42.0},
            cfg=self._cfg(), target="PMI",
        )
        assert alerts == []

    def test_threshold_change_flips_verdict(self):
        row = {"close": 120.0}
        assert check_outliers(row, self._cfg(), "x")  # 阈值 [0,100] → 越界
        assert check_outliers(row, self._cfg(bounds={"close": (0.0, 200.0)}), "x") == []  # 放宽 → 合规
        assert check_timeliness(dt.date(2026, 1, 3), self._cfg(max_lag_days=5), "x") == []
        assert check_timeliness(dt.date(2026, 1, 3), self._cfg(max_lag_days=1), "x")

    def test_completeness_and_timeliness_edges(self):
        assert check_completeness({"a"}, ["a", "b"], "x")[0].detail == "缺口日期 b"
        assert check_timeliness(None, self._cfg(), "x")[0].detail == "库内无数据，无法判定时效"
        assert check_timeliness(dt.date(2026, 1, 5), self._cfg(expected_latest=None), "x") == []

    def test_alert_fields(self):
        a = Alert("outlier", "PMI", "close=150")
        assert (a.rule_type, a.target, a.detail) == ("outlier", "PMI", "close=150")


class TestTradingDayAssert:
    """验收：滞后 1 日 + 重试上限 3 → 恰重试 3 次后 1 条告警、failed；正常 → 0 重试、done。"""

    def test_fail_after_exact_retries(self):
        calls = {"n": 0}

        def fetch():
            calls["n"] += 1
            return dt.date(2026, 1, 4)  # 恒滞后

        alerts = []
        ok = assert_latest_trading_day(fetch, dt.date(2026, 1, 5), max_retry=3,
                                       alert_sink=alerts.append)
        assert not ok and calls["n"] == 4 and len(alerts) == 1

    def test_pass_zero_retry(self):
        calls = {"n": 0}

        def fetch():
            calls["n"] += 1
            return dt.date(2026, 1, 5)

        ok = assert_latest_trading_day(fetch, dt.date(2026, 1, 5), max_retry=3,
                                       alert_sink=lambda a: pytest.fail("不应告警"))
        assert ok and calls["n"] == 1

    def test_retry_recovers(self):
        seq = iter([dt.date(2026, 1, 4), dt.date(2026, 1, 5)])
        ok = assert_latest_trading_day(lambda: next(seq), dt.date(2026, 1, 5), max_retry=3)
        assert ok


class TestCliRunner:
    """CLI 基座：注册表、状态上报 running→success/failed、退出码、耗时。"""

    def test_success_flow(self):
        sink = MemoryStatusSink()
        register_job("demo-ok", lambda ctx: JobResult(0, "ok"))
        r = JobRunner(sink).run(JobContext("demo-ok", dt.date(2026, 1, 1), "run-1"))
        assert r.exit_code == 0
        assert [e["status"] for e in sink.events] == ["running", "success"]
        assert sink.events[1]["log_summary"] == "ok"
        assert sink.events[1]["duration_ms"] >= 0

    def test_handler_exception_maps_to_failed(self):
        sink = MemoryStatusSink()
        register_job("demo-bad", lambda ctx: (_ for _ in ()).throw(RuntimeError("boom")))
        r = JobRunner(sink).run(JobContext("demo-bad", dt.date(2026, 1, 1), "run-2"))
        assert r.exit_code == 1
        assert sink.events[1]["status"] == "failed"
        assert "boom" in sink.events[1]["log_summary"]

    def test_unregistered_job_failed(self):
        sink = MemoryStatusSink()
        r = JobRunner(sink).run(JobContext("no-such", dt.date(2026, 1, 1), "run-3"))
        assert r.exit_code == 1 and "no-such" in sink.events[1]["log_summary"]

    def test_audit_fields_forwarded(self):
        sink = MemoryStatusSink()
        register_job("demo-ok", lambda ctx: JobResult(0, "ok"))
        JobRunner(sink).run(JobContext("demo-ok", dt.date(2026, 1, 1), "run-4",
                                       trigger_type="manual", operator="钟Sir"))
        assert sink.events[0]["trigger_type"] == "manual"
        assert sink.events[1]["operator"] == "钟Sir"
