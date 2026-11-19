import { getPool, probe } from "./db";

/** P2 运维监控（AD-02）：只管宏观链路「缺不缺」，调度展示归 #datamgmt。 */
export interface MonitorItem {
  id: string;
  name: string;
  freq: string;
  latestPeriod: string | null;
  officialLatest: string | null; // 官方最新可获取（发布日历推算；缺规则 → null，前端空态）
  gapPeriods: number;
  lastFetchAt: string | null;
  status: "ok" | "gap" | "no_data";
}

export interface MonitorData {
  available: boolean;
  reason?: string;
  stamp: string;
  items: MonitorItem[];
}

export async function getMonitor(): Promise<MonitorData> {
  const p = await probe();
  if (!p.available) return { available: false, reason: p.reason, stamp: now(), items: [] };
  const db = getPool()!;
  const q = await db.query(
    `SELECT id, name, freq, latest_period, gap_periods, rows, last_fetch_at
       FROM task.data_item
      WHERE factor_layer = 'macro' AND status = 'active'
      ORDER BY id`,
  );
  const items: MonitorItem[] = q.rows.map((r) => ({
    id: r.id,
    name: r.name,
    freq: freqLabel(r.freq),
    latestPeriod: r.latest_period ?? null,
    officialLatest: null, // 发布日历元数据待接入（P2 对账 MO-5：缺 → 空态）
    gapPeriods: Math.max(0, r.gap_periods ?? 0),
    lastFetchAt: r.last_fetch_at ? new Date(r.last_fetch_at).toISOString() : null,
    status:
      (r.rows ?? 0) === 0 ? "no_data" : (r.gap_periods ?? 0) > 0 ? "gap" : ("ok" as const),
  }));
  items.sort((a, b) => (a.status === "gap" ? -1 : 0) - (b.status === "gap" ? -1 : 0)); // 缺失项置顶
  return { available: true, stamp: now(), items };
}

function freqLabel(f: string): string {
  return { daily: "日频", weekly: "周频", monthly: "月频", quarterly: "季频" }[f] ?? f;
}

function now(): string {
  return new Date().toISOString();
}
