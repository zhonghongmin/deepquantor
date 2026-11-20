"use client";

import { useEffect, useState } from "react";
import { apiGet } from "@/lib/api";
import { EmptyState } from "@/components/EmptyState";
import type { ApiResponse } from "@/lib/api";
import type { CycleData, DimSeries, MacroData } from "@/services/macro";

/** P10 宏观数据（AD-10）：五区单列，对齐《管理端效果图》#macro。
 *  结论与数据分离；DR001 零输入（D-18）；折线只用真实落库序列，缺期即断开（不补零/不填前值）。 */

const DIM_META: Record<
  string,
  { name: string; cls: string; color: string; icon: string; keyLabel: string; unit: string }
> = {
  growth: { name: "经济 · 产出", cls: "econ", color: "#0ea5e9", icon: "经", keyLabel: "制造业 PMI", unit: "" },
  inflation: { name: "通胀", cls: "inf", color: "#f59e0b", icon: "胀", keyLabel: "CPI 同比", unit: "%" },
  money: { name: "货币", cls: "mon", color: "#6366f1", icon: "币", keyLabel: "M2 同比", unit: "%" },
  credit: { name: "信用", cls: "cred", color: "#10b981", icon: "信", keyLabel: "社融存量 同比", unit: "%" },
};

/** 细项分项明细（效果图 2026-11-21 新版 §1.2.2：仅下传中观、不进状态机；静态展示框架）。 */
const DIM_DETAILS: Record<string, [string, string[]][]> = {
  growth: [
    ["制造业 PMI 分项", ["生产", "新订单", "新出口订单", "原材料库存", "从业人员", "供应商配送时间", "购进价格", "出厂价格"]],
    ["非制造业 PMI 分项", ["商务活动", "新订单", "建筑业新订单与从业人员"]],
    ["综合与结构", ["综合 PMI 产出", "高技术制造", "装备制造", "消费品", "高耗能", "大型/中型/小型企业"]],
    ["增长·量项（验证层）", ["工增分行业", "工业企业利润", "固投：制造/基建/地产", "社零分品类", "高频印证项"]],
  ],
  inflation: [
    ["CPI 八大类", ["食品烟酒", "衣着", "居住", "生活用品及服务", "交通通信", "教育文化娱乐", "医疗保健", "其他"]],
    ["CPI 重点单品", ["猪肉", "鲜菜", "鲜果", "能源燃料", "服务：住宿/机票/旅行社"]],
    ["核心 CPI", ["扣除能源的工业消费品", "服务细分"]],
    ["PPI 生产资料", ["采掘", "原材料", "加工"]],
    ["PPI 生活资料", ["食品", "衣着", "一般日用品", "耐用消费品"]],
    ["PPI 分行业", ["煤炭开采", "石油天然气", "有色冶炼", "化学原料", "电气机械", "计算机通信电子"]],
  ],
  money: [
    ["货币量（唯一主判）", ["M2 同比", "M1 同比", "M1−M2"]],
    ["辅助信号（不参与判定）", ["DR001 绝对水平", "DR001 3 年滚动分位"]],
  ],
  credit: [
    ["社融分项", ["人民币贷款", "政府债", "企业债", "表外", "股票"]],
    ["信贷分项", ["企业中长贷", "居民短贷", "居民中长贷", "票据"]],
    ["结构读法", ["贷款 vs 债券 结构迁移", "住户贷款净增减", "短贷与票据撑量", "企业中长贷占比"]],
  ],
};

const FACTOR_TEXT: Record<string, Record<number, { txt: string; cls: string }>> = {
  growth: { 1: { txt: "↑ 上行", cls: "up" }, [-1]: { txt: "↓ 下行", cls: "dn" }, 0: { txt: "→ 中性", cls: "flat" } },
  inflation: { 1: { txt: "↑ 上行", cls: "up" }, [-1]: { txt: "↓ 下行", cls: "dn" }, 0: { txt: "→ 温和", cls: "flat" } },
  money: { 1: { txt: "↑ 宽货币", cls: "up" }, [-1]: { txt: "↓ 紧货币", cls: "dn" }, 0: { txt: "→ 中性", cls: "flat" } },
  credit: { 1: { txt: "↑ 宽信用", cls: "up" }, [-1]: { txt: "↓ 紧信用", cls: "dn" }, 0: { txt: "→ 中性", cls: "flat" } },
};

/** 货币 × 信用 → 大方向标签（领先层，MC-02）。 */
function bigDirection(money: number, credit: number): { txt: string; cls: string } {
  if (money === 1 && credit === 1) return { txt: "大方向：进攻", cls: "up" };
  if (money === -1 && credit === -1) return { txt: "大方向：防守", cls: "dn" };
  return { txt: "大方向：观望", cls: "" };
}

const MONEY_TXT: Record<number, string> = { 1: "宽货币", [-1]: "紧货币", 0: "中性货币" };
const CREDIT_TXT: Record<number, string> = { 1: "宽信用", [-1]: "紧信用", 0: "中性信用" };
const GROWTH_TXT: Record<number, string> = { 1: "增长 上行", [-1]: "增长 下行", 0: "增长 中性" };
const INFL_TXT: Record<number, string> = { 1: "通胀 上行", [-1]: "通胀 下行", 0: "通胀 温和" };

const ALLOC_META: { key: string; nm: string; color: string }[] = [
  { key: "stock", nm: "股票", color: "#0060c0" },
  { key: "bond", nm: "债券", color: "#0ea5e9" },
  { key: "commodity", nm: "商品（顺周期）", color: "#e08b3c" },
  { key: "gold", nm: "贵金属", color: "#d4a72c" },
  { key: "cash", nm: "现金", color: "#94a3b8" },
];

const REGIME_BG: Record<string, { bg: string; bar: string }> = {
  "复苏": { bg: "rgba(16,185,129,.11)", bar: "#0f9d6e" },
  "过热": { bg: "rgba(245,158,11,.14)", bar: "#d98a00" },
  "滞胀": { bg: "rgba(229,72,77,.10)", bar: "#d0484d" },
  "衰退": { bg: "rgba(59,130,246,.11)", bar: "#3b82f6" },
};

/** 真实 6 期折线（效果图 spark 同构：渐变面积 + 折线 + 逐期标注 + 端点）。 */
function Spark({ vals, color, dec, unit }: { vals: number[]; color: string; dec: number; unit: string }) {
  if (vals.length < 2) return null;
  const W = 300, H = 56, padT = 17, padB = 8, padLR = 9;
  const mn = Math.min(...vals), mx = Math.max(...vals), rng = mx - mn || 1;
  const X = (i: number) => padLR + (i * (W - padLR * 2)) / (vals.length - 1);
  const Y = (v: number) => H - padB - ((v - mn) / rng) * (H - padT - padB);
  const pts = vals.map((v, i) => [X(i), Y(v)] as const);
  const line = pts.map(([x, y], i) => `${i ? "L" : "M"}${x.toFixed(1)} ${y.toFixed(1)}`).join(" ");
  const area = `${line} L${pts[pts.length - 1][0].toFixed(1)} ${H} L${pts[0][0].toFixed(1)} ${H} Z`;
  const gid = `sg-${color.replace("#", "")}`;
  return (
    <svg className="spk" viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" aria-hidden="true">
      <defs>
        <linearGradient id={gid} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor={color} stopOpacity=".24" />
          <stop offset="1" stopColor={color} stopOpacity="0" />
        </linearGradient>
      </defs>
      <path d={area} fill={`url(#${gid})`} />
      <path d={line} fill="none" stroke={color} strokeWidth="2" strokeLinejoin="round" strokeLinecap="round"
        vectorEffect="non-scaling-stroke" />
      {pts.slice(0, -1).map(([x, y], i) => (
        <text key={i} x={x.toFixed(1)} y={(y - 5).toFixed(1)} textAnchor={i === 0 ? "start" : "middle"}
          fontSize="9" fontWeight="500" fill="#94a3b2">
          {vals[i].toFixed(dec)}{unit}
        </text>
      ))}
      <circle cx={pts[0][0].toFixed(1)} cy={pts[0][1].toFixed(1)} r="2.8" fill="#fff" stroke="#c3cedb" strokeWidth="1.6" />
      <circle cx={pts[pts.length - 1][0].toFixed(1)} cy={pts[pts.length - 1][1].toFixed(1)} r="3.4" fill={color} stroke="#fff" strokeWidth="1.8" />
    </svg>
  );
}

/** 末月环比箭头（效果图 dirArrow 同构）：末值 > 前值 ↑；< ↓；相等 →。 */
function dirArrow(vals: number[]): { ch: string; cls: string } {
  if (vals.length < 2) return { ch: "→", cls: "flat" };
  const p = vals[vals.length - 2], c = vals[vals.length - 1];
  return c > p ? { ch: "↑", cls: "up" } : c < p ? { ch: "↓", cls: "dn" } : { ch: "→", cls: "flat" };
}

/** ⑤ 周期回溯：宏观周期背景色带（真实历史批次）× 沪深300 累计涨幅（真实行情）。 */
function CycleChart({ cycle, history }: { cycle: CycleData; history: { asOf: string; regime: string }[] }) {
  const regimeByMonth = new Map(history.map((h) => [h.asOf.slice(0, 7), h.regime]));
  const months = cycle.months, cum = cycle.cum, N = months.length;
  if (N < 2) return null;
  const W = 1200, H = 380, L = 62, R = 1172, T = 40, B = 330;
  const PW = R - L, HH = B - T, step = PW / (N - 1);
  const X = (t: number) => L + t * step;
  const lo = Math.min(0, Math.floor(Math.min(...cum) / 10) * 10 - 5);
  const hi = Math.max(10, Math.ceil(Math.max(...cum) / 10) * 10 + 5);
  const Y = (v: number) => T + ((hi - v) / (hi - lo)) * HH;

  // 周期背景色带：连续同 regime 的月份合并为一段
  const bands: { s: number; e: number; regime: string }[] = [];
  months.forEach((m, t) => {
    const rg = regimeByMonth.get(m) ?? "";
    if (bands.length && bands[bands.length - 1].regime === rg) bands[bands.length - 1].e = t;
    else bands.push({ s: t, e: t, regime: rg });
  });

  const line = cum.map((v, t) => `${t ? "L" : "M"}${X(t).toFixed(1)} ${Y(v).toFixed(1)}`).join(" ");
  const xTicks = [0, 12, 24, 36, 48, N - 1].filter((t, i, a) => t < N && a.indexOf(t) === i);
  const grid: number[] = [];
  for (let v = Math.ceil(lo / 20) * 20; v <= hi; v += 20) grid.push(v);

  return (
    <svg className="cyc-svg" viewBox={`0 0 ${W} ${H}`} role="img" aria-label="近 5 年宏观周期与沪深300 累计涨幅">
      {bands.map((b, i) => {
        const ph = REGIME_BG[b.regime];
        if (!ph) return null;
        const x1 = Math.max(L, X(b.s) - step / 2), x2 = Math.min(R, X(b.e) + step / 2);
        return (
          <g key={i}>
            <rect x={x1.toFixed(1)} y={T} width={(x2 - x1).toFixed(1)} height={HH} fill={ph.bg} />
            <rect x={x1.toFixed(1)} y={T} width={(x2 - x1).toFixed(1)} height="3" fill={ph.bar} opacity=".7" />
            {x2 - x1 > 54 && (
              <text x={((x1 + x2) / 2).toFixed(1)} y={T + 18} textAnchor="middle" fontSize="11.5" fontWeight="700" fill={ph.bar}>
                {b.regime}
              </text>
            )}
          </g>
        );
      })}
      {grid.map((v) => (
        <g key={v}>
          <line x1={L} y1={Y(v).toFixed(1)} x2={R} y2={Y(v).toFixed(1)}
            stroke={v === 0 ? "#94a3b8" : "#eef2f6"} strokeWidth={v === 0 ? 1.4 : 1}
            strokeDasharray={v === 0 ? "6 4" : undefined} />
          <text x={L - 9} y={(Y(v) + 4).toFixed(1)} textAnchor="end" fontSize="11"
            fill={v === 0 ? "#64748b" : "#9aa6b2"} fontWeight={v === 0 ? 600 : 400}>
            {v > 0 ? `+${v}%` : `${v}%`}
          </text>
        </g>
      ))}
      <line x1={L} y1={T} x2={L} y2={B} stroke="#dfe6ee" />
      <line x1={L} y1={B} x2={R} y2={B} stroke="#dfe6ee" />
      {xTicks.map((t) => (
        <text key={t} x={X(t).toFixed(1)} y={B + 20} textAnchor={t === 0 ? "start" : t === N - 1 ? "end" : "middle"}
          fontSize="11" fill="#6b7785">{months[t]}</text>
      ))}
      <path d={line} fill="none" stroke="#0060c0" strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" opacity=".95" />
      <circle cx={X(N - 1).toFixed(1)} cy={Y(cum[N - 1]).toFixed(1)} r="3.6" fill="#0060c0" stroke="#fff" strokeWidth="1.6" />
    </svg>
  );
}

export default function MacroPage() {
  const [data, setData] = useState<MacroData | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [openDim, setOpenDim] = useState<string | null>(null); // ② 弹层：维度 key

  const load = () =>
    apiGet<MacroData>("/api/macro").then((r: ApiResponse<MacroData>) => {
      if (r.code === 0) { setData(r.data); setErr(null); } else setErr(r.message);
    });
  useEffect(() => { load(); }, []);

  const s = data?.signal ?? null;
  const factors = (s?.signalJson?.factors ?? null) as Record<string, number> | null;
  const assetAlloc = (s?.signalJson?.asset_alloc ?? null) as Record<string, number> | null;
  const styleTilt = (s?.signalJson?.style_tilt ?? null) as Record<string, string> | null;
  const phase = (s?.signalJson?.phase as string | undefined) ?? "—";

  // 连续同象限期数（从最新一期往前数）
  const streak = (() => {
    const h = data?.history ?? [];
    if (!h.length) return 0;
    let n = 0;
    for (const x of h) { if (x.regime === h[0].regime) n++; else break; }
    return n;
  })();

  if (err) {
    return (
      <section>
        <div className="page-h"><b>宏观数据</b></div>
        <div className="card"><EmptyState title="数据加载失败" sub={err} />
          <div className="text-center"><button className="btn ghost sm" onClick={() => { setErr(null); load(); }}>重试</button></div>
        </div>
      </section>
    );
  }

  return (
    <section id="macro">
      <div className="sec-bar">
        <h3>① 当前结论 · 周期 / 配置</h3>
        <span className="sec-sub">数据截至 {s?.asOf ?? "—"}（只读 signal.macro_signal，页面不重算）</span>
      </div>

      {!s ? (
        <div className="card mb-4">
          <EmptyState title="暂无已发布宏观信号" sub={`数据截至 ${data ? data.stamp.slice(0, 10) : "—"} · 待 macro-monthly 任务产出首期`} />
        </div>
      ) : (
        <div className="result-hero mb-4">
          <div className="mres-l">
            <div className="mres-eyebrow">两层状态机 → 当前周期结论</div>
            <div className="fr-mini">
              <span className="fr-k">货币 × 信用 <i>第一层 · 领先 · 定大方向</i></span>
              <span className="fr-v">{s.moneyCredit ?? "—"}
                <em>{factors ? `${MONEY_TXT[factors.money]} ＋ ${CREDIT_TXT[factors.credit]}` : ""}</em>
              </span>
              {factors && <span className={`fr-b ${bigDirection(factors.money, factors.credit).cls}`}>{bigDirection(factors.money, factors.credit).txt}</span>}
            </div>
            <div className="fr-mini">
              <span className="fr-k">经济 × 通胀 <i>第二层 · 确认 · 定周期</i></span>
              <span className="fr-v">{s.regime} · {phase}
                <em>{factors ? `${GROWTH_TXT[factors.growth]} · ${INFL_TXT[factors.inflation]}` : ""}</em>
              </span>
              {streak > 0 && <span className="fr-b">连续 {streak} 期同象限</span>}
              {s.confidence != null && (
                <span className={`fr-b ${s.confidence >= 0.99 ? "hi" : ""}`}>
                  置信度 {s.confidence >= 0.99 ? "高" : s.confidence >= 0.6 ? "中" : "低"}
                </span>
              )}
            </div>
          </div>
          <div className="mres-r">
            <div className="mres-eyebrow">资产配置 · 目标风险预算</div>
            <div className="mres-bar">
              {ALLOC_META.map((a) => {
                const pct = Math.round(((assetAlloc?.[a.key] ?? 0) as number) * 1000) / 10;
                return (
                  <div key={a.key} className="mres-seg" style={{ flex: `${pct} 1 0`, background: a.color }}
                    title={`${a.nm} ${pct}%`}>
                    {pct >= 8 ? `${pct}%` : ""}
                  </div>
                );
              })}
            </div>
            <div className="mres-alloc">
              {ALLOC_META.map((a) => {
                const pct = Math.round(((assetAlloc?.[a.key] ?? 0) as number) * 1000) / 10;
                return (
                  <span key={a.key} className="mres-pill">
                    <i style={{ background: a.color }} />{a.nm} <b>{pct}%</b>
                  </span>
                );
              })}
            </div>
            <div className="mres-style">
              <span className="rs-lab">风格偏好</span>
              市值：<b>{styleTilt?.size ?? "—"}</b>　估值：<b>{styleTilt?.value_growth ?? "—"}</b>　属性：<b>{styleTilt?.cycle_defensive ?? "—"}</b>
            </div>
          </div>
        </div>
      )}

      <div className="sec-bar">
        <h3>② 数据支撑 · 近 6 个月走势</h3>
        <span className="sec-sub">预判层指标 · 月频 · 每项真实 6 期（缺期即断开，不补零不填前值）</span>
      </div>
      <div className="grid grid-cols-4 gap-4">
        {Object.keys(DIM_META).map((key) => {
          const meta = DIM_META[key];
          const dim: DimSeries | undefined = (data?.series ?? []).find((x) => x.key === key);
          const ftxt = factors ? FACTOR_TEXT[key]?.[factors[key]] : undefined;
          const vals = dim?.values.map((x) => x.v) ?? [];
          const hasLine = vals.length >= 2;
          const last = vals[vals.length - 1];
          const chg = hasLine ? last - vals[0] : null;
          const ma = dirArrow(vals);
          return (
            <div key={key} className="card dim" style={{ cursor: "pointer" }}
              onClick={() => setOpenDim(key)} role="button" tabIndex={0}
              onKeyDown={(e) => e.key === "Enter" && setOpenDim(key)}>
              <div className="dim-top">
                <span className={`dim-ic ${meta.cls}`}>{meta.icon}</span>
                <span className="dt-nm">{meta.name}</span>
                {ftxt && <span className={`dt-arrow ${ftxt.cls}`}>{ftxt.txt}</span>}
              </div>
              {!hasLine ? (
                <EmptyState title="待数据落库" sub="月度序列待采集任务产出 · 展示保留" />
              ) : (
                <>
                  <div className="spk-row">
                    <span className="spk-lbl">{meta.keyLabel} · 近 {vals.length} 期</span>
                    <span className="spk-now">
                      {last.toFixed(1)}<small>{meta.unit}</small>
                      <i className={`now-arrow ${ma.cls}`}>{ma.ch}</i>
                    </span>
                  </div>
                  <Spark vals={vals} color={meta.color} dec={1} unit={meta.unit} />
                  <div className="spk-x">
                    {dim!.values.map((x) => <span key={x.p}>{x.p.slice(5)}</span>)}
                  </div>
                  {chg != null && (
                    <div className="spk-chg">较 {vals.length} 期前 <b>{chg >= 0 ? "+" : ""}{chg.toFixed(1)}</b></div>
                  )}
                  <table className="dim-t">
                    <tbody>
                      {dim!.subs.map((sub) => (
                        <tr key={sub.name}>
                          <td>{sub.name}</td>
                          <td>
                            {sub.values.length >= 2 ? (
                              <div className="sub-series">
                                {sub.values.map((v, idx) =>
                                  idx === sub.values.length - 1 ? (
                                    <span key="last" className="s-last">
                                      {v.toFixed(sub.dec)}{sub.unit}
                                      <i className={`s-arrow ${dirArrow(sub.values).cls}`}>
                                        {dirArrow(sub.values).ch}
                                      </i>
                                    </span>
                                  ) : (
                                    <span key={idx}>{v.toFixed(sub.dec)}</span>
                                  ),
                                )}
                              </div>
                            ) : (
                              <span className="sub-pending">待采数落库</span>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </>
              )}
            </div>
          );
        })}
      </div>

      {/* ② 分项明细弹层（效果图 openDetail 同构）：§1.2.2 仅下传中观、不进状态机 */}
      {openDim && DIM_DETAILS[openDim] && (
        <>
          <div className="dim-modal-mask" onClick={() => setOpenDim(null)} />
          <div className="dim-modal" role="dialog" aria-modal="true">
            <div className="dim-modal-h">
              <span className={`dim-ic ${DIM_META[openDim].cls}`}>{DIM_META[openDim].icon}</span>
              <span className="dt-nm">{DIM_META[openDim].name}</span>
              {factors && (
                <span className={`dt-arrow ${FACTOR_TEXT[openDim]?.[factors[openDim]]?.cls ?? "flat"}`}>
                  {FACTOR_TEXT[openDim]?.[factors[openDim]]?.txt ?? "—"}
                </span>
              )}
              <button className="dim-modal-x" onClick={() => setOpenDim(null)} aria-label="关闭">×</button>
            </div>
            <div className="dim-modal-sub">
              {DIM_META[openDim].keyLabel} · 近 6 个月 · 完整分项明细（§1.2.2，仅下传中观、不进状态机）
            </div>
            {DIM_DETAILS[openDim].map(([g, items]) => (
              <div key={g} className="md-grp">
                <div className="md-grp-h">{g}</div>
                <div className="md-items">
                  {items.map((x) => <span key={x}>{x}</span>)}
                </div>
              </div>
            ))}
          </div>
        </>
      )}

      <div className="sec-bar">
        <h3>③ 日频辅助预警</h3>
        <span className="sec-sub">每日更新 · 预警信号明细</span>
      </div>
      <div className="card">
        {/* D-30 后移本期不实现：区域保留空态占位，不落数据行（对账 MA-4） */}
        <EmptyState title="后续迭代 · D-30" sub="warn_flags 落库与日频预警展示随 D-30 后移，本期不实现" />
      </div>

      <div className="sec-bar">
        <h3>④ 预测信号（领先窗口）</h3>
        <span className="sec-sub">基于已发布细项，推测下月增长 / 通胀 / 货币 / 信用主要指标</span>
      </div>
      <div className="grid grid-cols-4 gap-4">
        {Object.keys(DIM_META).map((key) => {
          const meta = DIM_META[key];
          const ftxt = factors ? FACTOR_TEXT[key]?.[factors[key]] : undefined;
          const detail: Record<string, string> = {
            growth: "制造业 PMI · 非制造业 PMI",
            inflation: "CPI 同比 · PPI 同比",
            money: "M1 同比 · M2 同比 · M1−M2",
            credit: "社融存量同比 · 新增贷款同比多增",
          };
          const main: Record<string, string> = {
            growth: "PMI（预判层主判）· GDP（验证层）",
            inflation: "CPI · PPI（领先方向）",
            money: "M2 同比 · M1−M2（量唯一主判）",
            credit: "社融存量同比 · 贷款（企业中长贷）",
          };
          return (
            <div key={key} className="fc-card">
              <div className="fc-top">
                <span className="fc-dim">{meta.name.replace(" · 产出", "")}</span>
                {ftxt
                  ? <span className={`fc-tag ${ftxt.cls}`}>{ftxt.txt.replace(/^[↑↓→] /, "")}</span>
                  : <span className="fc-tag flat">—</span>}
              </div>
              <div className="fc-row"><span className="fc-k">主要指标</span><span className="fc-v">{main[key]}</span></div>
              <div className="fc-row"><span className="fc-k">细项支撑</span><span className="fc-v">已发布：{detail[key]}</span></div>
              <div className="fc-pred">
                <b>下月推测：待回测 · 暂不推测</b>
                <br />hit_rate_status = pending（只读派生，不写回信号）
              </div>
            </div>
          );
        })}
      </div>

      <div className="sec-bar">
        <h3>⑤ 周期回溯 · 近 5 年</h3>
        <span className="sec-sub">宏观周期 × 沪深300 累计涨幅 · 60 个月 · 起点归一 0%</span>
      </div>
      <div className="cyc-wrap">
        {data?.cycle && data.cycle.months.length >= 12 && data.history.length > 0 ? (
          <>
            <div className="cyc-head">
              <div className="ch-l">
                <b>宏观周期 × 沪深300 走势</b><br />
                {data.cycle.months[0]} ~ {data.cycle.months[data.cycle.months.length - 1]} · {data.cycle.months.length} 个月 ·
                背景色带为当期周期判断（历史批次回溯 · 不参与判定）
              </div>
              <div className="cyc-legends">
                <div className="lg-group">
                  <span className="lg-cap">指数 · 真实行情</span>
                  <span className="lg"><i className="sw" style={{ borderTopColor: "#0060c0" }} />沪深300</span>
                </div>
                <div className="lg-group">
                  <span className="lg-cap">周期背景</span>
                  {Object.entries(REGIME_BG).map(([rg, ph]) => (
                    <span key={rg} className="lg"><i className="ph" style={{ background: ph.bg, borderColor: ph.bar }} />{rg}</span>
                  ))}
                </div>
              </div>
            </div>
            <CycleChart cycle={data.cycle} history={data.history} />
          </>
        ) : (
          <EmptyState
            title="待回测"
            sub={`已积累 ${data?.history.length ?? 0} / 60 期信号 · 历史批次随 macro-monthly 持续产出`}
          />
        )}
      </div>
    </section>
  );
}
