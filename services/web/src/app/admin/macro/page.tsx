"use client";

import { useEffect, useState } from "react";
import { apiGet } from "@/lib/api";
import { EmptyState } from "@/components/EmptyState";
import type { ApiResponse } from "@/lib/api";
import type { MacroData } from "@/services/macro";

/** P10 宏观数据（AD-10）：五区单列。结论与数据分离；DR001 零输入（D-18）。 */

const NINE_STATES = [
  ["宽货币", "宽信用", "双宽"], ["宽货币", "中性信用", "宽货币·中性信用"], ["宽货币", "紧信用", "宽货币紧信用"],
  ["中性货币", "宽信用", "中性货币·宽信用"], ["中性货币", "中性信用", "中性·中性"], ["中性货币", "紧信用", "中性货币紧信用"],
  ["紧货币", "宽信用", "紧货币宽信用"], ["紧货币", "中性信用", "紧货币·中性信用"], ["紧货币", "紧信用", "双紧"],
];

const DIMS = [
  { key: "growth", name: "经济 · 产出", icon: "📈" },
  { key: "inflation", name: "通胀", icon: "🌡" },
  { key: "money", name: "货币", icon: "💰" },
  { key: "credit", name: "信用", icon: "🏦" },
];

export default function MacroPage() {
  const [data, setData] = useState<MacroData | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const load = () =>
    apiGet<MacroData>("/api/macro").then((r: ApiResponse<MacroData>) => {
      if (r.code === 0) { setData(r.data); setErr(null); } else setErr(r.message);
    });
  useEffect(() => { load(); }, []);

  const s = data?.signal;
  const factors = (s?.signalJson?.factors ?? null) as Record<string, number> | null;

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

      <div className="card mb-4">
        {!s ? (
          <EmptyState title="暂无已发布宏观信号" sub={`数据截至 ${data ? data.stamp.slice(0, 10) : "—"} · 待 macro-monthly 任务产出首期`} />
        ) : (
          <div className="grid grid-cols-2 gap-4">
            <div>
              <div className="text-[11px] text-muted2 mb-1">两层状态机 → 当前周期结论</div>
              <div className="foot-note !mb-2">
                <b>货币 × 信用</b>（第一层 · 领先 · 定大方向）：{s.moneyCredit ?? "—"}
              </div>
              <div className="foot-note">
                <b>经济 × 通胀</b>（第二层 · 确认 · 定周期）：{s.regime}
                {s.confidence != null && <> · 置信度 {s.confidence >= 0.99 ? "高" : s.confidence >= 0.6 ? "中" : "低"}</>}
              </div>
            </div>
            <div>
              <div className="text-[11px] text-muted2 mb-1">资产配置 · 目标风险预算</div>
              <div className="qgrid">
                {NINE_STATES.map(([m, c, key]) => (
                  <div key={key} className={`qcell ${key === s.moneyCredit ? "cur" : ""}`}>
                    {m}<br />{c}<small>{key}</small>
                  </div>
                ))}
              </div>
              <div className="text-[11px] text-muted2 mt-1">纵轴 货币 · 横轴 信用 · 九格＝3×3 九态流动性条件</div>
            </div>
          </div>
        )}
      </div>

      <div className="sec-bar">
        <h3>② 数据支撑 · 近 6 个月走势</h3>
        <span className="sec-sub">预判层指标 · 月频 · 每项 6 期方向</span>
      </div>
      <div className="grid grid-cols-4 gap-4">
        {DIMS.map((d) => {
          const dir = factors ? factors[d.key] : null;
          return (
            <div key={d.key} className="card">
              <div className="flex items-center gap-2 mb-2">
                <span>{d.icon}</span><b className="text-[14px] text-navy">{d.name}</b>
                {dir != null && (
                  <span className={`tag ${dir > 0 ? "ok" : dir < 0 ? "bad" : "gray"}`}>
                    {dir > 0 ? "上行" : dir < 0 ? "下行" : "中性"}
                  </span>
                )}
              </div>
              {/* 近 6 月走势折线：依赖宏观 15 项采集落库；未落库保留区块 + 空态（对账 MA-3） */}
              {dir == null ? (
                <EmptyState title="待数据落库" sub="月度序列待采集任务产出 · 展示保留" />
              ) : (
                <svg viewBox="0 0 120 40" className="w-full h-[40px]">
                  <line x1="0" y1="38" x2="120" y2="38" stroke="var(--line)" />
                  <circle cx="6" cy={dir > 0 ? 34 : 8} r="2.5" fill="var(--muted2)" />
                  <circle cx="114" cy={dir > 0 ? 6 : 34} r="3" fill={dir > 0 ? "var(--red)" : "var(--green)"} />
                  <line x1="6" y1={dir > 0 ? 34 : 8} x2="114" y2={dir > 0 ? 6 : 34}
                    stroke={dir > 0 ? "var(--red)" : "var(--green)"} strokeWidth="1.6" />
                </svg>
              )}
            </div>
          );
        })}
      </div>

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
        {["增长", "通胀", "货币", "信用"].map((dim) => (
          <div key={dim} className="card">
            <div className="flex items-center justify-between mb-2">
              <b className="text-[14px] text-navy">{dim}</b>
              <span className="tag gray">pending</span>
            </div>
            <EmptyState title="待回测 · 暂不推测" sub="hit_rate_status = pending（只读派生，不写回信号）" />
          </div>
        ))}
      </div>

      <div className="sec-bar">
        <h3>⑤ 周期回溯 · 近 5 年</h3>
        <span className="sec-sub">宏观周期 × 主要指数累计涨幅 · 60 个月</span>
      </div>
      <div className="card">
        {(data?.history.length ?? 0) < 60 ? (
          <EmptyState
            title="待回测"
            sub={`已积累 ${data?.history.length ?? 0} / 60 期信号 · 历史批次随 macro-monthly 持续产出`}
          />
        ) : (
          <div className="foot-note">周期回溯图渲染（60 期已齐）</div>
        )}
      </div>
    </section>
  );
}
