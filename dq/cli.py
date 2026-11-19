"""CLI 基座：统一入口 `python -m dq.cli <job_key> --window-date YYYY-MM-DD --run-id <uuid>`。

四件套落点：
- 三档路由：job 内经 dq.data.providers.UnifiedProvider（DL-01）；
- 时点断言：dq.data.trading_day.assert_latest_trading_day（SC-03）；
- 幂等 upsert：dq.data.storage.upsert_dataframe（DL-03）；
- 状态上报：本模块 JobRunner 结束自写 task.job_instance（状态/退出码/耗时/日志摘要），不依赖平台回调。

配置纪律：cron 与时点守卫只在 jobs.yaml 与平台侧，本模块不硬编码任何时点（Spec §2.1）。
任务处理器注册表 JOBS 由各层填充（macro_daily / macro_monthly 在 B3-a 接线）。
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

# ---- 任务处理器协议 ----

@dataclass
class JobContext:
    job_key: str
    window_date: dt.date
    run_id: str
    trigger_type: str = "auto"       # auto / manual / rerun
    operator: str | None = None      # manual / rerun 留审计
    scheduled_at: dt.datetime | None = None
    services: dict[str, Any] = field(default_factory=dict)  # 注入 provider/storage/conn 等


@dataclass
class JobResult:
    exit_code: int = 0
    log_summary: str = ""


JobHandler = Callable[[JobContext], JobResult]


class JobStatusSink(Protocol):
    """状态上报接口：CLI 结束自写 task.job_instance 的抽象。"""

    def start(self, job_key: str, run_id: str, trigger_type: str,
              scheduled_at: dt.datetime | None) -> None: ...

    def finish(self, job_key: str, run_id: str, status: str, exit_code: int,
               duration_ms: int, log_summary: str, operator: str | None) -> None: ...


# ---- 注册表 ----

JOBS: dict[str, JobHandler] = {}


def register_job(job_key: str, handler: JobHandler) -> None:
    """注册任务处理器（幂等：同键覆盖）。job_key 与 task.job_def.job_key 一致。"""
    JOBS[job_key] = handler


# ---- 运行器 ----

class JobRunner:
    """包裹处理器执行并完成状态上报：running → success/failed。

    处理器抛任何异常 → 状态 failed、退出码 1、异常摘要进 log_summary，不吞不崩。
    """

    def __init__(self, sink: JobStatusSink, clock: Callable[[], dt.datetime] | None = None):
        self._sink = sink
        self._clock = clock or dt.datetime.now

    def run(self, ctx: JobContext) -> JobResult:
        started = self._clock()
        self._sink.start(ctx.job_key, ctx.run_id, ctx.trigger_type, ctx.scheduled_at)
        handler = JOBS.get(ctx.job_key)
        if handler is None:
            result = JobResult(
                exit_code=1,
                log_summary=f"未注册任务：{ctx.job_key}（可用：{', '.join(sorted(JOBS)) or '无'}）",
            )
        else:
            try:
                result = handler(ctx)
            except Exception as exc:  # noqa: BLE001 —— 异常转为 failed 状态上报
                result = JobResult(exit_code=1, log_summary=f"异常：{type(exc).__name__}: {exc}")
        duration_ms = int((self._clock() - started).total_seconds() * 1000)
        status = "success" if result.exit_code == 0 else "failed"
        self._sink.finish(ctx.job_key, ctx.run_id, status, result.exit_code,
                          duration_ms, result.log_summary, ctx.operator)
        return result


# ---- 状态上报落库（PostgreSQL，task.job_instance）----

class PostgresStatusSink:
    """直写 task.job_instance（DDL：状态/退出码/耗时/日志摘要/operator 留审计）。"""

    def __init__(self, conn):
        self._conn = conn

    def start(self, job_key, run_id, trigger_type, scheduled_at=None):
        cur = self._conn.cursor()
        cur.execute(
            "INSERT INTO task.job_instance (job_key, run_id, trigger_type, scheduled_at,"
            " started_at, status) VALUES (%s, %s, %s, %s, %s, 'running')",
            (job_key, run_id, trigger_type, scheduled_at, dt.datetime.now()),
        )
        self._conn.commit()

    def finish(self, job_key, run_id, status, exit_code, duration_ms, log_summary, operator=None):
        cur = self._conn.cursor()
        cur.execute(
            "UPDATE task.job_instance SET ended_at = %s, status = %s, exit_code = %s,"
            " duration_ms = %s, log_summary = %s, operator = %s"
            " WHERE job_key = %s AND run_id = %s AND status = 'running'",
            (dt.datetime.now(), status, exit_code, duration_ms, log_summary,
             operator, job_key, run_id),
        )
        self._conn.commit()


# ---- 内存状态上报（测试用）----

class MemoryStatusSink:
    def __init__(self):
        self.events: list[dict[str, Any]] = []

    def start(self, job_key, run_id, trigger_type, scheduled_at=None):
        self.events.append({"phase": "start", "job_key": job_key, "run_id": run_id,
                            "trigger_type": trigger_type, "status": "running"})

    def finish(self, job_key, run_id, status, exit_code, duration_ms, log_summary, operator=None):
        self.events.append({"phase": "finish", "job_key": job_key, "run_id": run_id,
                            "status": status, "exit_code": exit_code,
                            "duration_ms": duration_ms, "log_summary": log_summary,
                            "operator": operator})


# ---- 入口 ----

def new_run_id() -> str:
    return str(uuid.uuid4())


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="dq.cli", description="DeepQuantor 统一 CLI")
    p.add_argument("job_key", help="任务键，须与 task.job_def.job_key 一致")
    p.add_argument("--window-date", required=True, help="窗口日期 YYYY-MM-DD")
    p.add_argument("--run-id", default=None, help="跑批标识；缺省自动生成 uuid")
    p.add_argument("--trigger", choices=("auto", "manual", "rerun"), default="auto")
    p.add_argument("--operator", default=None, help="manual/rerun 操作人（留审计）")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    ctx = JobContext(
        job_key=args.job_key,
        window_date=dt.date.fromisoformat(args.window_date),
        run_id=args.run_id or new_run_id(),
        trigger_type=args.trigger,
        operator=args.operator,
    )
    runner = JobRunner(sink=MemoryStatusSink())  # 落库 sink 由 B3-a 按环境接线注入
    result = runner.run(ctx)
    if result.log_summary:
        print(result.log_summary)
    return result.exit_code


if __name__ == "__main__":
    sys.exit(main())
