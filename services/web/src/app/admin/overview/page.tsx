"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { apiGet } from "@/lib/api";
import { EmptyState } from "@/components/EmptyState";
import type { ApiResponse } from "@/lib/api";
import type { OverviewData } from "@/services/overview";

function fmtStamp(iso: string): string {
  const d = new Date(iso);
  return `${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")} ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}

export default function OverviewPage() {
  const [data, setData] = useState<OverviewData | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const load = () =>
    apiGet<OverviewData>("/api/overview").then((r: ApiResponse<OverviewData>) => {
      if (r.code === 0) setData(r.data);
      else setErr(r.message);
    });

  useEffect(() => {
    load();
  }, []);

  if (err) {
    return (
      <section>
        <div className="page-h"><b>概览</b></div>
        <div className="card">
          <EmptyState title="数据加载失败，点击重试" sub={err} />
          <div className="text-center">
            <button className="btn ghost sm" onClick={() => { setErr(null); load(); }}>重试</button>
          </div>
        </div>
      </section>
    );
  }

  if (!data) {
    return (
      <section>
        <div className="page-h"><b>概览</b></div>
        <div className="layer-row">
          {[1, 2, 3].map((i) => (
            <div key={i} className="layer off"><div className="lbody mute">加载中…</div></div>
          ))}
        </div>
      </section>
    );
  }

  const l1 = data.l1;
  return (
    <section id="overview">
      <div className="page-h" style={{ justifyContent: "flex-end" }}>
        <span className="pill">数据截至 {data.available ? fmtStamp(data.stamp) : "—"}</span>
      </div>
      {/* 三层数据链路卡：全页只有这一行卡片（P1 布局铁律） */}
      <div className="layer-row">
        <div className="layer on">
          <div className="lhd">
            <span className="lnum">L1</span>
            <b>宏观</b>
            {l1 && <span className={`tag ${l1.state === "运行中" ? "ok" : "warn"}`}>{l1.state}</span>}
            {!l1 && <span className="tag bad">缺失</span>}
          </div>
          <div className="lbody">
            {l1 ? (
              <>
                <div className="li"><b>{l1.total}</b><span>数据项</span></div>
                <div className="li"><b className="green">{l1.ok}</b><span>正常</span></div>
                <div className="li"><b className="amber">{l1.gap}</b><span>期待补</span></div>
              </>
            ) : (
              <EmptyState title="宏观数据项未初始化" sub="请先在数据管理页登记数据项" />
            )}
          </div>
          <div className="lfoot">
            <span>{l1?.lastFetchAt ? `最近更新 ${fmtStamp(l1.lastFetchAt)}` : "最近更新 —"}</span>
            <Link className="lk" href="/admin/monitor">运维监控 →</Link>
          </div>
        </div>
        <div className="layer off">
          <div className="lhd"><span className="lnum">L2</span><b>中观</b><span className="tag gray">未接入</span></div>
          <div className="lbody mute">行业景气 · 产业链上下游 · 板块资金</div>
          <div className="lfoot"><span>暂无采集任务</span></div>
        </div>
        <div className="layer off">
          <div className="lhd"><span className="lnum">L3</span><b>微观</b><span className="tag gray">未接入</span></div>
          <div className="lbody mute">六维因子 · 行业综合评分优先 · 个股与行业 ETF 同级</div>
          <div className="lfoot"><span>暂无采集任务</span></div>
        </div>
      </div>
    </section>
  );
}
