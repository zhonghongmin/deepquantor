"""DL-03 幂等存储（SQLite 实测）+ DL-04 增量与回补。"""
from __future__ import annotations

import datetime as dt

import pandas as pd
import pytest

from dq.data.increment import backfill, incremental, latest_date, next_start
from dq.data.storage import upsert_dataframe


@pytest.fixture()
def conn():
    import sqlite3
    c = sqlite3.connect(":memory:")
    c.execute("ATTACH ':memory:' AS market")  # SQLite 模拟 PG schema
    c.execute("CREATE TABLE market.day_doc (date TEXT, code TEXT, close REAL,"
              " PRIMARY KEY (date, code))")
    return c


def _df(dates, closes):
    return pd.DataFrame({"date": [d.isoformat() for d in dates], "code": ["000001"] * len(dates),
                         "close": closes})


class TestUpsertIdempotent:
    def test_100_rows_twice_still_100(self, conn):
        dates = [dt.date(2026, 1, 1) + dt.timedelta(days=i) for i in range(100)]
        df = _df(dates, range(100))
        assert upsert_dataframe(conn, "market.day_doc", df, ("date", "code"), dialect="sqlite") == 100
        upsert_dataframe(conn, "market.day_doc", df, ("date", "code"), dialect="sqlite")
        assert conn.execute("SELECT COUNT(*) FROM market.day_doc").fetchone()[0] == 100

    def test_key_query_unique(self, conn):
        upsert_dataframe(conn, "market.day_doc", _df([dt.date(2026, 1, 1)], [9.9]),
                         ("date", "code"), dialect="sqlite")
        rows = conn.execute(
            "SELECT * FROM market.day_doc WHERE date='2026-01-01' AND code='000001'"
        ).fetchall()
        assert len(rows) == 1

    def test_conflict_updates_no_raise(self, conn):
        upsert_dataframe(conn, "market.day_doc", _df([dt.date(2026, 1, 1)], [1.0]),
                         ("date", "code"), dialect="sqlite")
        upsert_dataframe(conn, "market.day_doc", _df([dt.date(2026, 1, 1)], [2.0]),
                         ("date", "code"), dialect="sqlite")
        assert conn.execute("SELECT close FROM market.day_doc").fetchone()[0] == 2.0

    def test_empty_frame_returns_zero(self, conn):
        assert upsert_dataframe(conn, "market.day_doc", _df([], []),
                                ("date", "code"), dialect="sqlite") == 0

    def test_missing_key_cols_raises(self, conn):
        with pytest.raises(ValueError):
            upsert_dataframe(conn, "market.day_doc", pd.DataFrame({"close": [1.0]}),
                             ("date", "code"), dialect="sqlite")

    def test_bad_dialect_raises(self, conn):
        with pytest.raises(ValueError):
            upsert_dataframe(conn, "market.day_doc", _df([dt.date(2026, 1, 1)], [1.0]),
                             ("date", "code"), dialect="mysql")

    def test_bad_identifier_raises(self, conn):
        with pytest.raises(ValueError):
            upsert_dataframe(conn, "market; DROP TABLE x", _df([dt.date(2026, 1, 1)], [1.0]),
                             ("date", "code"), dialect="sqlite")

    def test_none_becomes_null(self, conn):
        df = pd.DataFrame({"date": ["2026-01-01"], "code": ["000001"], "close": [None]})
        upsert_dataframe(conn, "market.day_doc", df, ("date", "code"), dialect="sqlite")
        assert conn.execute("SELECT close FROM market.day_doc").fetchone()[0] is None


class TestIncrementBackfill:
    def test_latest_date_and_next_start(self, conn):
        upsert_dataframe(conn, "market.day_doc", _df([dt.date(2026, 1, 1)], [1.0]),
                         ("date", "code"), dialect="sqlite")
        latest = latest_date(conn, "market.day_doc")
        assert latest == dt.date(2026, 1, 1)
        # 库内最新 T-1 → 增量起点 = T（不重复写 T-1）
        assert next_start(latest, dt.date(2025, 1, 1)) == dt.date(2026, 1, 2)

    def test_empty_table_uses_default_start(self, conn):
        assert next_start(None, dt.date(2026, 1, 1)) == dt.date(2026, 1, 1)

    def test_backfill_30_days_no_holes_and_idempotent(self, conn):
        start = dt.date(2026, 1, 5)
        dates = [start + dt.timedelta(days=i) for i in range(30)]
        fetch = lambda s, e: _df([d for d in dates if s <= d <= e], [float(i) for i, d in enumerate(dates) if s <= d <= e])  # noqa: E731
        n1 = backfill(conn, "market.day_doc", fetch, start, dates[-1], ("date", "code"), dialect="sqlite")
        assert n1 == 30
        n2 = backfill(conn, "market.day_doc", fetch, start, dates[-1], ("date", "code"), dialect="sqlite")
        assert n2 == 30  # 同区间连跑两次 → 第二次新增 0 行（upsert 全部命中）
        assert conn.execute("SELECT COUNT(*) FROM market.day_doc").fetchone()[0] == 30
        assert latest_date(conn, "market.day_doc") == dates[-1]

    def test_incremental_no_duplicate_t_minus_1(self, conn):
        t1 = dt.date(2026, 1, 1)
        upsert_dataframe(conn, "market.day_doc", _df([t1], [1.0]), ("date", "code"), dialect="sqlite")
        def fetch(s, e):
            want = [d for d in (t1, dt.date(2026, 1, 2)) if s <= d <= e]
            return _df(want, [1.0, 2.0][: len(want)])

        n, start = incremental(conn, "market.day_doc", fetch, dt.date(2026, 1, 2),
                               ("date", "code"), dt.date(2026, 1, 1), dialect="sqlite")
        assert start == dt.date(2026, 1, 2) and n == 1
        assert conn.execute("SELECT COUNT(*) FROM market.day_doc").fetchone()[0] == 2

    def test_incremental_already_fresh(self, conn):
        d = dt.date(2026, 1, 2)
        upsert_dataframe(conn, "market.day_doc", _df([d], [1.0]), ("date", "code"), dialect="sqlite")
        n, start = incremental(conn, "market.day_doc", lambda s, e: pytest.fail("不应取数"),
                               d, ("date", "code"), dt.date(2026, 1, 1), dialect="sqlite")
        assert n == 0 and start == dt.date(2026, 1, 3)

    def test_backfill_empty_range(self, conn):
        assert backfill(conn, "market.day_doc", lambda s, e: _df([], []),
                        dt.date(2026, 2, 1), dt.date(2026, 1, 1), ("date", "code"), dialect="sqlite") == 0
