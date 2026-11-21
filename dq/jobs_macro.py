"""宏观分频任务处理器（B3-a）：macro-daily / macro-monthly。

职责边界（Spec §2.1）：WorkBuddy 只触发命令行；取数、计算、策略判定全部在本 CLI 内。
接线方式：向 dq.cli 注册表注册 handler，服务对象（provider / conn / 存储表名）经
ctx.services 依赖注入，便于离线测试与生产替换。

- macro-daily：日频辅助（02:00，非交易日跳过由 jobs.yaml params + 交易日断言控制）
- macro-monthly：月度信号（cron 0 10 10-20 * *，发布窗口内取上月、取到即停）
"""
from __future__ import annotations

import datetime as dt

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
    key_cols = ("as_of",)  # DDL 唯一权威：as_of 为主键（适用期，仅保留最新已发布一期）

    month_start = (ctx.window_date.replace(day=1) - dt.timedelta(days=1)).replace(day=1)
    month_end = ctx.window_date.replace(day=1) - dt.timedelta(days=1)  # 取上月
    inp: MacroInput = fetch_range(month_start, month_end)

    signal = run_macro(inp)
    row = signal.to_db_row(ctx.run_id)  # DDL 对齐列（as_of / s_* / signal_json）
    import pandas as pd
    df = pd.DataFrame([row])
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

    # TSF_STOCK 派生：社融存量水平/同比（央行锚点口径，全量重算覆盖），供展示层直读
    import pandas as pd

    from .data.macro_input import build_tsf_stock_rows

    stock_rows = build_tsf_stock_rows(conn, table)
    n_stock = 0
    if stock_rows:
        n_stock = upsert_dataframe(
            conn, table, pd.DataFrame(stock_rows), key_cols,
            dialect=services.get("dialect", "postgres"),
        )
    return JobResult(0, f"macro-indicators 落库 {n} 行 + TSF_STOCK 派生 {n_stock} 行"
                        f"（区间 {start}~{ctx.window_date}）{note}")


def macro_aux(ctx: JobContext) -> JobResult:
    """宏观辅助指标采集（AD-10 ②区待采闭环）：NBS 新网关 + 央行官网 → macro_indicator。

    在线采集失败降级 seed JSON（随仓库全量实采，2026-11-21）；量级体检不通过拒写。
    """
    import pandas as pd

    from .data.aux_collector import collect
    from .data.aux_ingest import audit_overlap, json_to_rows, load_seed, soft_audit
    from .data.storage import upsert_dataframe

    services = ctx.services
    conn = services["conn"]
    table = services.get("macro_indicator_table", "market.macro_indicator")
    key_cols = ("indicator_code", "freq", "period")
    months = int(services.get("aux_months", 6))

    # ---- 取数：在线优先，失败降级 seed ----
    data, provenance = None, ""
    try:
        data = collect(months, source=services.get("aux_source", "nbs"), verbose=False)
        provenance = f"在线采集（nbs+pboc，{months} 期）"
    except Exception as exc:  # noqa: BLE001 —— 降级 seed，不阻断
        print(f"[macro-aux] 在线采集失败降级 seed JSON：{type(exc).__name__}: {exc}")
    if data is None:
        data = load_seed()
        provenance = "seed JSON（dq/data/seeds/macro_aux_60m.json，2026-11-21 实采）"

    # ---- 量级体检（纪律②）：与 DB 重合期对照，违例拒写 ----
    # 按 (code, field, period) 展开：M1/M2 同比对 yoy 列（val 是余额亿元）、
    # CPI/PPI/PMI 同比或指数在 val 列（fetchers 落库约定）
    from .data.aux_ingest import AUDIT_PAIRS, AUDIT_SOFT

    audit_codes = tuple({c for c, _f, _t in AUDIT_PAIRS.values()}
                        | {c for c, _f, _t in AUDIT_SOFT.values()})
    need_yoy = {c for c, f, _t in AUDIT_PAIRS.values() if f == "yoy"}
    need_yoy |= {c for c, f, _t in AUDIT_SOFT.values() if f == "yoy"}
    cur = conn.cursor()
    cur.execute(
        "SELECT indicator_code, period, val, yoy FROM market.macro_indicator "
        "WHERE freq = 'M' AND indicator_code IN %s", (audit_codes,))
    db_rows: dict[tuple[str, str, str], float] = {}
    for code, period, val, yoy in cur.fetchall():
        p = str(period)[:7]
        if val is not None:
            db_rows[(code, "val", p)] = float(val)
        if yoy is not None:
            db_rows[(code, "yoy", p)] = float(yoy)
    violations = audit_overlap(data, db_rows)
    if violations:
        return JobResult(1, "macro-aux 量级体检未通过，拒绝入库：\n  " + "\n  ".join(violations))
    warns = soft_audit(data, db_rows)

    # ---- 幂等落库（仅新码）----
    rows = json_to_rows(data)
    if not rows:
        return JobResult(0, "macro-aux 无可入库行（采集空 + seed 缺失？）")
    for r in rows:
        r["run_id"] = ctx.run_id
    n = upsert_dataframe(conn, table, pd.DataFrame(rows), key_cols,
                         dialect=services.get("dialect", "postgres"))
    note = f"；软告警 {'；'.join(warns)}" if warns else ""
    return JobResult(0, f"macro-aux 落库 {n} 行（9 个辅助码）[{provenance}]{note}")


register_job("macro-daily", macro_daily)
register_job("macro-monthly", macro_monthly)
register_job("macro-indicators", macro_indicators)
register_job("macro-aux", macro_aux)
