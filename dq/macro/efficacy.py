"""MC-08 货币信用信号有效性离线评估（《数据策略总文档》§1.15.1 离线验证）。

- episode = 「首次连续 3 期双宽」，episode 去重（本次双宽段只触发一次）。
- lead_window 分层：1-3m / 3-6m / 6-12m；验证只用未来已发布数据（vintage 一致，
  每期仅一条首发记录，不取修订值）。
- 命中率 = 条件命中率，必须与无条件基准对比并给显著性（分块 bootstrap，块长 = 窗口
  月数，处理窗口重叠）；报告含 episode 数、置信区间与样本外命中率。
- 失效降级：失效条件触发或样本不足 → 结论降为「参考级」。
- 前视隔离：本模块为纯离线评估，物理隔离于 job-macro，零写回 macro_signal。
"""
from __future__ import annotations

import math
import random
from collections.abc import Sequence
from dataclasses import dataclass, field

LEAD_WINDOWS = ("1-3m", "3-6m", "6-12m")
WINDOW_MONTHS = {"1-3m": 3, "3-6m": 6, "12m": 12, "6-12m": 12}
MIN_EPISODES = 3          # 样本不足 → 参考级
BOOTSTRAP_N = 1000
BLOCK_MONTHS = 3          # 分块长度（月），处理窗口重叠


@dataclass
class McPeriod:
    """货币信用历史期（在线判定快照，vintage 一致）。"""
    period: str            # YYYY-MM
    money_credit: str
    invalid_flags: list[str] = field(default_factory=list)  # 失效条件标记


@dataclass
class GrowthOutcome:
    """未来增长结果（已发布值，禁止修订）；warm_up = 窗口末端是否扩张回暖。"""
    period: str            # YYYY-MM
    warm_up: bool          # 该期增长是否回暖（如 PMI 3 月均 > 50）
    published_at: str      # 发布日 YYYY-MM-DD（不得晚于评估基准日）


def find_episodes(history: Sequence[McPeriod]) -> list[int]:
    """「首次连续 3 期双宽」触发点（索引），episode 去重：同一段双宽只触发一次。"""
    episodes: list[int] = []
    run = 0
    in_episode = False
    for i, p in enumerate(history):
        if p.money_credit == "双宽":
            run += 1
            if run >= 3 and not in_episode:
                episodes.append(i)
                in_episode = True
        else:
            run = 0
            in_episode = False
    return episodes


def _wilson_ci(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, center - half), min(1.0, center + half))


def _block_bootstrap_pvalue(
    hits: list[bool], baseline: float, rng: random.Random
) -> float:
    """分块 bootstrap：H0 = 命中率等于无条件基准。块长 = BLOCK_MONTHS 处理窗口重叠。"""
    n = len(hits)
    if n == 0:
        return 1.0
    blocks = [hits[i:i + BLOCK_MONTHS] for i in range(0, n, BLOCK_MONTHS)]
    obs = sum(hits) / n
    extreme = 0
    for _ in range(BOOTSTRAP_N):
        sample: list[bool] = []
        while len(sample) < n:
            sample.extend(rng.choice(blocks))
        ph = sum(sample) / n
        if abs(ph - baseline) >= abs(obs - baseline):
            extreme += 1
    return extreme / BOOTSTRAP_N


def evaluate_signal_efficacy(
    history: Sequence[McPeriod],
    outcomes: Sequence[GrowthOutcome],
    *,
    seed: int = 42,
    outcome_map: dict[str, GrowthOutcome] | None = None,
) -> dict:
    """mc_to_growth 离线有效性评估 → signal_efficacy 报告结构。

    前视隔离：触发期 t 的判定快照只含 t 时点已发布数据（调用方保证）；
    验证取 t 之后窗口的已发布 outcome；本函数零写回 macro_signal。
    """
    by_period = outcome_map or {o.period: o for o in outcomes}
    if len(by_period) != len(outcomes):
        raise ValueError("outcome period 重复：vintage 必须唯一（首发口径）")

    episodes = find_episodes(history)
    valid_eps = [i for i in episodes if not history[i].invalid_flags]
    invalid_eps = [i for i in episodes if history[i].invalid_flags]

    windows: dict[str, dict] = {}
    for w in LEAD_WINDOWS:
        k = WINDOW_MONTHS[w]
        hits: list[bool] = []
        for i in valid_eps:
            trigger = history[i].period
            target_period = _shift_month(trigger, k)
            oc = by_period.get(target_period)
            if oc is None:
                continue  # 未来数据尚未发布：跳过，不虚构
            hits.append(bool(oc.warm_up))
        n = len(hits)
        k_hit = sum(hits)
        baseline = (
            sum(1 for o in outcomes if o.warm_up) / len(outcomes) if outcomes else 0.0
        )
        rng = random.Random(seed + k)
        p_value = _block_bootstrap_pvalue(hits, baseline, rng) if n else 1.0
        lo, hi = _wilson_ci(k_hit, n)
        # 样本外：后 1/3 episode 命中率（滚动切分，前 2/3 视为样本内）
        oos_n = max(1, n // 3) if n >= MIN_EPISODES else 0
        oos_hits = hits[-oos_n:] if oos_n else []
        windows[w] = {
            "n_episodes": n,
            "hit_rate": round(k_hit / n, 4) if n else None,
            "baseline": round(baseline, 4),
            "ci95": [round(lo, 4), round(hi, 4)],
            "p_value": p_value,
            "out_of_sample": {
                "n": len(oos_hits),
                "hit_rate": round(sum(oos_hits) / len(oos_hits), 4) if oos_hits else None,
            },
        }

    # 结论：任一窗口显著优于基准且样本充足 → 有效；否则参考级
    effective = any(
        wv["n_episodes"] >= MIN_EPISODES
        and wv["hit_rate"] is not None
        and wv["hit_rate"] > wv["baseline"]
        and wv["p_value"] < 0.05
        for wv in windows.values()
    )
    verdict = "有效" if effective else "参考级"
    if invalid_eps:
        verdict = "参考级"  # 失效条件触发 → 降级
    return {
        "signal_id": "mc_to_growth",
        "definition": "首次连续 3 期双宽 → 增长回暖",
        "lead_windows": windows,
        "n_episodes_total": len(episodes),
        "n_episodes_invalid": len(invalid_eps),
        "verdict": verdict,
        "hit_rate_status": "valid" if effective else "pending",
        "note": "离线评估只读，不写回 macro_signal（§1.15.1 前视隔离）",
    }


def _shift_month(period: str, months: int) -> str:
    y, m = int(period[:4]), int(period[5:7])
    total = y * 12 + (m - 1) + months
    return f"{total // 12:04d}-{total % 12 + 1:02d}"
