#!/usr/bin/env python3
"""线上 → 线下：用户注册增量回传（本期不启用，随中期免费吸流立项）。

约束：幂等键 = batch_id + as_of 或 updated_at 水位；只回传用户注册与账号变更，
不反向同步分析结果（反向连接被打破即失去隔离）。

TODO(中期 CL-01)：届时启用。
"""
from __future__ import annotations

import sys


def main() -> int:
    raise NotImplementedError("本期不启用，随中期 CL-01 立项")


if __name__ == "__main__":
    sys.exit(main())
