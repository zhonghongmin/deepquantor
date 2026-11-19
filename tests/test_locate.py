"""MC-02 / MC-09 状态定位与 36 格查表单测（Spec §4.1，全状态空间逐格）。"""
import pytest

from dq.macro import config as C
from dq.macro.locate import (
    assert_grid_orthogonality,
    center_of,
    locate_money_credit,
    locate_phase,
    locate_regime,
)
from dq.macro.position import interpolate_weight, phase_of, phase_progress

# ---------------------------------------------------------------------------
# MC-02：九态定位（全 9 格）
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("money,credit,expect", [
    (1, 1, "双宽"), (1, 0, "宽货币·中性信用"), (1, -1, "宽货币紧信用"),
    (0, 1, "中性货币·宽信用"), (0, 0, "中性·中性"), (0, -1, "中性货币紧信用"),
    (-1, 1, "紧货币宽信用"), (-1, 0, "紧货币·中性信用"), (-1, -1, "双紧"),
])
def test_nine_states(money, credit, expect):
    assert locate_money_credit(money, credit) == expect
    assert expect in C.MC_ENUM


def test_nine_enum_exactly_9():
    assert len(C.MC_ENUM) == 9


# ---------------------------------------------------------------------------
# MC-02：四象限归并（全 9 格，§1.4 归并规则）
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("growth,inflation,expect", [
    (1, -1, "复苏"), (1, 0, "复苏"), (1, 1, "过热"),
    (0, -1, "复苏"), (0, 0, "复苏"), (0, 1, "过热"),
    (-1, -1, "衰退"), (-1, 0, "衰退"), (-1, 1, "滞胀"),
])
def test_regime_merge(growth, inflation, expect):
    assert locate_regime(growth, inflation) == expect


def test_neutral_rows_fixed_early_phase():
    # 中性区归并后固定 前期 / 0（§1.4 相位）
    for g in (-1, 0, 1):
        for i in (-1, 0, 1):
            if g == 0 or i == 0:
                assert locate_phase(g, i) == ("前期", 0.0)


# ---------------------------------------------------------------------------
# MC-09：36 格查表逐格一致（§1.4 表值）
# ---------------------------------------------------------------------------

def test_grid_completeness():
    assert len(C.EQUITY_CENTER) == 36
    assert len(C.ASSET_ALLOC_BASE) == 36
    assert set(C.REGIMES) == {"复苏", "过热", "滞胀", "衰退"}


@pytest.mark.parametrize("regime,mc,center", sorted(
    [(r, m, v) for (r, m), v in C.EQUITY_CENTER.items()], key=lambda x: (x[0], x[1])
))
def test_grid_value_matches_doc(regime, mc, center):
    # 落表值 = 文档 §1.4 表值（配置即查表，无计算折减）
    assert center_of(regime, mc) == center


def test_shuang_kuang_in_four_different_rows():
    # §1.4 ②：双宽同时存在于四象限不同行，而非单一映射
    assert_grid_orthogonality()
    rows = {r: center_of(r, "双宽") for r in C.REGIMES}
    assert rows == {"复苏": 90.0, "过热": 71.5, "滞胀": 41.5, "衰退": 62.5}


def test_no_quota_discount():
    # 配额不折减：查表即原样返回（本函数无任何缩放逻辑，键直查）
    assert center_of("复苏", "双宽") == 90.0
    assert center_of("衰退", "双紧") == 32.5


# ---------------------------------------------------------------------------
# MC-03：相位插值（36 格 × 相位端点 + 连续性）
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("regime", C.REGIMES)
@pytest.mark.parametrize("mc", C.MC_ENUM)
def test_phase_endpoints_all_grid(regime, mc):
    base = center_of(regime, mc)
    nxt = C.CLOCK_NEXT[regime]
    # 前期 / progress 0 → 中枢
    assert interpolate_weight(regime, mc, "前期", 0.0) == base
    # 后期起点（0.5）→ 中枢（零跳变起点）
    assert interpolate_weight(regime, mc, "后期", 0.5) == base
    # 后期末端（1.0）→ 下一象限中枢（零跳变终点）
    assert interpolate_weight(regime, mc, "后期", 1.0) == center_of(nxt, mc)


def test_clock_continuity_zero_jump():
    # 复苏后期末端 w_eff == 过热前期 w_eff，残差 = 0（§1.11 连续性断言）
    w_late = interpolate_weight("复苏", "双宽", "后期", 1.0)
    w_next = interpolate_weight("过热", "双宽", "前期", 0.0)
    assert w_late == pytest.approx(w_next, abs=1e-12)


def test_late_phase_monotonic():
    # 后期内 w_eff 随 progress 单调走向下一象限中枢
    seq = [interpolate_weight("衰退", "双宽", "后期", p) for p in (0.5, 0.7, 0.9, 1.0)]
    assert seq == sorted(seq)  # 衰退双宽 62.5 → 复苏双宽 90 单调上升
    assert seq[0] == 62.5 and seq[-1] == 90.0


# ---------------------------------------------------------------------------
# 相位归一化（驱动变量预判层；复苏/滞胀 PPI、过热/衰退 PMI）
# ---------------------------------------------------------------------------

def test_phase_progress_recovery_uses_ppi():
    # 复苏：通胀自谷底回升 → PPI 上行 → progress 升
    rising = [0.0, 0.5, 1.0, 1.5, 2.0]
    p = phase_progress("复苏", [49, 50, 51], rising)
    assert 0.0 <= p <= 1.0 and p > 0.5  # 末值即窗口 max → 1.0

def test_phase_progress_stagflation_inverted():
    # 滞胀：通胀自峰位回落 → PPI 下行 → progress 升
    falling = [3.0, 2.5, 2.0, 1.5, 1.0]
    p = phase_progress("滞胀", [49, 48, 47], falling)
    assert p == 1.0  # 末值即窗口 min → norm 0 → 1 - 0

def test_phase_progress_flat_window_zero():
    assert phase_progress("复苏", [50, 50], [1.0, 1.0, 1.0]) == 0.0

def test_phase_of_threshold():
    assert phase_of("复苏", 0.49) == "前期"
    assert phase_of("复苏", 0.5) == "后期"
