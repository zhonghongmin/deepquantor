"""MC-10 宏观因子评分：对基准仓位的有界微调（《数据策略总文档》§1.17）。

- 合成分 macro_factor_score = Σ w_i·s_i ∈ [-1,+1]；缺数因子 s_i=0 并标 stale，禁止插值兜底。
- equity_weight = clamp(base × (1 + κ·score), 0, 1)；κ 默认 0.10、硬上限 0.20。
- 不改 regime / money_credit / phase；极端态（滞胀+双紧）微调后不得高于该态上限。
- 可开关：关闭或全 stale 时退化为纯查表基准。
"""
from __future__ import annotations

from collections.abc import Mapping

from . import config as C


class FactorScore:
    """宏观因子评分输入与审计快照。"""

    def __init__(
        self,
        scores: Mapping[str, float | None],
        weights: Mapping[str, float] = C.FACTOR_WEIGHTS,
        kappa: float = C.KAPPA_DEFAULT,
        enabled: bool = True,
    ):
        self.enabled = enabled
        if kappa > C.KAPPA_HARD_CAP:
            raise ValueError("κ 超硬上限")
        self.kappa = kappa
        if abs(sum(weights.values()) - 1.0) > 1e-9:
            raise ValueError("Σ w_i 必须为 1")
        if any(w > C.FACTOR_WEIGHT_CAP for w in weights.values()):
            raise ValueError("单组 w_i 不得超过 0.40")
        self.weights = dict(weights)
        self.s_i: dict[str, float] = {}
        self.stale: list[str] = []
        for k in ("growth", "inflation", "money", "credit"):
            v = scores.get(k)
            if v is None:
                self.s_i[k] = 0.0
                self.stale.append(k)
            else:
                if not -1.0 <= v <= 1.0:
                    raise ValueError(f"s_i[{k}] 越界 [-1,1]")
                self.s_i[k] = float(v)
        self.score = (
            sum(self.weights[k] * self.s_i[k] for k in self.s_i) if enabled else 0.0
        )
        self.all_stale = len(self.stale) == 4
        self.active = enabled and not self.all_stale

    def adjust(self, equity_weight_base: float, regime: str, mc: str) -> tuple[float, float]:
        """返回 (equity_weight, equity_weight_base)。非 active 时原样返回基准。

        极端态上限：微调后不得高于该态查表上限（config.EXTREME_STATE_CAP）。
        """
        base = equity_weight_base
        if not self.active:
            return base, base
        w = base * (1.0 + self.kappa * self.score)
        cap = C.EXTREME_STATE_CAP.get((regime, mc))
        if cap is not None:
            w = min(w, cap)
        return min(max(w, 0.0), 1.0), base

    def audit(self) -> dict:
        """审计快照：s_i / w_i / κ / score / stale，不写入对外象限字段。"""
        return {
            "macro_factor_score": round(self.score, 6),
            "s_i": dict(self.s_i),
            "w_i": dict(self.weights),
            "kappa": self.kappa,
            "enabled": self.enabled,
            "stale": self.stale,
            "active": self.active,
        }
