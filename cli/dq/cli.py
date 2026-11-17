"""dq.cli —— 统一 CLI 入口。

约定（《环境与初始化文档》§7.1）：
    python -m dq.cli <job_key> --window-date YYYY-MM-DD --run-id <uuid>

纪律：
  - 平台（WorkBuddy 自动化任务）只负责按 cron 发一条命令行，**不含任何业务逻辑**
  - 业务规则全部在 CLI 内，保证「调度触发 = 命令行执行」
  - 启动时断言不在交易时段 09:30–15:00（时点禁令，命中退出码 2）
  - 结束自行写 task.job_instance（状态 / 退出码 / 耗时 / 日志摘要），不依赖平台回调
  - 状态回写前不产生任何副作用输出
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, time

# 交易时段禁令（C-1 / SC-02）
TRADING_START = time(9, 30)
TRADING_END = time(15, 0)

EXIT_OK = 0
EXIT_BLOCKED = 2  # 时点禁令：启动落在交易时段
EXIT_NOT_IMPLEMENTED = 3  # 任务未注册（尚未实现）


def _assert_outside_trading_hours(now: datetime | None = None) -> None:
    """启动时断言不在交易时段。命中则退出码 2。"""
    now = now or datetime.now()
    if TRADING_START <= now.time() <= TRADING_END:
        print(
            f"[BLOCKED] 交易时段 09:30–15:00 内禁止启动 CLI（当前 {now:%H:%M:%S}）",
            file=sys.stderr,
        )
        sys.exit(EXIT_BLOCKED)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="dq.cli", description="量化选股系统 · 线下 CLI")
    ap.add_argument(
        "job_key",
        help="任务键（须已登记于 task.job_def / deploy/scheduler/jobs.yaml）",
    )
    ap.add_argument("--window-date", required=True, help="窗口日期 YYYY-MM-DD")
    ap.add_argument("--run-id", required=True, help="运行 ID（uuid）")
    ap.add_argument("--dry-run", action="store_true", help="只校验参数与时点，不实际执行")
    a = ap.parse_args(argv)

    _assert_outside_trading_hours()

    # TODO(M1)：按 job_key 分发到对应 collector 任务
    # 分发方式须为注册表（job_key → 任务函数），禁止在核心写 if/else 分支
    print(
        f"[NOT_IMPLEMENTED] job_key={a.job_key!r} 尚未注册。"
        "任务分发表待 M1 数据底座落地后实现。",
        file=sys.stderr,
    )
    return EXIT_NOT_IMPLEMENTED


if __name__ == "__main__":
    sys.exit(main())
