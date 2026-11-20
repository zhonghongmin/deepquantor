"""dq/data/macro_input 单测：指标表 → MacroInput 组装 + 存量重构数学（SQLite，不联网）。"""
from __future__ import annotations

import datetime as dt

import pytest

from dq.data.macro_input import (
    build_macro_input,
    loan_yoy_extra,
    tsf_stock_levels,
    tsf_stock_yoy,
)
from dq.macro import run_macro


def _conn():
    import sqlite3

    conn = sqlite3.connect(":memory:")
    cur = conn.cursor()
    cur.execute("ATTACH ':memory:' AS market")
    cur.execute("ATTACH ':memory:' AS signal")
    cur.execute("CREATE TABLE market.macro_indicator ("
                "indicator_code TEXT, freq TEXT, period TEXT, indicator_name TEXT,"
                " val REAL, unit TEXT, yoy REAL, source TEXT,"
                " PRIMARY KEY (indicator_code, freq, period))")
    cur.execute("CREATE TABLE signal.macro_signal (as_of TEXT, regime TEXT,"
                " PRIMARY KEY (as_of))")
    conn.commit()
    return conn


def _seed(conn, rows):
    conn.executemany(
        "INSERT INTO market.macro_indicator (indicator_code, freq, period,"
        " indicator_name, val, unit, yoy, source) VALUES (?,?,?,?,?,?,?,?)",
        rows)
    conn.commit()


def _month_range(start: str, n: int) -> list[str]:
    out = []
    y, mo = int(start[:4]), int(start[5:7])
    for i in range(n):
        idx = (y * 12 + mo - 1 + i)
        out.append(f"{idx // 12}-{idx % 12 + 1:02d}")
    return out


def _seed_series(conn):
    """28 个月序列（2024-07 起，保证同比多增有足额基期）：PMI 上行 / CPI 温和 / PPI 下行 / M2 平 / M1 活化 / 社融+信贷。"""
    months = _month_range("2024-07", 28)
    rows = []
    for i, m in enumerate(months):
        rows.append(("PMI", "M", m, "官方制造业PMI", 49.5 + i * 0.2, "%", None, "akshare"))
        rows.append(("CPI", "M", m, "CPI当月值", 100.0, "%", 0.4 + i * 0.02, "akshare"))
        rows.append(("PPI", "M", m, "PPI当月值", 100.0, "%", 2.0 - i * 0.05, "akshare"))
        rows.append(("M1", "M", m, "M1", 1e5, "亿元", 3.0 + i * 0.1, "akshare"))
        rows.append(("M2", "M", m, "M2", 3e5, "亿元", 7.0 + i * 0.02, "akshare"))
        rows.append(("TSF", "M", m, "社会融资规模增量", 20000.0 + i, "亿元", None, "akshare"))
        rows.append(("CREDIT", "M", m, "新增人民币贷款", 8000.0 + i * 50, "亿元", None, "akshare"))
    rows.append(("GDPCUM", "Q", "2026-Q3", "GDP累计值", "亿元", 1071071.2, 4.6, "akshare"))
    _seed(conn, rows)


class TestTsfStock:
    def test_anchor_math(self):
        """锚点前倒推 / 后正推：增量恒定 → 存量线性增长 → 同比随时间单调递减。"""
        months = _month_range("2024-01", 40)  # 覆盖锚点 2026-10 前后
        incr = {m: 10000.0 for m in months}
        levels = tsf_stock_levels(incr)
        assert levels["2026-10"] == pytest.approx(4_691_600.0)
        assert levels["2026-09"] == pytest.approx(4_691_600.0 - 10000.0)
        yoy = tsf_stock_yoy(levels)
        vals = [yoy[m] for m in sorted(yoy)]
        assert vals == sorted(vals, reverse=True)  # 存量线性增长 → 同比单调递减

    def test_yoy_twelve_month_window(self):
        months = _month_range("2025-06", 17)
        incr = {m: 20000.0 for m in months}
        yoy = tsf_stock_yoy(tsf_stock_levels(incr))
        # 2026-10 = 锚点；2025-10 = 锚点 − 12 个月增量
        expected = 4_691_600.0 / (4_691_600.0 - 12 * 20000.0) - 1
        assert yoy["2026-10"] == pytest.approx(expected * 100)


class TestLoanYoy:
    def test_extra_ratio(self):
        incr = {"2025-06": 8000.0, "2026-06": 8800.0,
                "2025-05": 7000.0, "2026-05": 7000.0}
        out = loan_yoy_extra(incr)
        assert out["2026-06"] == pytest.approx(10.0)
        assert out["2026-05"] == pytest.approx(0.0)

    def test_nonpositive_base_skipped(self):
        out = loan_yoy_extra({"2025-01": -500.0, "2026-01": 9000.0})
        assert "2026-01" not in out


class TestBuildMacroInput:
    def _build(self, conn, month_end=dt.date(2026, 10, 31)):
        return build_macro_input(conn, "sqlite", month_end)

    def test_full_pipeline(self):
        """指标表 → MacroInput → run_macro 全链路（SQLite）。"""
        conn = _conn()
        _seed_series(conn)
        inp = self._build(conn)
        assert inp.signal_date == "2026-10-31"
        assert len(inp.pmi_series) >= 6 and inp.pmi_series[-1] > inp.pmi_series[0]
        assert inp.gdp_yoy == pytest.approx(4.6)
        assert inp.prev_regime is None
        signal = run_macro(inp)
        assert signal.regime in ("复苏", "过热", "滞胀", "衰退")

    def test_prev_regime_threaded(self):
        conn = _conn()
        _seed_series(conn)
        conn.execute("INSERT INTO signal.macro_signal (as_of, regime) VALUES (?,?)",
                     ("2026-09-30", "衰退"))
        conn.commit()
        inp = self._build(conn)
        assert inp.prev_regime == "衰退"

    def test_insufficient_pmi_raises(self):
        conn = _conn()
        _seed_series(conn)
        conn.execute("DELETE FROM market.macro_indicator WHERE indicator_code='PMI'"
                     " AND period <= '2026-08'")
        conn.commit()
        with pytest.raises(ValueError, match="PMI"):
            self._build(conn)

    def test_cutoff_excludes_future(self):
        """组装只读截至月的数据：未来期不进入序列。"""
        conn = _conn()
        _seed_series(conn)
        inp = build_macro_input(conn, "sqlite", dt.date(2026, 6, 30))
        assert inp.pmi_month <= "2026-06"


class TestTsfStockDerived:
    def test_build_tsf_stock_rows(self):
        """TSF 全量增量 → TSF_STOCK 派生行：水平=锚点倒推/正推，yoy=同比；<13 期返回空。"""
        from dq.data.macro_input import AFRE_ANCHOR_MONTH, build_tsf_stock_rows

        conn = _conn()
        months = _month_range("2025-01", 22)
        base = 30_000.0
        _seed(conn, [("TSF", "M", m, "社会融资规模增量", base + i * 100, "亿元", None, "akshare")
                     for i, m in enumerate(months)])
        rows = build_tsf_stock_rows(conn)
        assert rows and all(r["indicator_code"] == "TSF_STOCK" for r in rows)
        by_p = {r["period"]: r for r in rows}
        # 锚点月水平 = 央行锚点
        assert by_p[AFRE_ANCHOR_MONTH]["val"] == 4_691_600.0
        # 同比月有 yoy（期数 ≥13 即可算 12 期前同比）
        assert by_p[AFRE_ANCHOR_MONTH]["yoy"] is not None
        # 期数不足 13 → 空
        conn2 = _conn()
        _seed(conn2, [("TSF", "M", m, "社会融资规模增量", base, "亿元", None, "akshare")
                      for m in _month_range("2026-01", 5)])
        assert build_tsf_stock_rows(conn2) == []
