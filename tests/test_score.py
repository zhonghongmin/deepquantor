"""MC-10 宏观因子评分有界微调单测（Spec §4.3 / 数据策略 §1.17）。"""
import pytest

from dq.macro import config as C
from dq.macro.score import FactorScore


def _fs(scores, **kw):
    return FactorScore(scores, **kw)


def test_score_range():
    fs = _fs({"growth": 1.0, "inflation": 1.0, "money": 1.0, "credit": 1.0})
    assert fs.score == pytest.approx(1.0)
    fs = _fs({"growth": -1.0, "inflation": -1.0, "money": -1.0, "credit": -1.0})
    assert fs.score == pytest.approx(-1.0)


def test_score_within_band():
    # 微调后恒落在 base × (1 ± κ) 带内（§1.17 ⑥）
    base = 0.625
    fs = _fs({"growth": 1.0, "inflation": 1.0, "money": 1.0, "credit": 1.0})
    w, b = fs.adjust(base, "衰退", "双宽")
    assert w == pytest.approx(base * (1 + C.KAPPA_DEFAULT))
    fs = _fs({"growth": -1.0, "inflation": -1.0, "money": -1.0, "credit": -1.0})
    w, _ = fs.adjust(base, "衰退", "双宽")
    assert w == pytest.approx(base * (1 - C.KAPPA_DEFAULT))
    assert 0.0 <= w <= 1.0


def test_disabled_falls_back_to_base():
    # 关开关回退基准（逐格回归由参数化覆盖）
    fs = _fs({"growth": 1.0, "inflation": 1.0, "money": 1.0, "credit": 1.0}, enabled=False)
    for regime in C.REGIMES:
        for mc in C.MC_ENUM:
            base = C.EQUITY_CENTER[(regime, mc)] / 100.0
            w, b = fs.adjust(base, regime, mc)
            assert w == b


def test_all_stale_falls_back_to_base():
    # 全 stale（禁止插值兜底）→ 退化为纯查表
    fs = _fs({"growth": None, "inflation": None, "money": None, "credit": None})
    assert not fs.active
    w, b = fs.adjust(0.9, "复苏", "双宽")
    assert w == b == 0.9


def test_partial_stale_zero_neutral():
    fs = _fs({"growth": None, "inflation": 1.0, "money": 1.0, "credit": 1.0})
    assert fs.s_i["growth"] == 0.0 and "growth" in fs.stale


def test_quadrant_never_changes():
    # 象限反例：任意评分下 regime / money_credit / phase 不变（评分不进判定）
    fs = _fs({"growth": 1.0, "inflation": 1.0, "money": 1.0, "credit": 1.0})
    # adjust 只输出仓位数值，不携带象限字段 —— 结构级保证
    result = fs.adjust(0.5, "滞胀", "双紧")
    assert isinstance(result, tuple) and len(result) == 2


def test_extreme_state_capped():
    # 极端态滞胀+双紧：满分评分微调后不得高于该态上限 0.45（§1.10/§1.11）
    fs = _fs({"growth": 1.0, "inflation": 1.0, "money": 1.0, "credit": 1.0})
    w, _ = fs.adjust(0.34, "滞胀", "双紧")
    assert w <= C.EXTREME_STATE_CAP[("滞胀", "双紧")]


def test_kappa_hard_cap():
    with pytest.raises(ValueError):
        _fs({"growth": None}, kappa=0.25)


def test_weight_cap_and_sum():
    with pytest.raises(ValueError):
        _fs({"growth": None}, weights={"growth": 0.5, "inflation": 0.2, "money": 0.2, "credit": 0.1})
    with pytest.raises(ValueError):
        _fs({"growth": None}, weights={"growth": 0.2, "inflation": 0.2, "money": 0.2, "credit": 0.2})


def test_audit_fields_complete():
    fs = _fs({"growth": 0.5, "inflation": None, "money": -0.3, "credit": None})
    aud = fs.audit()
    for key in ("macro_factor_score", "s_i", "w_i", "kappa", "enabled", "stale", "active"):
        assert key in aud
