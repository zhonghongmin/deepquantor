"""MacroSignal 输出契约（《数据策略总文档》§1.7，MC-05 总装输出）。

- to_contract_dict() 严格按 §1.7 JSON 字段输出，多余字段 = 0（MC-05 验收）。
- 契约 JSON Schema 见 contracts/macro_signal.schema.json，供引擎与展示页共用断言。
- 副标签（MC-07 未确认态）与审计信息为旁路元数据，不进契约 JSON（落点待口径补充，
  已在规格对账表登记）。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_SCHEMA_PATH = Path(__file__).parent / "contracts" / "macro_signal.schema.json"


def load_schema() -> dict:
    """加载冻结的 MacroSignal JSON Schema（共用断言）。"""
    with open(_SCHEMA_PATH, encoding="utf-8") as f:
        return json.load(f)


@dataclass
class MacroSignal:
    """宏观引擎单次运行的结构化输出（契约 §1.7 + 旁路元数据）。"""

    signal_date: str
    regime: str
    phase: str
    phase_progress: float
    money_credit: str
    equity_weight: float
    style_tilt: dict[str, str]
    asset_alloc: dict[str, float]
    confidence: str
    vintage: dict[str, Any]
    next_review: str
    factors: dict[str, int]
    money_detail: dict[str, Any]
    credit_detail: dict[str, Any]
    macro_detail: dict[str, Any]
    growth_verified: dict[str, Any]
    forecast_signals: list[dict] = field(default_factory=list)
    # ---- 旁路元数据（不进契约 JSON）----
    equity_weight_base: float = 0.0
    sub_label: str | None = None      # MC-07 未确认态副标签
    audit: dict[str, Any] = field(default_factory=dict)

    def to_contract_dict(self) -> dict:
        """§1.7 契约 JSON（字段一一对应，多余字段 = 0）。"""
        return {
            "signal_date": self.signal_date,
            "regime": self.regime,
            "phase": self.phase,
            "phase_progress": self.phase_progress,
            "money_credit": self.money_credit,
            "equity_weight": self.equity_weight,
            "style_tilt": self.style_tilt,
            "asset_alloc": self.asset_alloc,
            "confidence": self.confidence,
            "vintage": self.vintage,
            "next_review": self.next_review,
            "factors": self.factors,
            "money_detail": self.money_detail,
            "credit_detail": self.credit_detail,
            "macro_detail": self.macro_detail,
            "growth_verified": self.growth_verified,
            "forecast_signals": self.forecast_signals,
        }

    def to_db_row(self, run_id: str) -> dict:
        """signal.macro_signal 落库行（DDL 对齐）。

        confidence 数值映射见 config.CONFIDENCE_NUMERIC；s_* 列取因子评分审计。
        """
        aud = self.audit.get("factor_score", {})
        s = aud.get("s_i", {})
        return {
            "as_of": self.signal_date,
            "regime": self.regime,
            "money_credit": self.money_credit,
            "growth_s": s.get("growth"),
            "inflation_s": s.get("inflation"),
            "money_s": s.get("money"),
            "credit_s": s.get("credit"),
            "equity_weight": round(self.equity_weight, 4),
            "style_json": json.dumps(self.style_tilt, ensure_ascii=False),
            "asset_alloc_json": json.dumps(self.asset_alloc, ensure_ascii=False),
            "confidence": validate_confidence_value(self.confidence),
            "run_id": run_id,
            "signal_json": json.dumps(self.to_contract_dict(), ensure_ascii=False),
        }


def validate_confidence_value(conf: str) -> float:
    from . import config as C

    if conf not in C.CONFIDENCE_NUMERIC:
        raise ValueError(f"confidence 枚举非法：{conf}")
    return C.CONFIDENCE_NUMERIC[conf]
