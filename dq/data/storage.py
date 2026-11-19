"""DL-03 本地存储：五库幂等 upsert。

五库（DDL §0）：market 行情 / factor 因子 / signal 信号 / portfolio 组合 / metric 计量。
写入幂等：同一批 100 行写两次 → 行数仍为 100；(date, code) 查询唯一行；
主键冲突走 ON CONFLICT DO UPDATE，不抛未捕获异常。

双方言：postgres（psycopg2，%s 占位）与 sqlite（测试，? 占位），
两者均支持 INSERT ... ON CONFLICT (keys) DO UPDATE。
"""
from __future__ import annotations

from collections.abc import Sequence

import pandas as pd

SCHEMAS: tuple[str, ...] = ("market", "factor", "signal", "portfolio", "metric")

_DIALECT_PLACEHOLDER = {"postgres": "%s", "sqlite": "?"}


def _qualified(table: str) -> str:
    """market.day_doc 或已带点则原样。"""
    return table if "." in table else table


def _quote_ident(name: str) -> str:
    """标识符防注入：仅允许字母数字下划线与点。"""
    for part in name.split("."):
        if not part or not part.replace("_", "").isalnum():
            raise ValueError(f"非法标识符：{name!r}")
    return name


def upsert_dataframe(
    conn,
    table: str,
    df: pd.DataFrame,
    key_cols: Sequence[str],
    dialect: str = "postgres",
) -> int:
    """幂等 upsert：按 key_cols 冲突则更新非键列。返回写入行数。

    约束：df 非空列须含全部 key_cols；空帧直接返回 0（由调用方决定是否告警）。
    """
    if dialect not in _DIALECT_PLACEHOLDER:
        raise ValueError(f"不支持方言：{dialect}")
    missing = [c for c in key_cols if c not in df.columns]
    if missing:
        raise ValueError(f"键列缺失：{missing}")
    if df.empty:
        return 0

    t = _quote_ident(table)
    cols = list(df.columns)
    ph = _DIALECT_PLACEHOLDER[dialect]
    placeholders = ", ".join(ph for _ in cols)
    col_list = ", ".join(_quote_ident(c) for c in cols)
    update_cols = [c for c in cols if c not in key_cols]
    conflict = ", ".join(_quote_ident(c) for c in key_cols)
    if update_cols:
        set_clause = ", ".join(f"{_quote_ident(c)} = EXCLUDED.{_quote_ident(c)}" for c in update_cols)
        sql = (
            f"INSERT INTO {t} ({col_list}) VALUES ({placeholders}) "
            f"ON CONFLICT ({conflict}) DO UPDATE SET {set_clause}"
        )
    else:
        sql = (
            f"INSERT INTO {t} ({col_list}) VALUES ({placeholders}) "
            f"ON CONFLICT ({conflict}) DO NOTHING"
        )

    params = [tuple(None if pd.isna(v) else v for v in row) for row in df[cols].itertuples(index=False)]
    cur = conn.cursor()
    cur.executemany(sql, params)
    return len(params)
