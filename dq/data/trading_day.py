"""时点断言（SC-03）：取数后断言最新交易日符合预期，不符重试（N 次可配）后告警。

验收：滞后 1 日 + 重试上限 3 → 恰好重试 3 次后写 1 条告警，状态 failed；
数据正常 → 重试 0 次、状态 done。
"""
from __future__ import annotations

import datetime as dt
from collections.abc import Callable

from .quality import Alert


def assert_latest_trading_day(
    fetch_latest: Callable[[], dt.date | None],
    expected: dt.date,
    max_retry: int = 3,
    alert_sink: Callable[[Alert], None] | None = None,
) -> bool:
    """断言最新交易日 == expected；不符重试至多 max_retry 次，仍不符写 1 条告警。

    返回是否通过（True=done / False=failed，由调用方映射任务状态）。
    重试语义：每次尝试重新取数；不通过的总尝试次数 = 1 + max_retry。
    """
    for _ in range(1 + max_retry):
        latest = fetch_latest()
        if latest is not None and latest == expected:
            return True
    if alert_sink is not None:
        alert_sink(Alert(
            "timeliness", "trading_day_assert",
            f"最新交易日 {latest} != 期望 {expected}，重试 {max_retry} 次后仍不符",
        ))
    return False
