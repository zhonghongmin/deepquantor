"""DL-01 真实源适配器单测（mock akshare，不联网）。

覆盖：period 解析、标准帧组装（NaN/失败行剔除）、金十源解析、
三档降级（TSF 主源故障 → 金十备源命中）、fetch_all 单指标失败不阻断、
market.macro_indicator 幂等落库（SQLite 实测）。
"""
from __future__ import annotations

import datetime as dt
import sqlite3
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

import dq.data.fetchers as f


def _akmock(**apis):
    return SimpleNamespace(**apis)


# ---------------------------------------------------------------- period 解析

class TestPeriodParsing:
    def test_cn_month(self):
        assert f.to_month("2008年02月份") == "2008-02"

    def test_dot_month(self):
        assert f.to_month("2026.10") == "2026-10"

    def test_month_invalid_none(self):
        assert f.to_month("未知") is None

    def test_quarter_single(self):
        assert f.to_quarter("2006年第1季度") == "2006-Q1"

    def test_quarter_cumulative_skipped(self):
        assert f.to_quarter("2006年第1-2季度") is None

    def test_month_to_quarter(self):
        assert f.month_to_quarter("2026-11") == "2026-Q4"

    def test_range_month_freq(self):
        s, e = dt.date(2026, 1, 15), dt.date(2026, 3, 20)
        assert f.period_in_range("2026-02", s, e, "M")
        assert not f.period_in_range("2025-12", s, e, "M")
        assert not f.period_in_range("2026-04", s, e, "M")

    def test_range_quarter_freq(self):
        s, e = dt.date(2026, 1, 15), dt.date(2026, 9, 30)
        assert f.period_in_range("2026-Q1", s, e, "Q")
        assert f.period_in_range("2026-Q3", s, e, "Q")
        assert not f.period_in_range("2026-Q4", s, e, "Q")


# ---------------------------------------------------------------- 标准帧

class TestFrame:
    def test_nan_and_bad_period_dropped(self):
        df = f._frame("CPI", "M", "CPI当月值", "%",
                      ["2026-01", None, "2026-03"],
                      [101.5, 102.0, np.nan],
                      [0.5, 1.2, 0.9], "akshare")
        assert len(df) == 2                      # period=None 行剔除
        assert df.loc[df.period == "2026-03", "val"].isna().all()  # NaN 如实保留为 None
        assert list(df.columns) == f.OUT_COLS

    def test_num_rejects_non_numeric(self):
        assert f._num("abc") is None
        assert f._num(None) is None
        assert f._num(42) == 42.0


# ---------------------------------------------------------------- 源解析

_JIN10_COLS = ["商品", "日期", "今值", "预测值", "前值"]
_NBS_COLS = ["月份", "制造业-指数", "制造业-同比增长", "非制造业-指数", "非制造业-同比增长"]


def _nbs_raw():
    return pd.DataFrame([
        ["2026年10月份", 49.3, 0.61, 49.7, -0.8],
        ["2026年09月份", 50.1, 0.6, 50.2, 0.4],
    ], columns=_NBS_COLS)


class TestFetchers:
    def test_nbs_pmi_primary(self, monkeypatch):
        """PMI 主源（统计局）：制造业 + 非制造业同接口双指标。"""
        monkeypatch.setattr(f, "_ak", lambda: _akmock(macro_china_pmi=_nbs_raw))
        df = f.fetch_pmi_primary()
        assert list(df.period) == ["2026-10", "2026-09"]
        assert list(df.val) == [49.3, 50.1]
        df2 = f.fetch_pmi_nm_primary()
        assert list(df2.val) == [49.7, 50.2]
        assert set(df2.indicator_code) == {"PMI_NM"}

    def test_pmi_nbs_to_jin10_fallback(self, monkeypatch):
        """PMI 主源故障 → 金十备源命中，last_source 记备源。"""
        raw = pd.DataFrame([["中国官方制造业PMI", "2026-09-30", 49.8, None, None]],
                           columns=_JIN10_COLS)

        def boom():
            raise OSError("nbs 故障")

        monkeypatch.setattr(f, "_ak", lambda: _akmock(
            macro_china_pmi=boom, macro_china_pmi_yearly=lambda: raw))
        df, meta = f.provider_for("PMI").fetch()
        assert list(df.val) == [49.8]
        assert meta.last_source == "akshare-jin10"

    def test_gdp_cum_rows(self, monkeypatch):
        """GDP 累计行 → GDPCUM（截至季度）；单季与累计分码不撞主键。"""
        raw = pd.DataFrame({"季度": ["2026年第1-3季度", "2026年第3季度", "2026年第1-2季度"],
                            "国内生产总值-绝对值": [1071071.2, 380000.0, 695704.0],
                            "国内生产总值-同比增长": [4.6, 4.5, 4.7]})
        monkeypatch.setattr(f, "_ak", lambda: _akmock(macro_china_gdp=lambda: raw))
        cum = f.fetch_gdp_cum()
        assert list(cum.period) == ["2026-Q3", "2026-Q2"]
        assert set(cum.indicator_code) == {"GDPCUM"}
        single = f.fetch_gdp()
        assert list(single.period) == ["2026-Q3"]
        assert set(single.indicator_code) == {"GDP"}

    def test_exp_gacc_source(self, monkeypatch):
        """出口主源（海关总署）：金额 + 同比。"""
        raw = pd.DataFrame({"月份": ["2026年10月份"],
                            "当月出口额-金额": [4.123e8],
                            "当月出口额-同比增长": [35.2],
                            "当月进口额-金额": [3.07e8],
                            "当月进口额-同比增长": [41.6]})
        monkeypatch.setattr(f, "_ak", lambda: _akmock(macro_china_hgjck=lambda: raw))
        exp = f.fetch_exp_primary()
        assert list(exp.period) == ["2026-10"] and exp.yoy.iloc[0] == 35.2
        imp = f.fetch_imp_primary()
        assert imp.yoy.iloc[0] == 41.6 and imp.indicator_code.iloc[0] == "IMP_USD"

    def test_jin10_pmi_fallback_fn(self, monkeypatch):
        raw = pd.DataFrame([["中国官方制造业PMI", "2026-09-30", 49.8, None, None],
                            ["中国官方制造业PMI", "2026-10-31", 49.4, None, None]],
                           columns=_JIN10_COLS)
        monkeypatch.setattr(f, "_ak", lambda: _akmock(macro_china_pmi_yearly=lambda: raw))
        df = f.fetch_pmi_jin10()
        assert list(df.period) == ["2026-09", "2026-10"]
        assert list(df.val) == [49.8, 49.4]
        assert (df.source == "akshare").all()
        assert (df.yoy.isna()).all()

    def test_cpi_cn_columns(self, monkeypatch):
        raw = pd.DataFrame({"月份": ["2026年09月份", "2026年10月份"],
                            "全国-当月": [100.4, 100.2],
                            "全国-同比增长": [0.4, 0.2]})
        monkeypatch.setattr(f, "_ak", lambda: _akmock(macro_china_cpi=lambda: raw))
        df = f.fetch_cpi()
        assert list(df.period) == ["2026-09", "2026-10"]
        assert list(df.yoy) == [0.4, 0.2]
        assert set(df.indicator_name) == {"CPI当月值"}

    def test_gdp_cumulative_rows_dropped(self, monkeypatch):
        raw = pd.DataFrame({"季度": ["2026年第3季度", "2026年第1-3季度"],
                            "国内生产总值-绝对值": [320000.0, 950000.0],
                            "国内生产总值-同比增长": [4.8, 5.0]})
        monkeypatch.setattr(f, "_ak", lambda: _akmock(macro_china_gdp=lambda: raw))
        df = f.fetch_gdp()
        assert list(df.period) == ["2026-Q3"]

    def test_tsf_fallback_chain(self, monkeypatch):
        """主源 shrzgm 故障（现网实测 SSL）→ 备源金十命中，last_source 记备源。"""
        raw = pd.DataFrame({"日期": ["2026-09-01", "2026-10-01"], "最新值": [3351, 2522]})

        def boom():
            raise OSError("SSL: mofcom 站点故障")

        monkeypatch.setattr(f, "_ak", lambda: _akmock(
            macro_china_shrzgm=boom, macro_china_bank_financing=lambda: raw))
        df, meta = f.provider_for("TSF").fetch()
        assert list(df.period) == ["2026-09", "2026-10"]
        assert meta.last_source == "akshare-jin10"


# ---------------------------------------------------------------- fetch_all

class TestFetchAll:
    def test_single_metric_failure_not_blocking(self, monkeypatch):
        """CPI 源异常 → 跳过留痕；其余指标正常返回（NFR-03）。"""
        def boom():
            raise OSError("源故障")

        monkeypatch.setattr(f, "_ak", lambda: _akmock(
            macro_china_pmi=_nbs_raw,
            macro_china_pmi_yearly=boom, macro_china_non_man_pmi=boom,
            macro_china_cpi=boom, macro_china_ppi=boom,
            macro_china_money_supply=boom, macro_china_gdp=boom,
            macro_china_hgjck=boom, macro_china_exports_yoy=boom,
            macro_china_imports_yoy=boom, macro_china_new_financial_credit=boom,
            macro_china_shrzgm=boom, macro_china_bank_financing=boom))
        df = f.fetch_all(dt.date(2026, 10, 1), dt.date(2026, 10, 31),
                         codes=["PMI", "PMI_NM", "CPI"])
        assert set(df.indicator_code) == {"PMI", "PMI_NM"}
        assert df.attrs["failed"] == ["CPI"]

    def test_all_failed_raises(self, monkeypatch):
        def boom():
            raise OSError("源故障")
        monkeypatch.setattr(f, "_ak", lambda: _akmock(
            macro_china_pmi=boom, macro_china_pmi_yearly=boom, macro_china_cpi=boom))
        with pytest.raises(f.UpstreamError):
            f.fetch_all(dt.date(2026, 10, 1), dt.date(2026, 10, 31), codes=["PMI", "CPI"])

    def test_period_range_filtered(self, monkeypatch):
        monkeypatch.setattr(f, "_ak", lambda: _akmock(macro_china_pmi=_nbs_raw))
        df = f.fetch_all(dt.date(2026, 9, 1), dt.date(2026, 9, 30), codes=["PMI"])
        assert list(df.period) == ["2026-09"]


# ---------------------------------------------------------------- 落库（SQLite 实测）

class TestStorage:
    @pytest.fixture()
    def conn(self):
        c = sqlite3.connect(":memory:")
        c.execute("ATTACH ':memory:' AS market")
        c.execute("CREATE TABLE market.macro_indicator ("
                  "indicator_code TEXT, freq TEXT, period TEXT, indicator_name TEXT,"
                  " val REAL, unit TEXT, yoy REAL, source TEXT,"
                  " PRIMARY KEY (indicator_code, freq, period))")
        return c

    def _frame(self):
        return f._frame("PMI", "M", "官方制造业PMI", "%",
                        ["2026-09", "2026-10"], [49.5, 49.6], [None, None], "akshare")

    def test_idempotent_upsert(self, conn):
        from dq.data.storage import upsert_dataframe
        key = ("indicator_code", "freq", "period")
        assert upsert_dataframe(conn, "market.macro_indicator", self._frame(),
                                key, dialect="sqlite") == 2
        upsert_dataframe(conn, "market.macro_indicator", self._frame(), key, dialect="sqlite")
        assert conn.execute("SELECT COUNT(*) FROM market.macro_indicator").fetchone()[0] == 2

    def test_value_revision_overwrites(self, conn):
        from dq.data.storage import upsert_dataframe
        key = ("indicator_code", "freq", "period")
        upsert_dataframe(conn, "market.macro_indicator", self._frame(), key, dialect="sqlite")
        revised = self._frame()
        revised.loc[revised.period == "2026-10", "val"] = 49.7
        upsert_dataframe(conn, "market.macro_indicator", revised, key, dialect="sqlite")
        val = conn.execute("SELECT val FROM market.macro_indicator WHERE period='2026-10'"
                           ).fetchone()[0]
        assert val == 49.7
