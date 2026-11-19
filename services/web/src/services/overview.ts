import { getPool, probe } from "./db";

/** P1 概览（AD-09）：三层链路卡。L2/L3 未接入恒灰态；L1 与 #monitor 同源计数。 */
export interface OverviewData {
  available: boolean;
  reason?: string;
  stamp: string; // 数据截至
  l1: {
    state: "运行中" | "部分滞后" | "缺失";
    total: number;
    ok: number;
    gap: number;
    lastFetchAt: string | null;
  } | null;
}

export async function getOverview(): Promise<OverviewData> {
  const p = await probe();
  if (!p.available) return { available: false, reason: p.reason, stamp: now(), l1: null };
  const db = getPool()!;
  const q = await db.query(
    `SELECT COUNT(*)::int AS total,
            COUNT(*) FILTER (WHERE COALESCE(gap_periods,0) = 0 AND rows > 0)::int AS ok,
            COUNT(*) FILTER (WHERE COALESCE(gap_periods,0) > 0)::int AS gap,
            COUNT(*) FILTER (WHERE COALESCE(rows,0) = 0)::int AS no_data,
            MAX(last_fetch_at) AS last_fetch_at
       FROM task.data_item
      WHERE factor_layer = 'macro' AND status = 'active'`,
  );
  const r = q.rows[0];
  const total = r.total as number;
  const l1 =
    total === 0
      ? { state: "缺失" as const, total: 0, ok: 0, gap: 0, lastFetchAt: null }
      : {
          state: (r.gap > 0 ? "部分滞后" : "运行中") as "部分滞后" | "运行中",
          total,
          ok: r.ok as number,
          gap: r.gap as number,
          lastFetchAt: r.last_fetch_at ? new Date(r.last_fetch_at).toISOString() : null,
        };
  return { available: true, stamp: now(), l1 };
}

function now(): string {
  return new Date().toISOString();
}
