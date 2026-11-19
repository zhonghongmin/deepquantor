"""DL-01 统一数据提供器：三档路由 + Meta 打标。

三档路由（数据策略 §5.2，全系统统一）：① 星耀数智 → ② westockdata → ③ akshare → ④ 计算派生。
每一档失败/返回空才降级到下一档；回退必须打 last_source 与取数时间；
全部源抛异常则抛 UpstreamError，禁止静默返回空帧充数（需求 C-3 / DL-01）。

验收四场景（参数化单测）：
1. 主源正常 → last_source = 主源名，fetched_at 非空；
2. 主源异常 → 走备源且 last_source = 备源名；
3. 备源返回空 → 0 行且 last_source = 实际命中源（命中 = 成功返回，空结果如实上报）；
4. 三源皆异常 → 抛 UpstreamError，不写库、不返回空帧充数。
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import pandas as pd


class UpstreamError(RuntimeError):
    """全部数据源皆异常（抛错），未命中任何源。"""


@dataclass(frozen=True)
class Meta:
    """取数元数据：实际命中源 + 取数时间（UTC，非空）。"""

    last_source: str
    fetched_at: datetime


Source = tuple[str, Callable[[], pd.DataFrame]]


def _utcnow() -> datetime:
    return datetime.now(UTC)


class UnifiedProvider:
    """按档位顺序取数；单源异常降级、成功即命中（含空结果如实上报）。"""

    def __init__(self, sources: list[Source], clock: Callable[[], datetime] | None = None):
        if not sources:
            raise ValueError("sources 不能为空：至少配置一档数据源")
        self.sources = sources
        self._clock = clock or _utcnow

    def fetch(self) -> tuple[pd.DataFrame, Meta]:
        """依序取数，返回 (DataFrame, Meta)。全部源抛异常 → UpstreamError。"""
        raised: list[str] = []
        for name, fn in self.sources:
            try:
                df = fn()
            except Exception as exc:  # noqa: BLE001 —— 降级语义要求吞单源异常并留痕
                raised.append(f"{name}: {exc}")
                continue
            if df is None:  # 防御：源返回 None 视为编程错误，按异常降级
                raised.append(f"{name}: source returned None")
                continue
            if not isinstance(df, pd.DataFrame):
                raised.append(f"{name}: source returned {type(df).__name__}")
                continue
            return df, Meta(last_source=name, fetched_at=self._clock())
        raise UpstreamError("全部数据源未命中（按序降级后仍失败）：" + "；".join(raised))


def meta_to_dict(meta: Meta) -> dict[str, Any]:
    """Meta 序列化（供落库 last_source / fetched_at 列）。"""
    return {"last_source": meta.last_source, "fetched_at": meta.fetched_at.isoformat()}
