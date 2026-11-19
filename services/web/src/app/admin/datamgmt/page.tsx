"use client";

import { useEffect, useState } from "react";
import { apiGet, apiPost, apiDelete } from "@/lib/api";
import { EmptyState } from "@/components/EmptyState";
import type { ApiResponse } from "@/lib/api";
import type { DataMgmtData, DataItemRow, JobRow } from "@/services/datamgmt";

/** P3 数据管理（AD-02 / SC-06 / DL-05）：数据项 / 定时任务两 Tab，唯一数据资产写入口。 */

interface RefRow { usedBy: string; kind: string; note: string | null }

export default function DataMgmtPage() {
  const [tab, setTab] = useState<"items" | "jobs">("items");
  const [data, setData] = useState<DataMgmtData | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [cat, setCat] = useState("");
  const [freq, setFreq] = useState("");
  const [layer, setLayer] = useState("");
  const [kw, setKw] = useState("");
  const [editing, setEditing] = useState<DataItemRow | null>(null);
  const [creating, setCreating] = useState(false);
  const [toast, setToast] = useState<string | null>(null);
  const [refModal, setRefModal] = useState<{ item: DataItemRow; refs: RefRow[] } | null>(null);
  const [confirmDelete, setConfirmDelete] = useState<DataItemRow | null>(null);

  const load = () =>
    apiGet<DataMgmtData>("/api/datamgmt/items").then((r: ApiResponse<DataMgmtData>) => {
      if (r.code === 0) { setData(r.data); setErr(null); } else setErr(r.message);
    });
  useEffect(() => { load(); }, []);

  const shown = (data?.items ?? []).filter((i) => {
    if (cat && !i.name.includes(cat.replace("宏观", "")) && !i.name.includes(cat)) return false;
    if (freq && i.freq !== freq) return false;
    if (layer) {
      const m = { 宏观: "macro", 中观: "meso", 微观: "micro" }[layer];
      if (i.factorLayer !== m) return false;
    }
    if (kw && !i.name.includes(kw) && !i.field.includes(kw)) return false;
    return true;
  });

  const askDelete = async (item: DataItemRow) => {
    const r = await apiGet<{ refs: RefRow[] }>(`/api/datamgmt/items/delete?id=${encodeURIComponent(item.id)}`);
    if (r.code === 0 && r.data.refs.length > 0) {
      setRefModal({ item, refs: r.data.refs }); // 分支 A：有引用即拒绝
    } else {
      setConfirmDelete(item); // 分支 B：无引用，二次确认
    }
  };

  const doDelete = async (item: DataItemRow) => {
    const r = await apiDelete("/api/datamgmt/items", { id: item.id });
    setToast(r.message);
    setConfirmDelete(null);
    load();
  };

  const fmt = (iso: string) => {
    const d = new Date(iso);
    return `${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")} ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
  };

  if (err) {
    return (
      <section>
        <div className="page-h"><b>数据管理</b></div>
        <div className="card"><EmptyState title="数据加载失败" sub={err} />
          <div className="text-center"><button className="btn ghost sm" onClick={() => { setErr(null); load(); }}>重试</button></div>
        </div>
      </section>
    );
  }

  return (
    <section id="datamgmt">
      <div className="tabs">
        <button className={tab === "items" ? "active" : ""} onClick={() => setTab("items")}>数据项</button>
        <button className={tab === "jobs" ? "active" : ""} onClick={() => setTab("jobs")}>定时任务</button>
      </div>

      {tab === "items" && (
        <div id="dmTab-items">
          <div className="dl-bar">
            <span className="grp">类别
              <select style={{ minWidth: 120 }} value={cat} onChange={(e) => setCat(e.target.value)}>
                <option value="">全部</option><option>国内宏观</option><option>海外宏观</option>
              </select></span>
            <span className="grp">频率
              <select style={{ minWidth: 96 }} value={freq} onChange={(e) => setFreq(e.target.value)}>
                <option value="">全部</option><option>日频</option><option>周频</option><option>月频</option><option>季频</option>
              </select></span>
            <span className="grp">因子层级
              <select style={{ minWidth: 96 }} value={layer} onChange={(e) => setLayer(e.target.value)}>
                <option value="">全部</option><option>宏观</option><option>中观</option><option>微观</option>
              </select></span>
            <input type="text" placeholder="搜索数据项 / 字段…" style={{ minWidth: 190 }}
              value={kw} onChange={(e) => setKw(e.target.value)} />
            <button className="btn sm" onClick={() => setCreating(true)}>新增数据项</button>
            <span className="right">共 <b>{shown.length}</b> 项{layer === "中观" ? "（中观层尚未接入数据）" : ""}</span>
          </div>
          <div className="card">
            {data?.available && data.items.length === 0 ? (
              <EmptyState title="当前筛选下没有数据项" sub={`数据截至 ${data ? fmt(data.stamp) : "—"}`} />
            ) : (
              <div className="tscroll">
                <table className="stacktable">
                  <thead>
                    <tr>
                      <th>数据项</th><th>字段</th><th>频率</th><th>因子层级</th><th>数据源接口</th>
                      <th>公布时间</th><th>归属任务</th><th>已落库</th><th style={{ textAlign: "right" }}>操作</th>
                    </tr>
                  </thead>
                  <tbody>
                    {shown.map((i) => (
                      <tr key={i.id}>
                        <td data-l="数据项"><b>{i.name}</b></td>
                        <td data-l="字段" className="mono">{i.field}</td>
                        <td data-l="频率">{i.freq}</td>
                        <td data-l="因子层级">
                          {i.factorLayer ? { macro: "宏观", meso: "中观", micro: "微观" }[i.factorLayer] ?? i.factorLayer : "—"}
                        </td>
                        <td data-l="数据源接口" className="mono">{i.api ?? "—"}</td>
                        <td data-l="公布时间">{i.publishSlot ?? "—"}</td>
                        <td data-l="归属任务">{i.jobCode ?? "未挂载"}</td>
                        <td data-l="已落库">{i.rows > 0 ? `${i.rows} 行` : "—"}</td>
                        <td data-l="操作" style={{ textAlign: "right", whiteSpace: "nowrap" }}>
                          <button className="btn ghost sm" onClick={() => setEditing(i)}>编辑</button>{" "}
                          <button className="btn ghost sm" onClick={() => askDelete(i)}>删除</button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </div>
      )}

      {tab === "jobs" && (
        <div id="dmTab-jobs">
          <div className="dl-bar">
            <span className="right">共 <b>{data?.jobs.length ?? 0}</b> 个任务 · 同机构同时点发布的数据项归为一个任务</span>
          </div>
          <div className="card">
            {(data?.jobs.length ?? 0) === 0 ? (
              <EmptyState title="暂无定时任务" sub="任务定义唯一权威为 deploy/scheduler/jobs.yaml，经 register_jobs.py 登记" />
            ) : (
              <div className="tscroll">
                <table className="stacktable">
                  <thead>
                    <tr>
                      <th>任务</th><th>发布机构</th><th>覆盖数据项</th><th>执行时点</th>
                      <th>下次执行</th><th>最近执行</th><th style={{ textAlign: "right" }}>操作</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(data?.jobs ?? []).map((j: JobRow) => (
                      <tr key={j.jobKey}>
                        <td data-l="任务"><b>{j.jobName}</b> <span className="mono">{j.jobKey}</span></td>
                        <td data-l="发布机构">—</td>
                        <td data-l="覆盖数据项">—</td>
                        <td data-l="执行时点" className="mono">{j.cronExpr ?? "—"}</td>
                        <td data-l="下次执行">—</td>
                        <td data-l="最近执行">
                          {j.lastRun ? (
                            <>
                              <span className={`tag ${j.lastRun.status === "success" ? "ok" : "bad"}`}>{j.lastRun.status}</span>{" "}
                              <span className="mono">{j.lastRun.endedAt ? fmt(j.lastRun.endedAt) : "—"}</span>
                            </>
                          ) : "—"}
                        </td>
                        <td data-l="操作" style={{ textAlign: "right", whiteSpace: "nowrap" }}>
                          <button className="btn ghost sm">编辑</button>{" "}
                          <button className="btn ghost sm">执行历史</button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </div>
      )}

      {toast && (
        <div className="foot-note" onClick={() => setToast(null)} style={{ cursor: "pointer" }}>{toast}</div>
      )}

      {/* 新增/编辑弹窗 */}
      {(creating || editing) && (
        <ItemForm
          initial={editing}
          onClose={() => { setCreating(false); setEditing(null); }}
          onSaved={() => { setCreating(false); setEditing(null); setToast("已保存"); load(); }}
        />
      )}

      {/* DL-07 分支 A：被引用即拒绝，仅「我知道了」 */}
      {refModal && (
        <div className="card" style={{ position: "fixed", inset: "20% 30%", zIndex: 50, overflow: "auto" }}>
          <h3>无法删除：数据项仍被引用</h3>
          <p className="foot-note">
            「{refModal.item.name}」正被 {refModal.refs.length} 个使用方引用，直接删除会导致其运行失败或结果失真。
            请先到「策略与因子」页解除引用，再删除。
          </p>
          <table className="stacktable">
            <thead><tr><th>引用方</th><th>类型</th><th>用途</th></tr></thead>
            <tbody>
              {refModal.refs.map((r, k) => (
                <tr key={k}>
                  <td data-l="引用方">{r.usedBy}</td>
                  <td data-l="类型"><span className="tag gray">{r.kind === "strategy" ? "策略" : "报表"}</span></td>
                  <td data-l="用途">{r.note ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="text-center mt-3">
            <button className="btn ghost" onClick={() => setRefModal(null)}>我知道了</button>
          </div>
        </div>
      )}

      {/* DL-08 分支 B：先列删除范围再确认 */}
      {confirmDelete && (
        <div className="card" style={{ position: "fixed", inset: "26% 32%", zIndex: 50 }}>
          <h3>删除数据项及其数据</h3>
          <p>「{confirmDelete.name}」（编码 {confirmDelete.id}）删除后不可逆：</p>
          <ul className="text-[13px] text-muted list-disc pl-5">
            <li>历史数据 <b className="red">{confirmDelete.rows} 条</b>（库内全部期次）</li>
            <li>运行日志（仅该数据项相关记录）</li>
            <li>采集任务本身保留，仅移除该项</li>
          </ul>
          <p className="foot-note">
            <b>删除后该项不再采集，历史期次无法回滚。</b>建议先确认下游无其他系统依赖此数据。
          </p>
          <div className="flex gap-2 justify-end">
            <button className="btn ghost" onClick={() => setConfirmDelete(null)}>取消</button>
            <button className="btn" style={{ background: "var(--red)" }} onClick={() => doDelete(confirmDelete)}>
              确认删除并清除数据
            </button>
          </div>
        </div>
      )}
    </section>
  );
}

function ItemForm({ initial, onClose, onSaved }: {
  initial: DataItemRow | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [form, setForm] = useState({
    id: initial?.id ?? "",
    name: initial?.name ?? "",
    freq: initial?.freq ?? "月频",
    factor_layer: initial?.factorLayer ?? "",
    api: initial?.api ?? "",
    publish_slot: initial?.publishSlot ?? "",
    job_code: initial?.jobCode ?? "",
  });
  const [msg, setMsg] = useState<string | null>(null);

  const save = async () => {
    const r = await apiPost("/api/datamgmt/items", form);
    if (r.code === 0) onSaved();
    else setMsg(r.message);
  };

  return (
    <div className="card" style={{ position: "fixed", inset: "18% 34%", zIndex: 50 }}>
      <h3>{initial ? `编辑数据项 · ${initial.name}` : "新增数据项"}</h3>
      <div className="grid gap-2 text-[13px]">
        <label>数据项名 * <input className="w-full" type="text" value={form.name}
          onChange={(e) => setForm({ ...form, name: e.target.value })} /></label>
        <label>频率 *
          <select className="w-full" value={form.freq} onChange={(e) => setForm({ ...form, freq: e.target.value })}>
            <option>日频</option><option>周频</option><option>月频</option><option>季频</option>
          </select></label>
        <label>因子层级 *
          <select className="w-full" value={form.factor_layer} onChange={(e) => setForm({ ...form, factor_layer: e.target.value })}>
            <option value="">— 请选择（必填）—</option>
            <option value="macro">宏观</option><option value="meso">中观</option><option value="micro">微观</option>
          </select></label>
        <label>数据源接口 <input className="w-full" type="text" value={form.api}
          onChange={(e) => setForm({ ...form, api: e.target.value })} /></label>
        <label>公布时间 <input className="w-full" type="text" value={form.publish_slot}
          onChange={(e) => setForm({ ...form, publish_slot: e.target.value })} /></label>
        <label>归属定时任务 <input className="w-full" type="text" value={form.job_code}
          onChange={(e) => setForm({ ...form, job_code: e.target.value })} /></label>
      </div>
      {msg && <p className="foot-note" style={{ color: "var(--red)" }}>{msg}</p>}
      <div className="flex gap-2 justify-end mt-3">
        <button className="btn ghost" onClick={onClose}>取消</button>
        <button className="btn" onClick={save}>保存</button>
      </div>
    </div>
  );
}
