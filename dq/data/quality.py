"""DL-05 数据质量校验：完整性 / 时效性 / 异常值三类，阈值可配置。

验收：1 处缺口 + 1 处滞后 + 1 处越界 → 恰好 3 条告警且 rule_type 一一对应；
数据全合规 → 0 条；改阈值 → 同一数据判定随之改变。

注：《数据策略总文档》§4.5 现行为口径对照表（未含三类规则细则），
本模块按需求文档 DL-05 验收行实现三类通用规则，阈值外置 config。
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Alert:
    rule_type: str   # completeness / timeliness / outlier
    target: str      # 数据项编码或表名
    detail: str


@dataclass
class QualityConfig:
    """三类阈值，全部可配置（改配置即改判定）。"""

    expected_dates: list[str] = field(default_factory=list)   # 完整性：期望日期清单（ISO）
    max_lag_days: int = 1                                     # 时效性：最新日期距期望 ≤ N 天
    expected_latest: str | None = None                        # 时效性：期望最新交易日
    bounds: dict[str, tuple[float, float]] = field(default_factory=dict)  # 异常值：列 → [min, max]


def check_completeness(dates: set[str], expected: list[str], target: str) -> list[Alert]:
    """完整性：期望日期清单中缺失的日期 → 每缺口 1 条告警。"""
    missing = sorted(set(expected) - set(dates))
    return [Alert("completeness", target, f"缺口日期 {d}") for d in missing]


def check_timeliness(latest: dt.date | None, cfg: QualityConfig, target: str) -> list[Alert]:
    """时效性：库内最新日期滞后于期望交易日超过 max_lag_days → 告警。"""
    if cfg.expected_latest is None:
        return []
    exp = dt.date.fromisoformat(cfg.expected_latest)
    if latest is None:
        return [Alert("timeliness", target, "库内无数据，无法判定时效")]
    lag = (exp - latest).days
    if lag > cfg.max_lag_days:
        return [Alert("timeliness", target, f"最新 {latest} 滞后期望 {exp} {lag} 天 > 阈值 {cfg.max_lag_days}")]
    return []


def check_outliers(rows: dict[str, float], cfg: QualityConfig, target: str) -> list[Alert]:
    """异常值：数值越界（bounds 外）→ 每处 1 条告警。rows：列名 → 值。"""
    alerts: list[Alert] = []
    for col, bounds in cfg.bounds.items():
        if col not in rows:
            continue
        v = rows[col]
        if v is None:
            continue
        lo, hi = bounds
        if not (lo <= v <= hi):
            alerts.append(Alert("outlier", target, f"{col}={v} 越界 [{lo}, {hi}]"))
    return alerts


def run_quality_checks(
    dates: set[str],
    latest: dt.date | None,
    latest_row: dict[str, float],
    cfg: QualityConfig,
    target: str,
) -> list[Alert]:
    """三类校验总入口，按 完整性→时效性→异常值 顺序产出告警。"""
    alerts: list[Alert] = []
    if cfg.expected_dates:
        alerts += check_completeness(dates, cfg.expected_dates, target)
    alerts += check_timeliness(latest, cfg, target)
    alerts += check_outliers(latest_row, cfg, target)
    return alerts
