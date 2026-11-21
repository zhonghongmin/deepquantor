"""宏观辅助指标入库（AD-10 ②区待采清单闭环）。

数据链路：dq.data.aux_collector（NBS 新网关 + 央行官网官方源）
  → 本模块「映射 + 量级体检」→ market.macro_indicator 幂等 upsert。
在线采集失败时降级 seed JSON（dq/data/seeds/macro_aux_60m.json，2026-11-21 全量实采），
宁可缺数不灌错口径：体检不通过的指标拒绝入库（纪律②）。

新指标码（freq='M'，val=数值本身，yoy 留空）：
  PMI_ORDER 新订单指数 / PMI_PROD 生产指数 / PMI_EXP 新出口订单指数（NBS）
  PMI_NM 非制造业商务活动指数（NBS 官方源刷新）
  CPI_CORE 核心CPI同比 / CPI_FOOD 食品烟酒同比（NBS，指数-100 转同比后入库）
  CRED_HH_YOY 住户贷款余额同比 / CRED_ENT_YOY 企(事)业贷款余额同比 / CRED_GOV_YOY 政府债券存量同比（PBOC）
JSON 中已有的主序列（制造业PMI/CPI同比/PPI同比/M1/M2/社融存量同比）不重复入库，
仅作与 DB 重合期的量级体检对照。
"""
from __future__ import annotations

import json
import os

# JSON series key → (indicator_code, indicator_name, unit, source)
# 仅列需要入库的新码；未列出的 key 视为「已有主序列」，只参与体检。
AUX_CODE_MAP: dict[str, tuple[str, str, str, str]] = {
    "生产": ("PMI_PROD", "制造业PMI生产指数", "%", "nbs"),
    "新订单": ("PMI_ORDER", "制造业PMI新订单指数", "%", "nbs"),
    "新出口订单": ("PMI_EXP", "制造业PMI新出口订单指数", "%", "nbs"),
    "非制造业PMI": ("PMI_NM", "官方非制造业PMI", "%", "nbs"),
    "核心CPI": ("CPI_CORE", "核心CPI同比", "%", "nbs"),
    "食品烟酒": ("CPI_FOOD", "CPI食品烟酒同比", "%", "nbs"),
    "政府同比": ("CRED_GOV_YOY", "政府债券存量同比", "%", "pboc"),
    "居民同比": ("CRED_HH_YOY", "住户贷款余额同比", "%", "pboc"),
    "企业同比": ("CRED_ENT_YOY", "企(事)业单位贷款余额同比", "%", "pboc"),
}

# 量级体检对照（JSON key ↔ DB indicator_code，取该码的 val 与 JSON 值比对）
# tolerance 为绝对偏差上限；超限 → 拒绝入库全部新码（宁可缺数不灌错口径）。
# 第二元 field：'val' 或 'yoy' —— 实库列语义（2026-11-22 实测）：
#   M1/M2 val=余额（亿元）、CPI/PPI val=上年同月=100 指数 —— 两者的同比均在 yoy 列；
#   PMI/PMI_NM val 即指数值，直接对照。
AUDIT_PAIRS: dict[str, tuple[str, str, float]] = {
    "制造业PMI": ("PMI", "val", 0.1),
    "CPI同比": ("CPI", "yoy", 0.3),
    "PPI同比": ("PPI", "yoy", 0.3),
    "M1同比": ("M1", "yoy", 0.3),
    "M2同比": ("M2", "yoy", 0.3),
    "非制造业PMI": ("PMI_NM", "val", 0.1),
}
# 社融存量同比 vs TSF_STOCK：派生口径为央行锚点+增量倒推（E 级偏差已知），
# 只告警不拦截，写进 JobResult 日志摘要。
AUDIT_SOFT = {"社融存量同比": ("TSF_STOCK", "yoy", 1.5)}

SEED_JSON = os.path.join(os.path.dirname(__file__), "seeds", "macro_aux_60m.json")


def load_seed() -> dict:
    """读取随仓库分发的全量实采 seed（60 期，2026-11-21 NBS+PBOC）。"""
    with open(SEED_JSON, encoding="utf-8") as f:
        return json.load(f)


def json_to_rows(data: dict) -> list[dict]:
    """aux JSON → macro_indicator 行（仅 AUX_CODE_MAP 内的新码；缺失月跳过）。"""
    series = data.get("series", {})
    src_map = data.get("source_map", {})
    rows: list[dict] = []
    for key, (code, name, unit, src_default) in AUX_CODE_MAP.items():
        seq = series.get(key, {})
        source = src_map.get(key, src_default)
        for period in sorted(seq):
            v = seq.get(period)
            if period is None or v is None:
                continue
            rows.append({
                "indicator_code": code, "freq": "M", "period": period,
                "indicator_name": name, "val": float(v), "unit": unit,
                "yoy": None, "source": source,
            })
    return rows


def audit_overlap(data: dict, db_rows: dict[tuple[str, str, str], float]) -> list[str]:
    """量级体检：JSON 值 vs DB 重合期值（全重合期扫描）。返回违例描述列表（空=通过）。

    db_rows: {(indicator_code, field, period): 数值}，field ∈ {'val','yoy'}，
    由 job 侧按 AUDIT_PAIRS 涉及的列预先展开，period 形如 'YYYY-MM'。
    """
    series = data.get("series", {})
    violations: list[str] = []
    for key, (code, field, tol) in AUDIT_PAIRS.items():
        seq = series.get(key, {})
        for period, v in sorted(seq.items()):
            if v is None:
                continue
            db_v = db_rows.get((code, field, period))
            if db_v is None:
                continue
            if abs(float(v) - float(db_v)) > tol:
                violations.append(
                    f"{key}({period}) JSON={v:g} vs DB {code}.{field}={db_v:g} 偏差>{tol}")
    return violations


def soft_audit(data: dict, db_rows: dict[tuple[str, str, str], float]) -> list[str]:
    """软体检：超差仅返回告警文案，不拦截入库。"""
    series = data.get("series", {})
    warns: list[str] = []
    for key, (code, field, tol) in AUDIT_SOFT.items():
        seq = series.get(key, {})
        for period, v in sorted(seq.items()):
            if v is None:
                continue
            db_v = db_rows.get((code, field, period))
            if db_v is None:
                continue
            if abs(float(v) - float(db_v)) > tol:
                warns.append(
                    f"{key}({period}) JSON={v:g} vs {code}.{field}={db_v:g}（派生口径偏差，已知 E 级）")
    return warns
