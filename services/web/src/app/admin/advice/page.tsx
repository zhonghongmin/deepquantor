"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { apiGet } from "@/lib/api";
import { EmptyState } from "@/components/EmptyState";
import type { ApiResponse } from "@/lib/api";
import type { AdviceData } from "@/services/advice";

/** P6 投资建议（AD-08）：两段式。① 周期结论条 → ② 大类资产配置。宏观原始数据已迁至 #macro（D-19）。 */

const NINE_STATES = [
  ["宽货币", "宽信用", "双宽"], ["宽货币", "中性信用", "宽货币·中性信用"], ["宽货币", "紧信用", "宽货币紧信用"],
  ["中性货币", "宽信用", "中性货币·宽信用"], ["中性货币", "中性信用", "中性·中性"], ["中性货币", "紧信用", "中性货币紧信用"],
  ["紧货币", "宽信用", "紧货币宽信用"], ["紧货币", "中性信用", "紧货币·中性信用"], ["紧货币", "紧信用", "双紧"],
];

const ASSET_NAMES: Record<string, string> = {
  stock: "股票", bond: "债券", commodity: "商品（顺周期）", gold: "贵金属", cash: "现金",
};

export default function AdvicePage() {
  const [data, setData] = useState<AdviceData | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<string | null>(null);

  const load = () =>
    apiGet<AdviceData>("/api/advice").then((r: ApiResponse<AdviceData>) => {
      if (r.code === 0) { setData(r.data); setErr(null); } else setErr(r.message);
    });
  useEffect(() => { load(); }, []);

  const s = data?.signal;
  const alloc = s?.assetAlloc ?? null;
  const entries = alloc
    ? (["stock", "bond", "commodity", "gold", "cash"] as const).map((k) => ({
        key: k, name: ASSET_NAMES[k], pct: Math.round((alloc[k] ?? 0) * 10000) / 100,
      }))
    : null;

  if (err) {
    return (
      <section>
        <div className="page-h"><b>投资建议（对内版）</b></div>
        <div className="card"><EmptyState title="数据加载失败" sub={err} />
          <div className="text-center"><button className="btn ghost sm" onClick={() => { setErr(null); load(); }}>重试</button></div>
        </div>
      </section>
    );
  }

  return (
    <section id="advice">
      <div className="page-h" style={{ justifyContent: "space-between", alignItems: "center" }}>
        <Link className="lk" href="/admin/macro">查看宏观数据 →</Link>
        <button className="btn ghost">回看历史批次 ▾</button>
      </div>

      {/* ① 周期结论条（hero）：先看周期结论，再看资产配置 */}
      <div className="card mb-4">
        {!s ? (
          <EmptyState title="暂无已发布宏观信号" sub="待 macro-monthly 任务产出首期 · 数据不编造" />
        ) : (
          <div className="grid grid-cols-2 gap-4">
            <div>
              <div className="text-[11px] text-muted2">宏观周期研判 · 批次数据截至 {s.asOf}</div>
              <div className="text-[26px] font-bold text-navy my-1">
                {s.regime}{s.phase ? ` · ${s.phase}` : ""}
                {s.unconfirmed && <span className="tag warn ml-2">政策发力 · 待经济确认</span>}
              </div>
              <div className="flex items-center gap-2 flex-wrap text-[13px]">
                <span className="pill">{(s.moneyCredit ?? "").split("·")[0] || "—"}</span>
                <span className="text-muted2">×</span>
                <span className="pill">{(s.moneyCredit ?? "").split("·")[1] || "—"}</span>
                <span className="text-[12px] text-muted">仅表示流动性条件，不等价于周期判定</span>
              </div>
              {s.sayings.length > 0 && (
                <div className="foot-note mt-2">{s.sayings.join("；")}</div>
              )}
            </div>
            <div>
              <div className="qgrid">
                {NINE_STATES.map(([m, c, key]) => (
                  <div key={key} className={`qcell ${key === s.moneyCredit ? "cur" : ""}`}>
                    {m}<br />{c}<small>{key}</small>
                  </div>
                ))}
              </div>
              <div className="text-[11px] text-muted2 mt-1">纵轴 货币 · 横轴 信用 · 九格＝3×3 九态流动性条件（非经济周期）</div>
            </div>
          </div>
        )}
      </div>

      <div className="sec-bar">
        <h3>大类资产配置</h3>
        <span className="sec-sub">
          {s ? `${s.regime}${s.phase ? ` · ${s.phase}` : ""} × ${s.moneyCredit ?? ""} 的基准配置` : ""} ·
          <b> 五项合计 100%</b>（含商品占位 0%）· 五类为<b>目标风险预算</b>、非实际持仓 · 股票仓位恒等于权益中枢
        </span>
      </div>

      {/* 当前可执行结论条（C-13：预算 vs 实际持仓） */}
      {s?.equityWeight != null && (
        <div style={{
          display: "flex", alignItems: "center", gap: 16, flexWrap: "wrap",
          background: "linear-gradient(135deg,#0a2a4e 0%,#123f70 55%,#1a5089 100%)",
          color: "#fff", borderRadius: 12, padding: "15px 20px", margin: "0 0 14px",
        }}>
          <div style={{ minWidth: 168 }}>
            <div style={{ fontSize: 11, opacity: 0.8, letterSpacing: 0.6 }}>当前可执行 · 本期实际资金</div>
            <div style={{ fontSize: 23, fontWeight: 800, lineHeight: 1.3, marginTop: 2 }}>
              股票 {Math.round(s.equityWeight * 100)}% <span style={{ opacity: 0.6, fontWeight: 400 }}>＋</span> 货币资金 {100 - Math.round(s.equityWeight * 100)}%
            </div>
          </div>
          <div style={{ flex: 1, minWidth: 250, fontSize: 12, lineHeight: 1.7, opacity: 0.92, borderLeft: "1px solid rgba(255,255,255,.28)", paddingLeft: 16 }}>
            五类占比为<b>目标风险预算</b>，不等于实际持仓。本期仅<b>股票线</b>产出 A 股 ETF + 个股交易指令；
            其余资产目标额度<b>暂以货币资金持有</b>，随 G-9 各资产线启用后<b>等额归位</b>。
          </div>
        </div>
      )}

      {/* ② 占比条 + 5 张资产卡（卡内不含理由文本；点击后才出下钻） */}
      {entries ? (
        <div className="alloc-wrap">
          <div className="alloc-bar">
            {entries.map((e) => (
              <div key={e.key} style={{ width: `${e.pct}%`, background: e.key === "stock" ? "var(--blue)" : e.key === "bond" ? "var(--navy)" : e.key === "gold" ? "var(--amber)" : e.key === "cash" ? "#9aa6b2" : "var(--line)" }} />
            ))}
          </div>
          <div className="alloc-grid">
            {entries.map((e) => (
              <div
                key={e.key}
                className="alloc-card"
                onClick={() => e.key === "stock" && setExpanded(expanded === "stock" ? null : "stock")}
              >
                <div className="text-[12px] text-muted">{e.name}</div>
                <div className="pct">{e.pct}%</div>
                <div className="text-[11px] text-muted2">
                  {e.key === "stock" ? "A 股 ETF + 个股" : "目标额度 · 本期暂以货币资金持有"}
                </div>
              </div>
            ))}
          </div>
          <div className="foot-note mt-2">
            点击股票卡展开行业 Top-5 / 个股六维；其余四类展示目标额度与资金落地说明（本期无实际标的）
          </div>
          {expanded === "stock" && (
            <div className="card mt-2">
              <EmptyState title="下钻理由链待接入" sub={`RK 总装启用后展开行业 Top-5 → 个股五维 · 数据截至 ${s?.asOf ?? "—"}`} />
            </div>
          )}
        </div>
      ) : (
        <div className="card">
          <EmptyState title="暂无配置数据" sub={`数据截至 ${data ? data.stamp.slice(0, 10) : "—"}`} />
        </div>
      )}

      {/* 迁移负断言（AD-08 验收②）：本页不出现 4 张维度卡 / 近 6 月折线 / 5 年回溯图 */}
    </section>
  );
}
