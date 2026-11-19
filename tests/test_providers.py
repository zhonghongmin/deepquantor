"""DL-01 提供器验收四场景（参数化）+ DL-02 凭证加载。"""
from __future__ import annotations

import pandas as pd
import pytest

from dq.data.credentials import CredentialsError, load_credentials
from dq.data.providers import Meta, UnifiedProvider, UpstreamError


def _frame(n=2):
    return pd.DataFrame({"date": [1] * n, "code": ["X"] * n, "v": list(range(n))})


class TestUnifiedProvider:
    """验收：主源正常 / 主源异常 / 备源返回空 / 三源皆空。"""

    @pytest.fixture()
    def sources_ok(self):
        return [
            ("galaxy", lambda: _frame()),
            ("westock", lambda: pd.DataFrame({"date": [2], "code": ["W"], "v": [9]})),
            ("akshare", lambda: pd.DataFrame({"date": [3], "code": ["A"], "v": [8]})),
        ]

    def test_primary_ok(self, sources_ok):
        df, meta = UnifiedProvider(sources_ok).fetch()
        assert meta.last_source == "galaxy"
        assert meta.fetched_at is not None
        assert len(df) == 2

    def test_primary_error_falls_back(self, sources_ok):
        sources = [("galaxy", lambda: (_ for _ in ()).throw(RuntimeError("星耀挂了"))),
                   *sources_ok[1:]]
        df, meta = UnifiedProvider(sources).fetch()
        assert meta.last_source == "westock"
        assert df["code"].iloc[0] == "W"

    def test_empty_result_reported_honestly(self):
        # 主源异常 + 备源返回空 → 命中备源，0 行如实上报（不充数、不继续降级）
        sources = [
            ("galaxy", lambda: (_ for _ in ()).throw(RuntimeError("err"))),
            ("westock", lambda: pd.DataFrame()),
            ("akshare", lambda: _frame()),
        ]
        df, meta = UnifiedProvider(sources).fetch()
        assert len(df) == 0
        assert meta.last_source == "westock"

    def test_all_raise_raises_upstream(self):
        def bad(name):
            def fn():
                raise RuntimeError(name)
            return fn
        sources = [(n, bad(n)) for n in ("galaxy", "westock", "akshare")]
        with pytest.raises(UpstreamError):
            UnifiedProvider(sources).fetch()

    def test_none_result_degrades(self):
        # 源返回 None 视为编程错误，按异常降级到下一档
        sources = [("galaxy", lambda: None), ("akshare", lambda: _frame())]
        _, meta = UnifiedProvider(sources).fetch()
        assert meta.last_source == "akshare"

    def test_empty_sources_rejected(self):
        with pytest.raises(ValueError):
            UnifiedProvider([])

    def test_meta_to_dict(self):
        d = Meta("galaxy", pd.Timestamp("2026-01-01").to_pydatetime()).__dict__
        assert d["last_source"] == "galaxy"


class TestCredentials:
    """验收：.env 兜底含 4 键 → 全部加载且桥接；两处全缺 → 列缺失键名。"""

    def test_env_bridge(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AMAZINGDATA_HOST", "10.0.0.1")
        monkeypatch.setenv("AMAZINGDATA_PORT", "5432")
        monkeypatch.delenv("AD_HOST", raising=False)
        monkeypatch.delenv("AD_PORT", raising=False)
        creds = load_credentials(required=("AD_HOST", "AD_PORT"), dotenv_path=tmp_path / "none.env")
        assert creds == {"AD_HOST": "10.0.0.1", "AD_PORT": "5432"}

    def test_dotenv_fallback_with_bridge(self, tmp_path, monkeypatch):
        for k in ("AD_HOST", "AD_PORT", "AD_USER", "AD_TOKEN"):
            monkeypatch.delenv(k, raising=False)
            monkeypatch.delenv(f"AMAZINGDATA_{k}", raising=False)
        p = tmp_path / ".env"
        p.write_text("# comment\nAMAZINGDATA_HOST=h1\nAD_PORT=5432\n"
                     "AD_USER='u1'\nAD_TOKEN=\"tok\"\n", encoding="utf-8")
        creds = load_credentials(env={}, dotenv_path=p)
        assert creds == {"AD_HOST": "h1", "AD_PORT": "5432", "AD_USER": "u1", "AD_TOKEN": "tok"}

    def test_env_overrides_dotenv(self, tmp_path):
        p = tmp_path / ".env"
        p.write_text("AD_HOST=from_env_file\n", encoding="utf-8")
        creds = load_credentials(env={"AD_HOST": "from_os"}, dotenv_path=p, required=("AD_HOST",))
        assert creds["AD_HOST"] == "from_os"

    def test_all_missing_raises_with_key_names(self, tmp_path):
        p = tmp_path / ".env"
        p.write_text("", encoding="utf-8")
        with pytest.raises(CredentialsError) as ei:
            load_credentials(env={}, dotenv_path=p)
        assert "AD_HOST" in str(ei.value) and "AD_TOKEN" in str(ei.value)

    def test_partial_missing(self, tmp_path):
        p = tmp_path / ".env"
        p.write_text("AD_HOST=h\n", encoding="utf-8")
        with pytest.raises(CredentialsError) as ei:
            load_credentials(env={}, dotenv_path=p, required=("AD_HOST", "AD_PORT"))
        assert "AD_PORT" in str(ei.value) and "AD_HOST" not in str(ei.value).split("：")[1]
