"""DL-04 增量更新与区间回补。

增量：库内最新日期 T-1 → 拉取起点 = T（next_start），T-1 不重复写；
回补：指定 [start, end] 区间拉取落库，同区间连跑两次第二次新增 0 行（幂等由 DL-03 保证）。
"""
from __future__ import annotations

import datetime as dt
from collections.abc import Callable

FetchRange = Callable[[dt.date, dt.date], object]  # 返回 pandas DataFrame


def latest_date(conn, table: str, date_col: str = "date") -> dt.date | None:
    """查询库内最新日期；空表返回 None。"""
    cur = conn.cursor()
    cur.execute(f"SELECT MAX({date_col}) FROM {_safe(table)}")
    row = cur.fetchone()
    if row is None or row[0] is None:
        return None
    return row[0] if isinstance(row[0], dt.date) else dt.date.fromisoformat(str(row[0])[:10])


def next_start(latest: dt.date | None, default_start: dt.date) -> dt.date:
    """增量起点：库内最新 T-1 → 返回 T（不重复写 T-1）；空库 → default_start。"""
    return latest + dt.timedelta(days=1) if latest else default_start


def _safe(name: str) -> str:
    for part in name.split("."):
        if not part or not part.replace("_", "").isalnum():
            raise ValueError(f"非法标识符：{name!r}")
    return name


def backfill(
    conn,
    table: str,
    fetch_range: FetchRange,
    start: dt.date,
    end: dt.date,
    key_cols: tuple[str, ...],
    date_col: str = "date",
    dialect: str = "postgres",
) -> int:
    """区间回补：拉取 [start, end] 并幂等落库，返回本次 upsert 行数。"""
    if start > end:
        return 0
    df = fetch_range(start, end)
    if df.empty:
        return 0
    # 懒导入避免循环依赖
    from .storage import upsert_dataframe

    return upsert_dataframe(conn, table, df, key_cols=key_cols, dialect=dialect)


def incremental(conn, table: str, fetch_range: FetchRange, end: dt.date, key_cols: tuple[str, ...],
                default_start: dt.date, date_col: str = "date", dialect: str = "postgres") -> tuple[int, dt.date]:
    """增量更新：按最新日期续拉至 end。返回 (upsert 行数, 实际拉取起点)。"""
    start = next_start(latest_date(conn, table, date_col), default_start)
    if start > end:
        return 0, start  # 已是最新，无新增
    n = backfill(conn, table, fetch_range, start, end, key_cols, date_col, dialect)
    return n, start
