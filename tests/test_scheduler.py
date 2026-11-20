"""B3-a：register_jobs 幂等登记 + cron 守卫（退出码 2）+ 宏分频任务处理器。"""
from __future__ import annotations

import datetime as dt
import sqlite3
import textwrap

import pandas as pd
import pytest

import dq.jobs_macro  # noqa: F401 —— 触发注册
from dq.cli import JobContext, JobRunner, MemoryStatusSink
from scripts.register_jobs import (
    CronGuardViolation,
    cron_hits_trading_window,
    load_jobs,
    parse_cron,
    register,
    upsert_job_defs,
)


@pytest.fixture()
def tconn():
    c = sqlite3.connect(":memory:")
    c.execute("ATTACH ':memory:' AS task")
    c.execute("""CREATE TABLE task.job_def (
        job_key TEXT PRIMARY KEY, job_name TEXT, freq TEXT, cron_expr TEXT,
        cli_command TEXT, params_json TEXT, automation_id INTEGER,
        retry_cnt INTEGER, timeout_sec INTEGER, enabled INTEGER,
        updated_by TEXT, updated_at TEXT)""")
    return c


class TestCronGuard:
    """验收：cron 落 09:30–15:00 → 退出码 2；窗口外正常登记。"""

    def test_parse_cron(self):
        assert len(parse_cron("0 10 10-20 * *")) == 5
        with pytest.raises(ValueError):
            parse_cron("0 10 * *")

    def test_window_hits(self):
        assert cron_hits_trading_window("30 10 * * *")       # 10:30 命中
        assert cron_hits_trading_window("0 9-11 * * *")      # 覆盖 09:30 后
        assert cron_hits_trading_window("0 14 * * 1-5")      # 14:00 命中
        assert not cron_hits_trading_window("0 2 * * *")     # 02:00 窗口外
        assert not cron_hits_trading_window("0 16 * * *")    # 16:00 窗口外
        assert not cron_hits_trading_window("0 9 * * *")     # 09:00 起点前

    def test_0930_is_inclusive_start(self):
        assert cron_hits_trading_window("30 9 * * *")        # 09:30 属窗口（含起点）

    def test_register_blocked_exit2(self, tconn, tmp_path):
        p = tmp_path / "bad.yaml"
        p.write_text(textwrap.dedent("""\
            jobs:
              - job_key: bad
                job_name: 坏任务
                freq: daily
                cron_expr: "0 10 * * *"
                cli_command: "python -m x"
        """), encoding="utf-8")
        with pytest.raises(CronGuardViolation):
            register(tconn, p)
        assert tconn.execute("SELECT COUNT(*) FROM task.job_def").fetchone()[0] == 0

    def test_register_ok(self, tconn):
        jobs = load_jobs()  # 真实 jobs.yaml
        ins, _upd = upsert_job_defs(tconn, jobs)
        assert ins == len(jobs)
        rows = dict(tconn.execute(
            "SELECT job_key, cron_expr FROM task.job_def").fetchall())
        assert rows["macro-daily"] == "0 2 * * *"
        assert rows["macro-monthly"] == "0 10 10-20 * *"
        assert rows["macro-indicators"] == "0 3 11-16 * *"

    def test_idempotent_rerun(self, tconn):
        jobs = load_jobs()
        upsert_job_defs(tconn, jobs)
        ins, upd = upsert_job_defs(tconn, jobs)
        assert (ins, upd) == (0, len(jobs))
        assert tconn.execute("SELECT COUNT(*) FROM task.job_def").fetchone()[0] == len(jobs)

    def test_automation_id_preserved(self, tconn):
        jobs = load_jobs()
        upsert_job_defs(tconn, jobs)
        tconn.execute("UPDATE task.job_def SET automation_id = 88 WHERE job_key='macro-daily'")
        tconn.commit()
        upsert_job_defs(tconn, jobs)  # 重跑不得清掉平台回写
        aid = tconn.execute(
            "SELECT automation_id FROM task.job_def WHERE job_key='macro-daily'"
        ).fetchone()[0]
        assert aid == 88


# ---- 宏分频任务处理器 ----

def _sqlite_macro_tables():
    c = sqlite3.connect(":memory:")
    c.execute("ATTACH ':memory:' AS market")
    c.execute("ATTACH ':memory:' AS signal")
    c.execute("CREATE TABLE market.macro_daily (date TEXT, code TEXT, close REAL,"
              " PRIMARY KEY (date, code))")
    c.execute("CREATE TABLE market.macro_indicator ("
              "indicator_code TEXT, freq TEXT, period TEXT, indicator_name TEXT,"
              " val REAL, unit TEXT, yoy REAL, source TEXT,"
              " PRIMARY KEY (indicator_code, freq, period))")
    # 按契约字典动态建 signal.macro_signal 列（TEXT 即可，验落库逻辑非类型）
    from dq.macro import MacroInput, run_macro
    inp = MacroInput(
        signal_date="2026-10-31",
        pmi_month="2026-10", pmi_series=[50.0, 50.2, 50.4, 50.6, 50.8],
        cpi_month="2026-10", cpi_yoy=0.5, cpi_trend=1, cpi_core_yoy=0.5,
        ppi_month="2026-10", ppi_series=[0.1, 0.2, 0.3],
        m2_trend=1, spread_trend=1, money_month="2026-10",
        afre_yoy=8.0, afre_yoy_3m_ago=7.0, ml_loan_yoy=3.0,
        ml_loan_yoy_3m_ago=2.0, credit_month="2026-10",
        macro_detail_month="2026-10",
        factor_scores={"growth": None, "inflation": None, "money": None, "credit": None},
    )
    cols = list(run_macro(inp).to_contract_dict().keys())
    c.execute(f"CREATE TABLE signal.macro_signal ({', '.join(f'{col} TEXT' for col in cols)},"
              f" PRIMARY KEY (signal_date))")
    return c


class TestMacroJobs:
    def _run(self, job_key, services, **ctx_kwargs):
        sink = MemoryStatusSink()
        runner = JobRunner(sink)
        ctx = JobContext(job_key=job_key, run_id="r-" + job_key,
                         window_date=dt.date(2026, 11, 17), services=services, **ctx_kwargs)
        return runner.run(ctx), sink

    def test_monthly_in_window_upserts(self):
        conn = _sqlite_macro_tables()

        def fetch_range(s, e):
            from dq.macro import MacroInput
            return MacroInput(
                signal_date=(s + dt.timedelta(days=30)).isoformat(),
                pmi_month=s.isoformat(), pmi_series=[50.0, 50.2, 50.4, 50.6, 50.8],
                cpi_month=s.isoformat(), cpi_yoy=0.5, cpi_trend=1, cpi_core_yoy=0.5,
                ppi_month=s.isoformat(), ppi_series=[0.1, 0.2, 0.3],
                m2_trend=1, spread_trend=1, money_month=s.isoformat(),
                afre_yoy=8.0, afre_yoy_3m_ago=7.0, ml_loan_yoy=3.0,
                ml_loan_yoy_3m_ago=2.0, credit_month=s.isoformat(),
                macro_detail_month=s.isoformat(),
                factor_scores={"growth": None, "inflation": None, "money": None, "credit": None},
            )

        services = {"conn": conn, "provider": None, "fetch_range": fetch_range,
                    "table": "signal.macro_signal", "dialect": "sqlite"}
        # 2026-11-17 在发布窗口 10–20 内
        result, sink = self._run("macro-monthly", services)
        assert result.exit_code == 0, result.log_summary
        assert "落库 1 行" in sink.events[1]["log_summary"]

    def test_monthly_out_of_window_skips(self):
        def fetch_range(s, e):
            pytest.fail("窗口外不应取数")

        ctx = JobContext(job_key="macro-monthly", run_id="r-x",
                         window_date=dt.date(2026, 11, 5))  # 5 日不在 10–20
        r = JobRunner(MemoryStatusSink()).run(ctx)
        assert r.exit_code == 0 and "不在发布窗口" in r.log_summary

    def test_daily_skips_non_trading_day(self):
        conn = _sqlite_macro_tables()
        services = {"conn": conn, "fetch_range": lambda s, e: pytest.fail("不应取数"),
                    "is_trading_day": lambda d: False, "skip_non_trading_day": True,
                    "dialect": "sqlite"}
        r = JobRunner(MemoryStatusSink()).run(
            JobContext(job_key="macro-daily", run_id="r-d", window_date=dt.date(2026, 11, 1),
                       services=services))
        assert r.exit_code == 0 and "非交易日" in r.log_summary

    def test_daily_incremental(self):
        conn = _sqlite_macro_tables()
        d1, d2 = dt.date(2026, 11, 16), dt.date(2026, 11, 17)

        def fetch_range(s, e):
            want = [d for d in (d1, d2) if s <= d <= e]
            return pd.DataFrame({"date": [d.isoformat() for d in want],
                                 "code": ["PMI"] * len(want), "close": [1.0] * len(want)})

        services = {"conn": conn, "fetch_range": fetch_range,
                    "is_trading_day": lambda d: True, "skip_non_trading_day": True,
                    "dialect": "sqlite"}
        r = JobRunner(MemoryStatusSink()).run(
            JobContext(job_key="macro-daily", run_id="r-d2", window_date=d2,
                       services=services))
        assert r.exit_code == 0, r.log_summary
        n = conn.execute("SELECT COUNT(*) FROM market.macro_daily").fetchone()[0]
        assert n == 2

    def test_indicators_fetch_and_idempotent(self, monkeypatch):
        """DL-01：mock 取数 → 落库 macro_indicator；连跑两次幂等。"""
        import pandas as _pd

        import dq.data.fetchers as f

        conn = _sqlite_macro_tables()
        fake = _pd.DataFrame({
            "indicator_code": ["PMI", "PMI", "CPI"],
            "freq": ["M", "M", "M"],
            "period": ["2026-09", "2026-10", "2026-10"],
            "indicator_name": ["官方制造业PMI"] * 2 + ["CPI当月值"],
            "val": [49.5, 49.6, 100.2],
            "unit": ["%", "%", "%"],
            "yoy": [None, None, 0.2],
            "source": ["akshare"] * 3,
        })
        fake.attrs["failed"] = []
        monkeypatch.setattr(f, "fetch_all", lambda s, e: fake)

        services = {"conn": conn, "dialect": "sqlite",
                    "macro_indicator_table": "market.macro_indicator"}
        r = JobRunner(MemoryStatusSink()).run(
            JobContext(job_key="macro-indicators", run_id="r-i1", window_date=dt.date(2026, 11, 17),
                       services=services))
        assert r.exit_code == 0, r.log_summary
        assert conn.execute("SELECT COUNT(*) FROM market.macro_indicator").fetchone()[0] == 3
        # 幂等：连跑第二次行数不变
        r2 = JobRunner(MemoryStatusSink()).run(
            JobContext(job_key="macro-indicators", run_id="r-i2", window_date=dt.date(2026, 11, 17),
                       services=services))
        assert r2.exit_code == 0, r2.log_summary
        assert conn.execute("SELECT COUNT(*) FROM market.macro_indicator").fetchone()[0] == 3

    def test_indicators_failed_metric_noted(self, monkeypatch):
        """单指标源异常 → 跳过留痕进日志摘要，不阻断（NFR-03）。"""
        import pandas as _pd

        import dq.data.fetchers as f

        conn = _sqlite_macro_tables()
        fake = _pd.DataFrame({
            "indicator_code": ["PMI"], "freq": ["M"], "period": ["2026-10"],
            "indicator_name": ["官方制造业PMI"], "val": [49.6], "unit": ["%"],
            "yoy": [None], "source": ["akshare"],
        })
        fake.attrs["failed"] = ["CPI"]
        monkeypatch.setattr(f, "fetch_all", lambda s, e: fake)
        r = JobRunner(MemoryStatusSink()).run(
            JobContext(job_key="macro-indicators", run_id="r-i3", window_date=dt.date(2026, 11, 17),
                       services={"conn": conn, "dialect": "sqlite"}))
        assert r.exit_code == 0, r.log_summary
        assert "CPI" in r.log_summary
