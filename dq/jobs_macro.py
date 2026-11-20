"""宏观分频任务处理器（B3-a）：macro-daily / macro-monthly。

职责边界（Spec §2.1）：WorkBuddy 只触发命令行；取数、计算、策略判定全部在本 CLI 内。
接线方式：向 dq.cli 注册表注册 handler，服务对象（provider / conn / 存储表名）经
ctx.services 依赖注入，便于离线测试与生产替换。

- macro-daily：日频辅助（02:00，非交易日跳过由 jobs.yaml params + 交易日断言控制）
- macro-monthly：月度信号（cron 0 10 10-20 * *，发布窗口内取上月、取到即停）
"""
from __future__ import annotations

import datetime as dt
import json

from .cli import JobContext, JobResult, register_job
from .data.increment import incremental
from .macro import MacroInput, run_macro


def macro_monthly(ctx: JobContext) -> JobResult:
    """月频：发布窗口内取上月数据 → 跑宏观引擎 → 幂等落库 signal.macro_signal。"""
    services = ctx.services
    # 发布窗口守卫：仅在 jobs.yaml 配置的窗口日内产出（月频窗口 10–20 日）
    day = ctx.window_date.day
    window = services.get("publish_window", range(10, 21))
    if day not in window:
        return JobResult(0, f"今日 {day} 日不在发布窗口，跳过（取到即停）")

    conn = services["conn"]
    fetch_range = services["fetch_range"]    # (start, end) -> MacroInput 所需数据
    table = services.get("table", "signal.macro_signal")
    key_cols = ("signal_date",)

    month_start = (ctx.window_date.replace(day=1) - dt.timedelta(days=1)).replace(day=1)
    month_end = ctx.window_date.replace(day=1) - dt.timedelta(days=1)  # 取上月
    inp: MacroInput = fetch_range(month_start, month_end)

    signal = run_macro(inp)
    row = signal.to_contract_dict()
    import pandas as pd
    df = pd.DataFrame([{k: json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v
                        for k, v in row.items()}])
    from .data.storage import upsert_dataframe
    dialect = services.get("dialect", "postgres")
    n = upsert_dataframe(conn, table, df, key_cols, dialect=dialect)
    return JobResult(0, f"macro-monthly 落库 {n} 行：{ctx.window_date} 期 {inp.signal_date}")


def macro_daily(ctx: JobContext) -> JobResult:
    """日频辅助：增量采集辅助数据 + 非交易日跳过。"""
    services = ctx.services
    if services.get("skip_non_trading_day") and not services["is_trading_day"](ctx.window_date):
        return JobResult(0, f"{ctx.window_date} 非交易日，跳过")
    conn = services["conn"]
    fetch_range = services["fetch_range"]
    table = services.get("daily_table", "market.macro_daily")
    n, start = incremental(conn, table, fetch_range, ctx.window_date,
                           ("date", "code"), ctx.window_date - dt.timedelta(days=7),
                           dialect=services.get("dialect", "postgres"))
    return JobResult(0, f"macro-daily 增量起点 {start}，写入 {n} 行")


def macro_indicators(ctx: JobContext) -> JobResult:
    """月频宏观指标批量采集（DL-01）：近 N 月区间取数 → 幂等落库 market.macro_indicator。

    接口每次返回全量历史，增量语义由「区间起点 + 幂等 upsert」保证；
    单指标源异常跳过不阻断（NFR-03），全部异常抛 UpstreamError。
    """
    from .data.fetchers import fetch_all, minus_months
    from .data.storage import upsert_dataframe

    services = ctx.services
    conn = services["conn"]
    months = int(services.get("recent_months", 25))
    start = minus_months(ctx.window_date, months)
    df = fetch_all(start, ctx.window_date)
    table = services.get("macro_indicator_table", "market.macro_indicator")
    key_cols = ("indicator_code", "freq", "period")
    n = upsert_dataframe(conn, table, df, key_cols, dialect=services.get("dialect", "postgres"))
    failed = df.attrs.get("failed", [])
    note = f"，源异常跳过 {failed}" if failed else ""
    return JobResult(0, f"macro-indicators 落库 {n} 行（区间 {start}~{ctx.window_date}）{note}")


register_job("macro-daily", macro_daily)
register_job("macro-monthly", macro_monthly)
register_job("macro-indicators", macro_indicators)
