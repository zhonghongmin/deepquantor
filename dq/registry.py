"""任务注册表：独立模块，避免 `python -m dq.cli` 下 __main__ 与 dq.cli 双实例导致注册落空。

不 import dq.cli（避免循环）；JobHandler 以 TYPE_CHECKING 字符串注解引用。
"""
from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .cli import JobContext, JobResult

JobHandler = Callable[["JobContext"], "JobResult"]

JOBS: dict[str, JobHandler] = {}


def register_job(job_key: str, handler: JobHandler) -> None:
    """注册任务处理器（幂等：同键覆盖）。job_key 与 task.job_def.job_key 一致。"""
    JOBS[job_key] = handler
