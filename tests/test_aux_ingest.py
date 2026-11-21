"""macro-aux 辅助指标入库测试（离线，不连库）。"""
import json
import os

import pytest

from dq.data.aux_ingest import (
    AUDIT_PAIRS,
    SEED_JSON,
    audit_overlap,
    json_to_rows,
    load_seed,
)


# ---- seed 可载入且覆盖完整 ----

def test_seed_loadable():
    data = load_seed()
    assert data["periods"][0] == "2021-11"
    assert data["periods"][-1] == "2026-10"
    for k in ("制造业PMI", "新订单", "生产", "新出口订单", "非制造业PMI",
              "核心CPI", "食品烟酒", "居民同比", "企业同比", "政府同比"):
        seq = data["series"][k]
        hit = sum(1 for m in data["periods"] if seq.get(m) is not None)
        assert hit == len(data["periods"]), f"{k} 覆盖 {hit}/{len(data['periods'])}"


# ---- json_to_rows：仅映射新码 ----

def test_json_to_rows_codes_and_values():
    data = load_seed()
    rows = json_to_rows(data)
    codes = {r["indicator_code"] for r in rows}
    assert codes == {"PMI_PROD", "PMI_ORDER", "PMI_EXP", "PMI_NM",
                     "CPI_CORE", "CPI_FOOD", "CRED_GOV_YOY", "CRED_HH_YOY",
                     "CRED_ENT_YOY"}
    # 不写主序列码
    assert not codes & {"PMI", "CPI", "PPI", "M1", "M2", "TSF_STOCK"}
    # 末月值对拍（2026-10 官方值）
    last = {r["indicator_code"]: r for r in rows if r["period"] == "2026-10"}
    assert last["PMI_ORDER"]["val"] == 49.4
    assert last["PMI_PROD"]["val"] == 49.8
    assert last["PMI_EXP"]["val"] == 48.7
    assert last["CPI_CORE"]["val"] == 0.8
    assert last["CPI_FOOD"]["val"] == -1.6
    assert last["CRED_HH_YOY"]["val"] == -2.11
    assert last["CRED_ENT_YOY"]["val"] == 7.67
    assert last["CRED_GOV_YOY"]["val"] == 14.4
    # 行数 = 9 码 × 60 期
    assert len(rows) == 9 * 60
    # freq / yoy / source 约定
    r = last["PMI_ORDER"]
    assert r["freq"] == "M" and r["yoy"] is None
    assert r["unit"] == "%" and r["source"] == "nbs"
    assert last["CRED_HH_YOY"]["source"] == "pboc"


def test_json_to_rows_skips_nulls():
    data = {"series": {"新订单": {"2026-09": 50.5, "2026-10": None},
                       "核心CPI": {"2026-10": 0.8}},
            "source_map": {}}
    rows = json_to_rows(data)
    assert len(rows) == 2
    assert all(r["val"] is not None for r in rows)


# ---- 量级体检 ----

def _db_row(code, field, period, val):
    return {(code, field, period): val}


def test_audit_pass_on_consistent_overlap():
    data = {"series": {"制造业PMI": {"2026-10": 49.3},
                       "CPI同比": {"2026-10": 0.7},
                       "PPI同比": {"2026-10": 5.7},
                       "M1同比": {"2026-10": 4.4}}}
    db = {}
    db.update(_db_row("PMI", "val", "2026-10", 49.3))
    db.update(_db_row("CPI", "yoy", "2026-10", 0.7))
    db.update(_db_row("PPI", "yoy", "2026-10", 5.7))
    db.update(_db_row("M1", "yoy", "2026-10", 4.4))
    assert audit_overlap(data, db) == []


def test_audit_reads_yoy_field_for_m1():
    # M1 的 val 是余额（亿元），同比在 yoy —— 体检必须读 yoy 列，不得拿余额当同比
    data = {"series": {"M1同比": {"2026-10": 4.4}}}
    db = _db_row("M1", "val", "2026-10", 1168962.8)  # 余额亿元，不是同比
    assert audit_overlap(data, db) == []  # yoy 无重合 → 不误报


def test_audit_flags_large_deviation():
    data = {"series": {"制造业PMI": {"2026-10": 49.3}}}
    db = _db_row("PMI", "val", "2026-10", 51.0)  # 偏差 1.7 > 0.1
    v = audit_overlap(data, db)
    assert len(v) == 1 and "PMI" in v[0]


def test_audit_ignores_missing_db_overlap():
    data = {"series": {"制造业PMI": {"2026-10": 49.3}}}
    assert audit_overlap(data, {}) == []


def test_soft_audit_warns_not_blocks():
    from dq.data.aux_ingest import soft_audit
    data = {"series": {"社融存量同比": {"2026-10": 7.2}}}
    db = _db_row("TSF_STOCK", "yoy", "2026-10", 9.0)  # 偏差 1.8 > 1.5
    warns = soft_audit(data, db)
    assert len(warns) == 1 and "E 级" in warns[0]
    assert audit_overlap(data, db) == []  # 不进硬体检


def test_soft_audit_within_tolerance_is_silent():
    from dq.data.aux_ingest import soft_audit
    data = {"series": {"社融存量同比": {"2026-10": 7.2}}}
    db = _db_row("TSF_STOCK", "yoy", "2026-10", 8.1)  # 偏差 0.9 < 1.5，正常派生偏差不告警
    assert soft_audit(data, db) == []


def test_audit_pairs_anchor_is_2026_10():
    # 体检以 2026-10 期为主锚（首期实库跑批期），防口径漂移
    assert AUDIT_PAIRS["制造业PMI"][0] == "PMI"


def test_seed_file_shipped_in_repo():
    assert os.path.exists(SEED_JSON)
    with open(SEED_JSON, encoding="utf-8") as f:
        assert json.load(f)["series"]
