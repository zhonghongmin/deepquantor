"use client";

import { useEffect, useMemo, useState } from "react";
import { apiGet } from "@/lib/api";
import { EmptyState } from "@/components/EmptyState";
import type { ApiResponse } from "@/lib/api";
import type { MonitorData, MonitorItem } from "@/services/monitor";

const STATUS_LABEL = { ok: ["正常", "tag ok"], gap: ["待补", "tag warn"], no_data: ["无数据", "tag bad"] } as const;

function fmtStamp(iso: string): string {
  const d = new Date(iso);
  return `${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")} ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}

export default function MonitorPage() {
  const [data, setData] = useState<MonitorData | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [filter, setFilter] = useState<"" | MonitorItem["status"]>("");

  const load = () =>
    apiGet<MonitorData>("/api/monitor").then((r: ApiResponse<MonitorData>) => {
      if (r.code === 0) { setData(r.data); setErr(null); } else setErr(r.message);
    });

  useEffect(() => { load(); }, []);

  const stats = useMemo(() => {
    const items = data?.items ?? [];
    const gapItems = items.filter((i) => i.status === "gap");
    const noData = items.filter((i) => i.status === "no_data");
    return {
      total: items.length,
      ok: items.filter((i) => i.status === "ok").length,
      gapPeriods: gapItems.reduce((s, i) => s + i.gapPeriods, 0),
      gapItems: gapItems.length,
      noData: noData.length,
    };
  }, [data]);

  const shown = (data?.items ?? []).filter((i) => !filter || i.status === filter);

  if (err) {
    return (
      <section>
        <div className="page-h"><b>运维监控 · 宏观采集监控</b></div>
        <div className="card">
          <EmptyState title="数据加载失败" sub={err} />
          <div className="text-center">
            <button className="btn ghost sm" onClick={() => { setErr(null); load(); }}>重试</button>
          </div>
        </div>
      </section>
    );
  }

  return (
    <section id="monitor">
      <div className="page-h" style={{ justifyContent: "flex-end" }}>
        <button className="btn ghost" onClick={load}>刷新元数据</button>
      </div>

      {/* 状态条 4 计数（与 #overview 同源） */}
      <div className="stat-strip">
        <span className="it"><span>监测</span><b className="n">{stats.total}</b><span>项</span></span>
        <span className="vline" />
        <span className="it"><i className="dot ok" /><span>正常</span><b className="n green">{stats.ok}</b><span>项</span></span>
        <span className="vline" />
        <span className="it">
          <i className={`dot ${stats.gapItems > 0 ? "warn" : "ok"}`} />
          <span>待补</span><b className="n amber">{stats.gapPeriods}</b><span>期</span>
          <span>·</span><b className="n amber">{stats.gapItems}</b><span>项</span>
        </span>
        {stats.noData > 0 && (
          <span className="it" style={{ marginLeft: 16 }}>
            <i className="dot bad" /><span>其中</span><b className="n red">{stats.noData}</b><span>项无任何数据</span>
          </span>
        )}
        <span className="tip">数据截至 {data?.available ? fmtStamp(data.stamp) : "—"}</span>
      </div>

      <div className="card" style={{ marginBottom: 16 }}>
        <h3>数据项</h3>
        {/* 增量下载操作条（P2：系统自算缺口，一键补齐；勾选机制退出） */}
        <div className="dl-bar">
          <button
            className="btn sm grow"
            disabled={stats.gapItems === 0}
            title={stats.gapItems === 0 ? "全部数据项已是最新，无缺口" : ""}
            onClick={() => alert(`将对 ${stats.gapItems} 项滞后数据发起增量下载，共补 ${stats.gapPeriods} 期（只拉缺失期次 · 幂等跳过 · 不写空值）`)}
          >
            {stats.gapItems > 0
              ? `增量下载全部待补（${stats.gapItems} 项 / ${stats.gapPeriods} 期）`
              : "全部数据项已是最新，无缺口"}
          </button>
          <span className="right">只拉缺失期次 · 幂等跳过 · 不写空值</span>
        </div>
        <div className="dl-bar">
          <span className="grp">状态筛选
            <select style={{ minWidth: 96 }} value={filter} onChange={(e) => setFilter(e.target.value as typeof filter)}>
              <option value="">全部</option>
              <option value="ok">正常</option>
              <option value="gap">待补</option>
              <option value="no_data">无数据</option>
            </select>
          </span>
        </div>
        {data?.available && data.items.length === 0 ? (
          <EmptyState title="暂无数据项" sub="请先在数据管理页登记宏观 15 项（数据策略 §1.2）" />
        ) : (
          <div className="tscroll">
            <table className="stacktable">
              <thead>
                <tr>
                  <th>数据项</th><th>频率</th><th>库内最新期次</th>
                  <th title="按官方发布日历推算的最新已发布期次；尚未发布则停留在上一期">官方最新可获取 ⓘ</th>
                  <th>待补</th><th>最近采集时间</th><th>状态</th>
                </tr>
              </thead>
              <tbody>
                {shown.map((i) => {
                  const [label, cls] = STATUS_LABEL[i.status];
                  return (
                    <tr key={i.id}>
                      <td data-l="数据项"><b>{i.name}</b></td>
                      <td data-l="频率">{i.freq}</td>
                      <td data-l="库内最新期次" className="mono">{i.latestPeriod ?? "—"}</td>
                      <td data-l="官方最新可获取" className="mono">{i.officialLatest ?? "—"}</td>
                      <td data-l="待补" className={i.gapPeriods > 0 ? "amber" : ""}>{i.gapPeriods}</td>
                      <td data-l="最近采集时间" className="mono">{i.lastFetchAt ? fmtStamp(i.lastFetchAt) : "—"}</td>
                      <td data-l="状态"><span className={cls}>{label}</span></td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </section>
  );
}
