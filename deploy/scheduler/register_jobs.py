#!/usr/bin/env python3
"""任务登记器：把 deploy/scheduler/jobs.yaml 幂等写入 task.job_def。

纪律（《环境与初始化文档》§7.1）：
  - jobs.yaml 是任务定义唯一权威
  - 登记时校验 cron 不得落在 09:30–15:00，命中退出码 2
  - 登记后回写 automation_id

TODO(M1)：随数据底座落地后实现。
"""
from __future__ import annotations

import sys


def main() -> int:
    raise NotImplementedError("任务登记待 M1 落地后实现")


if __name__ == "__main__":
    sys.exit(main())
