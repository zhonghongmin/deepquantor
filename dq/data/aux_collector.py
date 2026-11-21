#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""宏观辅助指标 · 采集器（akshare NBS 新网关 + 央行官网 双适配器）

补齐管理端「宏观数据」4 张维度卡的主/辅指标。2026-11-21 版本核查复核结论：
  - akshare 1.18.22 的 macro_china_nbs_nation 走旧网关 data.stats.gov.cn/easyquery.htm，
    被 WAF 拦截（HTTP 403）；这是"不可用"的真正原因，属版本落后 + 统计局网关升级；
  - akshare 1.20.39 已重写该接口，底层改为统计局新网关
    data.stats.gov.cn/dg/website/publicrelease/web/external/stream/esData，实测可用；
  - NBS 新接口可统一取：PMI 总量及分项、非制造业 PMI、CPI/核心 CPI/食品烟酒、PPI；
  - M1/M2 走 akshare macro_china_money_supply（央行口径，比 NBS 金融节点快 1 个月，重合月数值一致）；
  - 央行信用侧（社融存量同比、政府/居民/企业同比）无 NBS 节点，仍走 PBOC 官网统计表。
  故不存在"一个接口取全所有指标"，本脚本用"一个采集器 + 三类官方适配器（NBS/akshare 央行/央行官网）"实现。

两种通道（--source）：
  nbs       默认。NBS 侧走 akshare 1.20.39 新接口，信用侧走央行官网统计表；
  official  纯官网解析（统计局新闻稿 + 央行统计表），不依赖 akshare，作对照/兜底。

NBS 口径说明：
  - CPI / 核心 CPI / 食品烟酒 / PPI 返回"上年同月=100"指数，脚本统一减 100 转同比（保留 2 位小数）；
  - CPI 节点按年份分段（(2026-)/(2021-2025)/(2016-2020)），须用 period=LAST120 取全再按窗口拼接：
    LAST10 对旧年份段返回 0 期，LAST120 才能让 (2021-2025) 覆盖满 60 期（2021-01~2025-12）；
  - M1/M2 金融节点最新月常比 PMI/CPI 滞后 1 个月，缺月输出 null，不补零不外推；
  - CPI 跨基期（如 2021-2025 段与 2026- 段口径口径衔接）以官方节点为准，不做人为平滑。

用法：
    python3 fetch_macro_aux.py --months 6                       # 近 6 个月，默认 nbs 通道
    python3 fetch_macro_aux.py --months 60 --end 2026-10 --out m60.json
    python3 fetch_macro_aux.py --months 60 --source official    # 纯官网对照通道
    python3 fetch_macro_aux.py --months 60 --resume m60.json --out m60.json  # 断点续采

关键机制：
  - --months N 同时驱动 NBS period=LAST{N}（自动向上取整到可用档位）与央行归档覆盖年份；
  - PMI 稿（official 通道）按标题月份每 11 个月均匀选篇，自带 13 个月，多期合并无缝覆盖；
  - 央行归档每年一张宽表，从统计数据年度索引动态发现年份与子栏目，不写死年份；
  - 「居民同比 / 企业同比」用余额自算，需 t-12 基数，故余额表多取 12 个月；
  - 每个指标缺失期返回 null，绝不补零、不填充、不外推。

输出：终端表格 + JSON（默认 macro_aux_official.json），series 内每指标附 _source 元信息。
"""
import argparse
import json
import math
import os
import re
import sys
import time
import urllib.parse
from datetime import datetime

import requests
from bs4 import BeautifulSoup

UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")
SESSION = requests.Session()
SESSION.headers.update({"User-Agent": UA, "Accept-Language": "zh-CN,zh;q=0.9"})

STATS_HOST = "https://www.stats.gov.cn"
STATS_INDEX = STATS_HOST + "/sj/zxfb/"
PBC_HOST = "https://www.pbc.gov.cn"
PBC_YEAR_INDEX = PBC_HOST + "/diaochatongjisi/116219/116319/index.html"

MONTH_RE = re.compile(r"(\d{4})\s*年\s*(\d{1,2})\s*月")

# ---- akshare 1.20.39 NBS 新网关路径与行名映射 ----
# 说明：新版 macro_china_nbs_nation 底层为统计局新站目录树 path，旧版路径已失效。
NBS_INDEX = {
    "制造业PMI": ("采购经理指数>制造业采购经理指数", {
        "制造业PMI": "制造业采购经理指数(%)",
        "生产": "生产指数(%)",
        "新订单": "新订单指数(%)",
        "新出口订单": "新出口订单指数(%)",
    }),
    "非制造业PMI": ("采购经理指数>非制造业采购经理指数", {
        "非制造业PMI": "非制造业商务活动指数(%)",
    }),
    "PPI": ("价格指数>工业生产者出厂价格分类指数>工业生产者出厂价格指数 (上年同月=100)", {
        "PPI同比": "工业生产者出厂价格指数(上年同月=100)",
    }),
}
_CPI_BASE = ("价格指数>居民消费价格分类指数 (上年同月=100)>"
             "全国居民消费价格分类指数 (上年同月=100) ")
# CPI 按基期分段，逐段用 LAST120 取全后拼接（LAST10 对旧段返回空）
NBS_CPI_SEGMENTS = [
    _CPI_BASE + "(2026-)",
    _CPI_BASE + "(2021-2025)",
    _CPI_BASE + "(2016-2020)",
]
NBS_CPI_ROWS = {
    "CPI同比": "居民消费价格指数(上年同月=100)",
    "核心CPI": "不包括食品和能源居民消费价格指数(上年同月=100)",
    # 基期切换导致行名不同：2026 新段含"及在外餐饮"，2021-2025 旧段只写"食品烟酒类"
    "食品烟酒": ["食品烟酒及在外餐饮类居民消费价格指数(上年同月=100)",
                 "食品烟酒类居民消费价格指数(上年同月=100)"],
}
# 这些指标在 NBS 返回"上年同月=100"指数，需减 100 换为同比
INDEX_MINUS_100 = {"CPI同比", "核心CPI", "食品烟酒", "PPI同比"}
NBS_MIN_VERSION = (1, 20, 0)  # NBS 新网关重写起始版本；低于此走旧 easyquery 会被 WAF 403


# ---------------------------------------------------------------- 基础工具
def get(url, tries=3, timeout=40):
    last = None
    for i in range(tries):
        try:
            r = SESSION.get(url, timeout=timeout)
            r.encoding = r.apparent_encoding or "utf-8"
            if r.status_code == 200 and r.text.strip():
                return r.text
            last = f"HTTP {r.status_code}"
        except Exception as e:                      # noqa: BLE001
            last = f"{type(e).__name__}: {e}"
        time.sleep(1.2 * (i + 1))
    raise RuntimeError(f"抓取失败 {url} → {last}")


def soup(url, **kw):
    return BeautifulSoup(get(url, **kw), "html.parser")


def norm_cn_month(text):
    """'2026 年 5 月' → '2026-05'"""
    m = MONTH_RE.search(text or "")
    if not m:
        return None
    return f"{m.group(1)}-{int(m.group(2)):02d}"


def norm_pbc_month(text):
    """'2026.05' → '2026-05'"""
    m = re.search(r"(\d{4})\.(\d{1,2})", text or "")
    if not m:
        return None
    return f"{m.group(1)}-{int(m.group(2)):02d}"


def num(cell):
    txt = cell.get_text(" ", strip=True).replace(",", "")
    txt = txt.replace("−", "-").replace("—", "").replace("%", "").strip()
    if not re.fullmatch(r"-?\d+(\.\d+)?", txt):
        return None
    return float(txt)


def table_rows(tbl):
    """把 HTML 表格拆成 [(首列文本, [数值...])]"""
    out = []
    for tr in tbl.find_all("tr"):
        cells = tr.find_all(["td", "th"])
        if not cells:
            continue
        label = " ".join(cells[0].get_text(" ", strip=True).split())
        vals = [num(c) for c in cells[1:]]
        vals = [v for v in vals if v is not None]
        out.append((label, vals))
    return out


def month_window(n_months, end_month):
    """返回 [end-n+1, ..., end] 共 n 个月，形如 2026-05"""
    ey, em = map(int, end_month.split("-"))
    months = []
    y, m = ey, em
    for _ in range(n_months):
        months.append(f"{y}-{m:02d}")
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    months.reverse()
    return months


# ---------------------------------------------------------------- NBS 新网关（akshare 新版实现）
def _check_akshare():
    """确认 akshare 的 NBS 接口为新网关实现。

    2026-11-22 实测：本环境 akshare 1.18.81 的 macro_china_nbs_nation 源码已是
    data.stats.gov.cn/dg/website/publicrelease/... 新网关（旧 WAF 403 只发生在
    1.18.22 及更早的 easyquery 实现），取 PMI 分项成功。故版本不足仅告警不阻断，
    由 nbs_fetch 实际调用结果兜底（失败仍会被上层捕获降级 seed JSON）。
    """
    import warnings

    import akshare as ak
    ver = tuple(int(x) for x in re.findall(r"\d+", ak.__version__)[:3])
    if ver < NBS_MIN_VERSION:
        warnings.warn(
            f"akshare {ak.__version__} 低于实测可用版本 {NBS_MIN_VERSION}；"
            "若 NBS 取数报 WAF 403 请升级：python3 -m pip install -U akshare")
    return ak


def nbs_period(n_months):
    """把请求月数映射到 NBS period 档位；NBS 只认 LAST10/LAST60/LAST120 或年份范围。
    CPI 分段固定 LAST120，其余按最小够用档位选，减少无谓传输。"""
    for limit in (10, 60, 120):
        if n_months <= limit:
            return f"LAST{limit}"
    return "LAST120"


def nbs_fetch(path, period):
    """调 akshare NBS 新接口，返回 DataFrame"""
    ak = _check_akshare()
    return ak.macro_china_nbs_nation("月度数据", path, period=period)


def nbs_to_series(df, row_map, months, minus100=False):
    """NBS DataFrame（行=指标，列=YYYY年M月）→ {指标: {YYYY-MM: 值}}
    列名可能为 '2026年10月'，用 MONTH_RE 归一。缺失/非法值跳过（保留 null）。"""
    out = {k: {} for k in row_map}
    if df is None or getattr(df, "empty", True):
        return out
    for col in df.columns:
        mo = norm_cn_month(str(col))
        if mo not in months:
            continue
        for key, row_label in row_map.items():
            # 支持候选行名：基期切换时同一指标在旧/新段名称不同，取首个命中的
            if isinstance(row_label, (list, tuple)):
                hit = next((r for r in row_label if r in df.index), None)
                if hit is None:
                    continue
                row_label = hit
            if row_label not in df.index:
                continue
            raw = df.at[row_label, col]
            try:
                v = float(raw)
            except (TypeError, ValueError):
                continue
            if minus100 and key in INDEX_MINUS_100:
                v = round(v - 100, 2)
            out[key][mo] = v
    return out


def ak_money_supply_series(months):
    """M1/M2 同比：用 akshare macro_china_money_supply（央行口径）。
    实测该接口比 NBS『金融>货币供应量』节点快 1 个月（前者到 2026-10，后者仅到 2026-09），
    且两源在重合月份数值完全一致（如 2026-09 均 M1=3.2/M2=7.2），故货币卡优先此源。"""
    ak = _check_akshare()
    df = ak.macro_china_money_supply()
    m1_col = next((c for c in df.columns if "M1" in c and "同比" in c), None)
    m2_col = next((c for c in df.columns if "M2" in c and "同比" in c), None)
    out = {"M1同比": {}, "M2同比": {}}
    if not m1_col or not m2_col:
        return out
    for _, row in df.iterrows():
        mo = norm_cn_month(str(row["月份"]))
        if mo not in months:
            continue
        for key, col in (("M1同比", m1_col), ("M2同比", m2_col)):
            try:
                out[key][mo] = float(row[col])
            except (TypeError, ValueError):
                pass
    return out


def nbs_cpi_series(months):
    """CPI 按基期分段采集并合并：(2026-) 新段优先，旧段补历史。
    每段固定 LAST120，否则 (2021-2025) 等旧段会返回空表。"""
    merged = {k: {} for k in NBS_CPI_ROWS}
    for path in NBS_CPI_SEGMENTS:
        try:
            df = nbs_fetch(path, "LAST120")
        except Exception as e:                      # noqa: BLE001
            continue                                # 不存在的年份段（如 2016-2020）跳过
        part = nbs_to_series(df, NBS_CPI_ROWS, months, minus100=True)
        for k, seq in part.items():
            for mo, v in seq.items():
                merged[k].setdefault(mo, v)         # 先段（新基期）优先
    return merged


# ---------------------------------------------------------------- 统计局
def stats_crawl(max_pages=8):
    """翻页抓取《数据发布》栏目，返回 [(标题, 绝对URL)]"""
    found = []
    for i in range(max_pages):
        url = STATS_INDEX + ("index.html" if i == 0 else f"index_{i}.html")
        try:
            sp = soup(url)
        except RuntimeError:
            break
        n = 0
        for a in sp.find_all("a", href=True):
            href = a["href"]
            if not re.search(r"t\d{8}_\d+\.html", href):
                continue
            title = " ".join(a.get_text(" ", strip=True).split())
            if not title:
                continue
            full = urllib.parse.urljoin(url, href)
            found.append((title, full))
            n += 1
        if n == 0:
            break
    # 去重保序
    seen, uniq = set(), []
    for t, u in found:
        if u in seen:
            continue
        seen.add(u)
        uniq.append((t, u))
    return uniq


def parse_pmi(url):
    """解析 PMI 新闻稿：表1 制造业构成指数、表2 其他相关指标、表3 非制造业"""
    sp = soup(url)
    res = {"pmi": {}, "生产": {}, "新订单": {}, "新出口订单": {}, "非制造业商务活动": {}}
    SIG = {
        "t1": ["PMI", "生产", "新订单", "原材料", "从业人员", "供应商"],
        "t2": ["新出口", "进口", "采购量", "购进价格", "出厂", "产成品", "在手", "活动预期"],
        "t3": ["商务活动", "投入品", "销售价格", "业务活动"],
    }
    for tbl in sp.find_all("table"):
        txt = " ".join(tbl.get_text(" ", strip=True).split())
        kind = None
        for k, sig in SIG.items():
            if all(s in txt for s in sig):
                kind = k
                break
        if not kind:
            continue
        rows = table_rows(tbl)
        for label, vals in rows:
            mo = norm_cn_month(label)
            if not mo or not vals:
                continue
            if kind == "t1":
                for key, idx in (("pmi", 0), ("生产", 1), ("新订单", 2)):
                    if len(vals) > idx and mo not in res[key]:
                        res[key][mo] = vals[idx]
            elif kind == "t2":
                if mo not in res["新出口订单"]:
                    res["新出口订单"][mo] = vals[0]
            elif kind == "t3":
                if mo not in res["非制造业商务活动"]:
                    res["非制造业商务活动"][mo] = vals[0]
    return res


def merge_pmi(dst, src):
    """把一期 PMI 稿的序列并入累计结果，已有月份不覆盖"""
    for k, seq in src.items():
        slot = dst.setdefault(k, {})
        for mo, v in seq.items():
            slot.setdefault(mo, v)


def pick_pmi_reports(pmi_titles, months):
    """按目标区间均匀选稿：每篇稿覆盖其标题月及前 12 个月，
    故每隔约 11 个月取一篇即可无缝覆盖长区间，避免只取最近几篇导致历史期缺失。
    """
    dated = []
    for t, u in pmi_titles:
        mo = norm_cn_month(t)
        if mo:
            dated.append((mo, t, u))
    dated.sort()
    if not dated:
        return []
    # 从区间起点起，每 11 个月一个采样锚点
    y, m = map(int, months[0].split("-"))
    ey, em = map(int, months[-1].split("-"))
    chosen = {}
    while (y, m) <= (ey, em):
        anchor = f"{y}-{m:02d}"
        cands = [(mo, t, u) for mo, t, u in dated if mo >= anchor]
        if cands:
            mo, t, u = min(cands)          # 覆盖 anchor 的最近一期稿
            chosen[u] = (mo, t, u)
        m += 11
        if m > 12:
            m -= 12
            y += 1
    # 补最新一期，确保末月覆盖
    mo, t, u = dated[-1]
    chosen.setdefault(u, (mo, t, u))
    return [(t, u) for _, t, u in sorted(chosen.values())]


def _parse_cpi_html(html):
    """从 CPI 新闻稿 HTML 解析：核心 CPI 同比、食品烟酒同比、CPI 同比"""
    sp = BeautifulSoup(html, "html.parser")
    out = {}
    for tbl in sp.find_all("table"):
        txt = " ".join(tbl.get_text(" ", strip=True).split())
        if "不包括食品和能源" not in txt:
            continue
        for label, vals in table_rows(tbl):
            if not vals:
                continue
            if "不包括食品和能源" in label:
                out["核心CPI"] = vals[1] if len(vals) > 1 else None
            elif "食品烟酒" in label:
                out["食品烟酒"] = vals[1] if len(vals) > 1 else None
            elif label.strip() in ("居民消费价格", "居民消费价格指数"):
                out["CPI"] = vals[1] if len(vals) > 1 else None
        break
    # 正文兜底
    body = " ".join(sp.get_text(" ", strip=True).split())
    if out.get("核心CPI") is None:
        m = re.search(r"核心\s*CPI\s*同比(上涨|下降)([\d.]+)%", body)
        if m:
            out["核心CPI"] = float(m.group(2)) * (1 if m.group(1) == "上涨" else -1)
    if out.get("食品烟酒") is None:
        m = re.search(r"食品烟酒(?:及在外餐饮)?价格同比(上涨|下降)([\d.]+)%", body)
        if m:
            out["食品烟酒"] = float(m.group(2)) * (1 if m.group(1) == "上涨" else -1)
    if out.get("CPI") is None:
        m = re.search(r"全国居民消费价格同比(上涨|下降)([\d.]+)%", body)
        if m:
            out["CPI"] = float(m.group(2)) * (1 if m.group(1) == "上涨" else -1)
    return out


def parse_cpi(url, tries=2):
    """解析 CPI 稿，带字段校验重试：统计局限流时会返回 200 但正文不完整，
    此时核心字段缺失，重新请求而非接受空值。"""
    best = {}
    for i in range(tries):
        try:
            html = get(url, tries=1)
            out = _parse_cpi_html(html)
            # 以「核心CPI 或 食品烟酒」任一命中视为正文完整
            if out.get("核心CPI") is not None or out.get("食品烟酒") is not None:
                return out
            if len(out) > len(best):
                best = out
        except RuntimeError:
            pass
        if i < tries - 1:
            time.sleep(1.5 * (i + 1))
    return best


# ---------------------------------------------------------------- 央行
def pbc_find_link(page_url, keyword):
    """在央行栏目页里找到含 keyword 标题的表附件链接（取 htm，缺失则 xls）"""
    sp = soup(page_url)
    best = None
    for a in sp.find_all("a", href=True):
        href = a["href"]
        if "attachDir" not in href:
            continue
        txt = " ".join(a.get_text(" ", strip=True).split())
        if not txt:
            continue
        blk = a
        for _ in range(4):
            blk = blk.parent
            if blk is None:
                break
            bt = " ".join(blk.get_text(" ", strip=True).split())
            if keyword in bt:
                break
        if keyword in (blk.get_text(" ", strip=True) if blk else "") or keyword in txt:
            ext = os.path.splitext(href)[1].lower()
            cand = (0 if ext == ".htm" else 1, href)
            if best is None or cand[0] < best[0]:
                best = cand
    return best[1] if best else None


def pbc_year_index():
    """从央行统计数据索引页动态发现 {年份: 年度归档URL}"""
    sp = soup(PBC_YEAR_INDEX)
    out = {}
    for a in sp.find_all("a", href=True):
        t = " ".join(a.get_text(" ", strip=True).split())
        m = re.fullmatch(r"(20\d{2})年统计数据", t)
        if m:
            out[int(m.group(1))] = urllib.parse.urljoin(PBC_HOST, a["href"])
    return out


def pbc_subcolumn(year_url, keyword):
    """在年度归档页找到指定子栏目 URL（如「社会融资规模」）"""
    sp = soup(year_url)
    for a in sp.find_all("a", href=True):
        t = " ".join(a.get_text(" ", strip=True).split())
        if t == keyword:
            return urllib.parse.urljoin(PBC_HOST, a["href"])
    # 退而求其次：标题以 keyword 开头且较短
    for a in sp.find_all("a", href=True):
        t = " ".join(a.get_text(" ", strip=True).split())
        if t.startswith(keyword) and len(t) <= len(keyword) + 4:
            return urllib.parse.urljoin(PBC_HOST, a["href"])
    return None


def pbc_collect_years(years, wanted, column_keyword, table_keyword, log):
    """遍历年度归档 → 子栏目 → 统计表，合并 {'行名|slot': {月: 值}}"""
    idx = pbc_year_index()
    merged = {}
    found_urls = {}
    for y in sorted(years, reverse=True):
        yu = idx.get(y)
        if not yu:
            log(f"   [央行] {y}年 无归档页，跳过")
            continue
        col = pbc_subcolumn(yu, column_keyword)
        if not col:
            log(f"   [央行] {y}年 未找到栏目「{column_keyword}」，跳过")
            continue
        link = pbc_find_link(col, table_keyword)
        if not link:
            log(f"   [央行] {y}年 未找到表「{table_keyword}」，跳过")
            continue
        full = urllib.parse.urljoin(PBC_HOST, link)
        d = parse_pbc_wide(full, wanted)
        for k, v in d.items():
            merged.setdefault(k, {}).update(v)
        found_urls[y] = full
        brief = ", ".join(f"{k.split('|')[0]}:{len(v)}期" for k, v in d.items())
        log(f"   [央行] {y}年 {table_keyword} → {brief}")
    return merged, found_urls


def expand_row(tr):
    """把一行展开成 {绝对列号: cell}，按 colspan 累计"""
    out, col = {}, 0
    for c in tr.find_all(["td", "th"]):
        span = int(c.get("colspan") or 1)
        for k in range(span):
            out[col + k] = c
        col += span
    return out


def parse_pbc_wide(url, wanted):
    """解析央行宽表：返回 {'行名|slot': {月份: 值}}

    支持两种版式：
      ① 每月一列（人民币信贷收支表）：列序 = 月份
      ② 每月两列（社融存量统计表）：月份表头 colspan=2，列序 = 存量、增速
    """
    sp = soup(url)
    tables = sp.find_all("table")
    if not tables:
        return {}
    tbl = max(tables, key=lambda t: len(t.find_all("tr")))
    trs = tbl.find_all("tr")

    month_row_idx, month_of_col = None, {}
    for ri, tr in enumerate(trs):
        hits = {}
        for col, c in expand_row(tr).items():
            m = norm_pbc_month(c.get_text(" ", strip=True))
            if m:
                hits[col] = m
        if len(set(hits.values())) >= 3:
            month_row_idx, month_of_col = ri, hits
            break
    if month_row_idx is None:
        return {}

    kind_of_col = {col: "value" for col in month_of_col}
    for ri in range(month_row_idx + 1, min(month_row_idx + 4, len(trs))):
        labels = {col: c.get_text(" ", strip=True)
                  for col, c in expand_row(trs[ri]).items()}
        if any("增速" in l or "Growth" in l for l in labels.values()):
            for col, l in labels.items():
                if "增速" in l or "Growth" in l:
                    kind_of_col[col] = "growth"
                elif "存量" in l or "Stock" in l:
                    kind_of_col[col] = "stock"
            break

    data = {}
    for tr in trs[month_row_idx + 1:]:
        cells = expand_row(tr)
        if not cells:
            continue
        label = " ".join(cells[0].get_text(" ", strip=True).split())
        if not label:
            continue
        for col, c in cells.items():
            if col not in month_of_col:
                continue
            val = num(c)
            if val is None:
                continue
            for key in wanted:
                if key in label:
                    slot = kind_of_col.get(col, "value")
                    data.setdefault(f"{key}|{slot}", {})[month_of_col[col]] = val
    return data


def yoy(series, months):
    """用本期与 12 个月前对比算同比；基数不足返回 None"""
    out = {}
    for m in months:
        y, mo = m.split("-")
        base = f"{int(y) - 1}-{mo}"
        if m in series and base in series and series[base]:
            out[m] = round((series[m] / series[base] - 1) * 100, 2)
    return out


# ---------------------------------------------------------------- 主流程 · 官网通道
def collect_official(n_months=6, end_month=None, verbose=True, max_pages=None, prior=None):
    end = end_month or datetime.now().strftime("%Y-%m")
    months = month_window(n_months, end)
    # 同比基数：余额类需额外前推 12 个月
    base_n = n_months + 12
    base_months = month_window(base_n, end)
    # 央行需覆盖的年份（按基数窗口）
    bal_years = sorted({int(m[:4]) for m in base_months})
    # 社融存量表增速列本身已是同比，只需覆盖展示年份
    shr_years = sorted({int(m[:4]) for m in months})

    log = print if verbose else (lambda *a, **k: None)
    out = {"periods": months, "months_requested": n_months,
           "generated_at": datetime.now().isoformat(timespec="seconds"),
           "sources": {}}

    # ---- 统计局：PMI 分项（每期稿自带近 13 个月，多期合并覆盖长区间）----
    if max_pages is None:
        max_pages = max(10, math.ceil(n_months * 1.1) + 6)
    items = stats_crawl(max_pages)
    log(f"[统计局] 发布栏目翻页 {max_pages} 页，抓取条目 {len(items)}")
    pmi_titles = [(t, u) for t, u in items if "采购经理指数运行情况" in t]
    if not pmi_titles:
        raise RuntimeError("未在统计局发布栏目找到 PMI 新闻稿")
    picked = pick_pmi_reports(pmi_titles, months)
    pmi = {}
    for t, u in picked:
        merge_pmi(pmi, parse_pmi(u))
    log(f"[统计局] PMI 稿 {len(pmi_titles)} 篇，区间均匀选 {len(picked)} 篇合并；"
        f"生产覆盖 {len(pmi.get('生产', {}))} 期")
    out["sources"]["PMI分项"] = [u for _, u in picked]

    # ---- 统计局：CPI（逐月稿）----
    cpi_items = [(t, u) for t, u in items if "居民消费价格" in t and ("同比" in t or "上涨" in t or "下降" in t)]
    cpi_map = {}
    for t, u in cpi_items:
        mo = norm_cn_month(t)
        if mo:
            cpi_map.setdefault(mo, u)
    cpi_all = {}
    for mo in months:
        u = cpi_map.get(mo)
        if not u:
            continue
        cpi_all[mo] = parse_cpi(u)
    cpi_hit = sum(1 for m in months if m in cpi_all)
    log(f"[统计局] CPI 稿命中 {cpi_hit}/{len(months)} 期（栏目共匹配 {len(cpi_items)} 篇）")
    out["sources"]["CPI"] = {m: cpi_map.get(m) for m in months}

    # ---- 央行：社会融资规模存量统计表（政府债券增速、社融存量同比）----
    shr, shr_urls = pbc_collect_years(
        shr_years, ["社会融资规模存量", "政府债券"],
        "社会融资规模", "社会融资规模存量统计表", log)
    shr_growth = {k.split("|")[0]: v for k, v in shr.items() if k.endswith("|growth")}
    out["sources"]["社融存量统计表"] = shr_urls

    # ---- 央行：金融机构人民币信贷收支表（住户 / 企事业贷款余额）→ 同比 ----
    keys = ["住户贷款", "企（事）业单位贷款", "企(事)业单位贷款"]
    bal, bal_urls = pbc_collect_years(
        bal_years, keys, "金融机构信贷收支统计",
        "金融机构人民币信贷收支表", log)
    out["sources"]["人民币信贷收支表"] = bal_urls

    # ---- 汇总 ----
    res = {}
    res["制造业PMI"] = {m: pmi.get("pmi", {}).get(m) for m in months}
    res["生产"] = {m: pmi.get("生产", {}).get(m) for m in months}
    res["新订单"] = {m: pmi.get("新订单", {}).get(m) for m in months}
    res["新出口订单"] = {m: pmi.get("新出口订单", {}).get(m) for m in months}
    res["非制造业PMI"] = {m: pmi.get("非制造业商务活动", {}).get(m) for m in months}
    res["CPI同比"] = {m: cpi_all.get(m, {}).get("CPI") for m in months}
    res["核心CPI"] = {m: cpi_all.get(m, {}).get("核心CPI") for m in months}
    res["食品烟酒"] = {m: cpi_all.get(m, {}).get("食品烟酒") for m in months}
    res["社融存量同比"] = {m: shr_growth.get("社会融资规模存量", {}).get(m) for m in months}
    res["政府同比"] = {m: shr_growth.get("政府债券", {}).get(m) for m in months}
    hh = next((k for k in bal if k.startswith("住户贷款")), None)
    qy = next((k for k in bal if "企" in k and "业单位贷款" in k), None)
    if hh:
        res["居民同比"] = yoy(bal[hh], months)
        res.setdefault("_balance", {})["住户贷款"] = bal[hh]
    if qy:
        res["企业同比"] = yoy(bal[qy], months)
        res.setdefault("_balance", {})["企（事）业单位贷款"] = bal[qy]
    # 断点续采：与 prior 逐指标逐月合并，任一侧有值即保留（互补补全）
    if prior:
        pseries = prior.get("series", {})
        pmonths = set(prior.get("periods", []))
        for k, seq in pseries.items():
            if k.startswith("_") or k not in res:
                continue
            for m in pmonths:
                if seq.get(m) is not None and res[k].get(m) is None:
                    res[k][m] = seq[m]
        for bk, bseq in pseries.get("_balance", {}).items():
            if bk in res.get("_balance", {}):
                for m, v in bseq.items():
                    res["_balance"][bk].setdefault(m, v)
        if verbose:
            print("[断点续采] 已并入历史 JSON 的非空值")
    out["series"] = res
    return out


# ---------------------------------------------------------------- 主流程 · NBS 新网关通道
def collect_nbs(n_months=6, end_month=None, verbose=True, prior=None):
    """NBS 侧走 akshare 1.20.39 新网关，信用侧走央行官网统计表。"""
    end = end_month or datetime.now().strftime("%Y-%m")
    months = month_window(n_months, end)
    base_months = month_window(n_months + 12, end)
    bal_years = sorted({int(m[:4]) for m in base_months})
    shr_years = sorted({int(m[:4]) for m in months})
    log = print if verbose else (lambda *a, **k: None)
    out = {"periods": months, "months_requested": n_months,
           "generated_at": datetime.now().isoformat(timespec="seconds"),
           "source": "nbs+pboc", "sources": {}}

    res = {}
    # NBS: PMI / 非制造业 / PPI（period 用最小够用档位，CPI 单独分段）
    per = nbs_period(n_months)
    for name, (path, row_map) in NBS_INDEX.items():
        try:
            df = nbs_fetch(path, per)
        except Exception as e:                      # noqa: BLE001
            log(f"[NBS] {name} 取数失败：{type(e).__name__} {e}")
            df = None
        # PPI 节点返回"上年同月=100"指数，需减 100 转同比；PMI 本身即指数，不减
        seqs = nbs_to_series(df, row_map, months, minus100=(name == "PPI"))
        res.update(seqs)
        hit = max((len(v) for v in seqs.values()), default=0)
        log(f"[NBS] {name}：{hit}/{len(months)} 期（period={per}）")

    # 货币: M1/M2 走 akshare macro_china_money_supply（比 NBS 节点新 1 个月，口径一致）
    try:
        res.update(ak_money_supply_series(months))
        log(f"[akshare] M1/M2 同比：{len(res.get('M1同比', {}))}/{len(months)} 期（央行口径）")
    except Exception as e:                          # noqa: BLE001
        log(f"[akshare] M1/M2 取数失败：{type(e).__name__} {e}")

    # NBS: CPI 分段拼接（新基期优先，旧基期补历史）
    res.update(nbs_cpi_series(months))
    cpi_hit = sum(1 for m in months if res.get("CPI同比", {}).get(m) is not None)
    log(f"[NBS] CPI 分段拼接：CPI同比 {cpi_hit}/{len(months)} 期")
    out["sources"]["NBS"] = {"period": per, "cpi": "LAST120(按基期分段拼接)"}

    # 央行: 信用侧（社融存量/政府债券增速 + 住户/企事业贷款余额 → 自算同比）
    shr, shr_urls = pbc_collect_years(
        shr_years, ["社会融资规模存量", "政府债券"],
        "社会融资规模", "社会融资规模存量统计表", log)
    shr_growth = {k.split("|")[0]: v for k, v in shr.items() if k.endswith("|growth")}
    out["sources"]["社融存量统计表"] = shr_urls
    keys = ["住户贷款", "企（事）业单位贷款", "企(事)业单位贷款"]
    bal, bal_urls = pbc_collect_years(
        bal_years, keys, "金融机构信贷收支统计",
        "金融机构人民币信贷收支表", log)
    out["sources"]["人民币信贷收支表"] = bal_urls
    res["社融存量同比"] = {m: shr_growth.get("社会融资规模存量", {}).get(m) for m in months}
    res["政府同比"] = {m: shr_growth.get("政府债券", {}).get(m) for m in months}
    hh = next((k for k in bal if k.startswith("住户贷款")), None)
    qy = next((k for k in bal if "企" in k and "业单位贷款" in k), None)
    if hh:
        res["居民同比"] = yoy(bal[hh], months)
        res.setdefault("_balance", {})["住户贷款"] = bal[hh]
    if qy:
        res["企业同比"] = yoy(bal[qy], months)
        res.setdefault("_balance", {})["企（事）业单位贷款"] = bal[qy]

    # 数据源标注（每个指标可追溯）
    out["source_map"] = {
        "制造业PMI": "nbs", "生产": "nbs", "新订单": "nbs", "新出口订单": "nbs",
        "非制造业PMI": "nbs", "PPI同比": "nbs", "CPI同比": "nbs", "核心CPI": "nbs",
        "食品烟酒": "nbs", "M1同比": "akshare_money_supply", "M2同比": "akshare_money_supply",
        "社融存量同比": "pboc", "政府同比": "pboc", "居民同比": "pboc", "企业同比": "pboc",
    }

    # 断点续采：与 prior 逐指标逐月合并，任一侧有值即保留
    if prior:
        pseries = prior.get("series", {})
        pmonths = set(prior.get("periods", []))
        for k, seq in pseries.items():
            if k.startswith("_") or k not in res:
                continue
            for m in pmonths:
                if seq.get(m) is not None and res[k].get(m) is None:
                    res[k][m] = seq[m]
        for bk, bseq in pseries.get("_balance", {}).items():
            if bk in res.get("_balance", {}):
                for m, v in bseq.items():
                    res["_balance"][bk].setdefault(m, v)
        if verbose:
            print("[断点续采] 已并入历史 JSON 的非空值")
    out["series"] = res
    return out


# ---------------------------------------------------------------- 主流程 · 分发
def collect(n_months=6, end_month=None, verbose=True, max_pages=None, prior=None, source="nbs"):
    """统一入口：source='nbs' 走 NBS 新网关 + 央行官网；'official' 走纯官网解析。"""
    if source == "official":
        return collect_official(n_months, end_month, verbose, max_pages, prior)
    if source != "nbs":
        raise ValueError(f"未知 source={source!r}，仅支持 'nbs' / 'official'")
    return collect_nbs(n_months, end_month, verbose, prior)


def coverage(res, months):
    """各序列命中率（非空期数 / 请求期数）"""
    rows = [k for k in res if not k.startswith("_")]
    return {k: sum(1 for m in months if res[k].get(m) is not None) for k in rows}


def fmt_table(res, months):
    rows = [k for k in res if not k.startswith("_")]
    lines = []
    lines.append("指标".ljust(12) + "".join(m.rjust(9) for m in months))
    for k in rows:
        cells = []
        for m in months:
            v = res[k].get(m)
            cells.append(("—" if v is None else f"{v:g}").rjust(9))
        lines.append(k.ljust(12) + "".join(cells))
    return "\n".join(lines)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="宏观辅助指标采集器（akshare NBS 新网关 + 央行官网）")
    ap.add_argument("--months", type=int, default=6, help="抓取月数，如 6 / 60（默认 6）")
    ap.add_argument("--end", default=None, help="末月 YYYY-MM，默认当月")
    ap.add_argument("--source", choices=["nbs", "official"], default="nbs",
                    help="取数通道：nbs=akshare 新网关+央行官网（默认）；official=纯官网解析，不依赖 akshare")
    ap.add_argument("--out", default="macro_aux_official.json", help="输出 JSON 路径")
    ap.add_argument("--max-pages", type=int, default=None,
                    help="统计局发布栏目翻页数，默认按 --months 自动推算")
    ap.add_argument("--resume", default=None,
                    help="断点续采：并入已有 JSON 的非空值，多次运行互补补全，抗官网限流")
    ap.add_argument("--quiet", action="store_true", help="静默模式，不打印采集日志")
    a = ap.parse_args()

    prior = None
    if a.resume and os.path.exists(a.resume):
        with open(a.resume, encoding="utf-8") as f:
            prior = json.load(f)
        if not a.quiet:
            print(f"[断点续采] 载入 {os.path.abspath(a.resume)}")
    data = collect(a.months, a.end, verbose=not a.quiet, max_pages=a.max_pages,
                   prior=prior, source=a.source)
    months = data["periods"]
    if not a.quiet:
        print(f"\n=== 采集结果（通道={data.get('source', a.source)}；"
              f"国家统计局 NBS 新网关 / 中国人民银行）===")
        # 月数较多时只打印前 6 与后 6 期，避免刷屏
        if len(months) <= 14:
            print(fmt_table(data["series"], months))
        else:
            view = months[:6] + ["..."] + months[-6:]
            print("指标".ljust(12) + "".join(m.rjust(9) for m in view))
            for k in [k for k in data["series"] if not k.startswith("_")]:
                cells = []
                for m in view:
                    v = data["series"][k].get(m) if m != "..." else None
                    cells.append(("   ...   " if m == "..." else
                                  ("—" if v is None else f"{v:g}")).rjust(9))
                print(k.ljust(12) + "".join(cells))
        cov = coverage(data["series"], months)
        print("\n命中率：" + "  ".join(f"{k}={v}/{len(months)}" for k, v in cov.items()))
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"已写出 {os.path.abspath(a.out)}")
