"""DL-01 真实源适配器（宏观 · akshare 档）。

按《数据策略总文档》§1.2 指标契约 + §5.2 三档路由实现：
① 星耀数智（宏观层无适用源，本期不接）→ ② westockdata（宏观层无）→ ③ akshare → ④ 计算派生。

实测结论（2026-11-20，akshare 1.18.81）：
- 可用：macro_china_pmi_yearly / non_man_pmi / cpi / ppi / money_supply / supply_of_money /
  gdp / exports_yoy / imports_yoy / new_financial_credit / bank_financing；
- 社融主源 macro_china_shrzgm（mofcom）站点级 SSL 故障 → 降级链改 bank_financing（金十增量）；
- 输出列统一为 market.macro_indicator 表列：indicator_code / freq / period /
  indicator_name / val / unit / yoy / source；period 月频 YYYY-MM、季频 YYYY-Qn。

网络约束：本环境动态双栈出网不稳，akshare 客户端统一锁 IPv4（幂等 patch，与公众号脚本同方案）。
全部源抛异常 → UnifiedProvider 抛 UpstreamError，禁止静默空帧充数（C-3）。
"""
from __future__ import annotations

import datetime as dt
import re
import socket
from collections.abc import Callable
from typing import Any

import pandas as pd

from .providers import Source, UnifiedProvider, UpstreamError

# ---------------------------------------------------------------- IPv4 锁定

_ipv4_patched = False


def enforce_ipv4() -> None:
    """强制 socket.getaddrinfo 只返回 AF_INET（动态双栈出网不稳的兜底，幂等）。"""
    global _ipv4_patched  # noqa: PLW0603
    if _ipv4_patched:
        return
    orig = socket.getaddrinfo

    def ipv4_only(*args: Any, **kwargs: Any):
        return [r for r in orig(*args, **kwargs) if r[0] == socket.AF_INET]

    socket.getaddrinfo = ipv4_only  # type: ignore[assignment]
    _ipv4_patched = True


def _ak():
    """懒加载 akshare（锁 IPv4 后再导入；测试 monkeypatch 友好）。"""
    enforce_ipv4()
    import akshare as ak

    return ak


# ---------------------------------------------------------------- period 解析

_RE_CN_MONTH = re.compile(r"(\d{4})年(\d{1,2})月")
_RE_DOT_MONTH = re.compile(r"(\d{4})\.(\d{1,2})$")
_RE_CN_QUARTER = re.compile(r"(\d{4})年第(\d)季度")


def to_month(s: str) -> str | None:
    """中文/点分月份 → YYYY-MM；解析失败返回 None。"""
    s = str(s).strip()
    m = _RE_CN_MONTH.match(s)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}"
    m = _RE_DOT_MONTH.fullmatch(s)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}"
    return None


def to_quarter(s: str) -> str | None:
    """中文季度 → YYYY-Qn；累计行（如「第1-2季度」）返回 None 跳过。"""
    m = _RE_CN_QUARTER.fullmatch(str(s).strip())
    return f"{m.group(1)}-Q{m.group(2)}" if m else None


def month_to_quarter(period: str) -> str:
    """YYYY-MM → YYYY-Qn（GDP 季度区间过滤用）。"""
    y, mo = int(period[:4]), int(period[5:7])
    return f"{y}-Q{(mo - 1) // 3 + 1}"


def minus_months(d: dt.date, months: int) -> dt.date:
    """日期回退 n 个月（落到当月 1 日，供近 N 月采集区间起点）。"""
    y, m = d.year, d.month - months
    while m <= 0:
        m += 12
        y -= 1
    return d.replace(year=y, month=m, day=1)


def period_in_range(period: str, start: dt.date, end: dt.date, freq: str) -> bool:
    """period 落在 [start, end] 内：月频比 YYYY-MM，季频比 YYYY-Qn（季频入参可为季频格式）。"""
    if freq == "Q":
        p = period if "Q" in period else month_to_quarter(period)
        s = month_to_quarter(start.strftime("%Y-%m"))
        e = month_to_quarter(end.strftime("%Y-%m"))
    else:
        p, s, e = period, start.strftime("%Y-%m"), end.strftime("%Y-%m")
    return s <= p <= e


# ---------------------------------------------------------------- 标准帧组装

OUT_COLS = ["indicator_code", "freq", "period", "indicator_name", "val", "unit", "yoy", "source"]


def _num(v: Any) -> float | None:
    """安全转 float；NaN/None/不可解析 → None。"""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if f != f else f  # NaN 剔除


def _frame(code: str, freq: str, name: str, unit: str,
           periods: list[str | None], vals: list[Any],
           yoys: list[Any], source: str) -> pd.DataFrame:
    """按 market.macro_indicator 输出列组装标准帧（period 解析失败的行剔除）。"""
    rows = [{"indicator_code": code, "freq": freq, "period": p,
             "indicator_name": name, "val": _num(v), "unit": unit,
             "yoy": _num(y), "source": source}
            for p, v, y in zip(periods, vals, yoys, strict=True) if p]
    return pd.DataFrame(rows, columns=OUT_COLS)


def _jin10(api: str, code: str, name: str, unit: str) -> pd.DataFrame:
    """金十数据源通用解析：列 = 商品/日期/今值/预测值/前值，日期 → 月 period。"""
    df = getattr(_ak(), api)()
    periods = [dt.date.fromisoformat(str(d)[:10]).strftime("%Y-%m") for d in df["日期"]]
    return _frame(code, "M", name, unit, periods, df["今值"], [None] * len(df), "akshare")


# ---------------------------------------------------------------- 指标适配器

# PMI（统计局官方源，新鲜至当月；金十源滞后约一年，降为备档）

def fetch_pmi_primary() -> pd.DataFrame:
    df = _ak().macro_china_pmi()  # 升序排列，head 为最新；与排序无关（全量落库）
    return _frame("PMI", "M", "官方制造业PMI", "%", df["月份"].map(to_month),
                  df["制造业-指数"], [None] * len(df), "akshare")


def fetch_pmi_nm_primary() -> pd.DataFrame:
    df = _ak().macro_china_pmi()
    return _frame("PMI_NM", "M", "官方非制造业PMI", "%", df["月份"].map(to_month),
                  df["非制造业-指数"], [None] * len(df), "akshare")


def fetch_pmi_jin10() -> pd.DataFrame:
    return _jin10("macro_china_pmi_yearly", "PMI", "官方制造业PMI", "%")


def fetch_pmi_nm_jin10() -> pd.DataFrame:
    return _jin10("macro_china_non_man_pmi", "PMI_NM", "官方非制造业PMI", "%")


def fetch_cpi() -> pd.DataFrame:
    df = _ak().macro_china_cpi()
    return _frame("CPI", "M", "CPI当月值", "%", df["月份"].map(to_month),
                  df["全国-当月"], df["全国-同比增长"], "akshare")


def fetch_ppi() -> pd.DataFrame:
    df = _ak().macro_china_ppi()
    return _frame("PPI", "M", "PPI当月值", "%", df["月份"].map(to_month),
                  df["当月"], df["当月同比增长"], "akshare")


def _money(code: str, cnt_col: str, yoy_col: str, name: str) -> pd.DataFrame:
    df = _ak().macro_china_money_supply()
    return _frame(code, "M", name, "亿元", df["月份"].map(to_month),
                  df[cnt_col], df[yoy_col], "akshare")


def fetch_m0() -> pd.DataFrame:
    return _money("M0", "流通中的现金(M0)-数量(亿元)", "流通中的现金(M0)-同比增长", "M0")


def fetch_m1() -> pd.DataFrame:
    return _money("M1", "货币(M1)-数量(亿元)", "货币(M1)-同比增长", "M1")


def fetch_m2() -> pd.DataFrame:
    return _money("M2", "货币和准货币(M2)-数量(亿元)", "货币和准货币(M2)-同比增长", "M2")


def fetch_gdp() -> pd.DataFrame:
    """GDP 单季行（该接口 2026 年起单季仅至 Q1，后续以累计行 GDPCUM 补位）。"""
    df = _ak().macro_china_gdp()
    qs = df["季度"].map(to_quarter)
    keep = qs.notna()
    return _frame("GDP", "Q", "GDP当季值", "亿元",
                  qs[keep].tolist(), df.loc[keep, "国内生产总值-绝对值"],
                  df.loc[keep, "国内生产总值-同比增长"], "akshare")


def fetch_gdp_cum() -> pd.DataFrame:
    """GDP 累计行（第1-n季度，YTD 同比作增长锚），period = 截至季度。"""
    df = _ak().macro_china_gdp()
    s = df["季度"].astype(str)
    m = s.str.extract(r"(\d{4})年第1-(\d)季度")
    ok = m[0].notna()
    periods = [f"{a}-Q{b}" for a, b, o in zip(m[0], m[1], ok, strict=False) if o]
    return _frame("GDPCUM", "Q", "GDP累计值(截至该季)", "亿元", periods,
                  df.loc[ok, "国内生产总值-绝对值"],
                  df.loc[ok, "国内生产总值-同比增长"], "akshare")


# 进出口（海关总署源，新鲜至当月；单位原文口径，绝对值校准记 E17）

def fetch_exp_primary() -> pd.DataFrame:
    df = _ak().macro_china_hgjck()
    return _frame("EXP_USD", "M", "当月出口额(美元)", "亿美元", df["月份"].map(to_month),
                  df["当月出口额-金额"], df["当月出口额-同比增长"], "akshare")


def fetch_imp_primary() -> pd.DataFrame:
    df = _ak().macro_china_hgjck()
    return _frame("IMP_USD", "M", "当月进口额(美元)", "亿美元", df["月份"].map(to_month),
                  df["当月进口额-金额"], df["当月进口额-同比增长"], "akshare")


def fetch_exp_jin10() -> pd.DataFrame:
    return _jin10("macro_china_exports_yoy", "EXP_USD", "出口同比(美元计价)", "%")


def fetch_imp_jin10() -> pd.DataFrame:
    return _jin10("macro_china_imports_yoy", "IMP_USD", "进口同比(美元计价)", "%")


def fetch_credit() -> pd.DataFrame:
    df = _ak().macro_china_new_financial_credit()
    return _frame("CREDIT", "M", "新增人民币贷款", "亿元", df["月份"].map(to_month),
                  df["当月"], df["当月-同比增长"], "akshare")


def fetch_tsf() -> pd.DataFrame:
    """社融增量：主源 shrzgm（mofcom，实测 SSL 故障）→ 备源 bank_financing（金十）。

    由 UnifiedProvider 降级：本函数只实现备源档；主源注册为独立档，失败自动落备源。
    """
    df = _ak().macro_china_bank_financing()
    periods = [dt.date.fromisoformat(str(d)[:10]).strftime("%Y-%m") for d in df["日期"]]
    return _frame("TSF", "M", "社会融资规模增量", "亿元", periods,
                  df["最新值"], [None] * len(df), "akshare")


def fetch_tsf_primary() -> pd.DataFrame:
    """社融增量主源（官方 mofcom）；当前站点级 SSL 故障，保留档位待其恢复。"""
    df = _ak().macro_china_shrzgm()
    periods = [to_month(m) for m in df["月份"]]
    cols = [c for c in df.columns if "当月" in c and "同比" not in c]
    yoy_cols = [c for c in df.columns if "当月" in c and "同比" in c]
    return _frame("TSF", "M", "社会融资规模增量", "亿元", periods,
                  df[cols[0]] if cols else [None] * len(df),
                  df[yoy_cols[0]] if yoy_cols else [None] * len(df), "akshare")


# ---------------------------------------------------------------- 注册表与路由

# indicator_code → (freq, 中文名, 单位, 源降级链 [(源标签, 拉取函数), ...])
MACRO_REGISTRY: dict[str, tuple[str, str, str, list[Source]]] = {
    "PMI":     ("M", "官方制造业PMI", "%",
                [("akshare-nbs", fetch_pmi_primary), ("akshare-jin10", fetch_pmi_jin10)]),
    "PMI_NM":  ("M", "官方非制造业PMI", "%",
                [("akshare-nbs", fetch_pmi_nm_primary), ("akshare-jin10", fetch_pmi_nm_jin10)]),
    "CPI":     ("M", "CPI当月值", "%", [("akshare", fetch_cpi)]),
    "PPI":     ("M", "PPI当月值", "%", [("akshare", fetch_ppi)]),
    "M0":      ("M", "M0", "亿元", [("akshare", fetch_m0)]),
    "M1":      ("M", "M1", "亿元", [("akshare", fetch_m1)]),
    "M2":      ("M", "M2", "亿元", [("akshare", fetch_m2)]),
    "GDP":     ("Q", "GDP当季值", "亿元", [("akshare", fetch_gdp)]),
    "GDPCUM":  ("Q", "GDP累计值(截至该季)", "亿元", [("akshare", fetch_gdp_cum)]),
    "EXP_USD": ("M", "当月出口额(美元)", "亿美元",
                [("akshare-gacc", fetch_exp_primary), ("akshare-jin10", fetch_exp_jin10)]),
    "IMP_USD": ("M", "当月进口额(美元)", "亿美元",
                [("akshare-gacc", fetch_imp_primary), ("akshare-jin10", fetch_imp_jin10)]),
    "CREDIT":  ("M", "新增人民币贷款", "亿元", [("akshare", fetch_credit)]),
    # 社融：主源（官方）失败自动降级备源（金十增量）
    "TSF":     ("M", "社会融资规模增量", "亿元",
                [("akshare-shrzgm", fetch_tsf_primary), ("akshare-jin10", fetch_tsf)]),
}


def provider_for(code: str, clock: Callable[[], dt.datetime] | None = None) -> UnifiedProvider:
    """按注册表为单指标构建 UnifiedProvider（逐档降级，last_source 记实际命中源）。"""
    freq, name, unit, sources = MACRO_REGISTRY[code]
    if clock is not None:
        return UnifiedProvider(sources, clock=clock)
    return UnifiedProvider(sources)


def fetch_all(start: dt.date, end: dt.date, codes: list[str] | None = None) -> pd.DataFrame:
    """全指标取数并按区间过滤，合并标准帧。

    单指标全部源异常 → 该指标跳过并记录（NFR-03：任一数据源不可用不阻断主链路），
    全部指标异常 → 抛 UpstreamError。
    """
    picked = codes or list(MACRO_REGISTRY)
    frames: list[pd.DataFrame] = []
    failed: list[str] = []
    for code in picked:
        freq, name, unit, sources = MACRO_REGISTRY[code]
        try:
            df, meta = UnifiedProvider(sources).fetch()
        except Exception:  # noqa: BLE001 —— 单指标失败不阻断（NFR-03），failed 留痕
            failed.append(code)
            continue
        mask = [period_in_range(p, start, end, freq) for p in df["period"]]
        df = df[mask]
        frames.append(df)
    if not frames:
        raise UpstreamError(f"全部指标未命中：{failed}")
    out = pd.concat(frames, ignore_index=True)
    out.attrs["failed"] = failed
    return out
