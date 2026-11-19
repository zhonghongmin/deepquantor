import { getPool, probe } from "./db";

/** P3 数据管理（AD-02 / DL-05）：唯一数据资产写入口（数据项 / 定时任务两 Tab）。 */

const FREQ_LABEL: Record<string, string> = {
  daily: "日频", weekly: "周频", monthly: "月频", quarterly: "季频",
};

export interface DataItemRow {
  id: string;
  name: string;
  field: string;
  freq: string;
  factorLayer: string | null;
  api: string | null;
  publishSlot: string | null;
  jobCode: string | null;
  rows: number;
}

export interface JobRow {
  jobKey: string;
  jobName: string;
  cronExpr: string | null;
  enabled: boolean;
  lastRun: { status: string; endedAt: string | null; durationMs: number | null } | null;
}

export interface DataMgmtData {
  available: boolean;
  reason?: string;
  stamp: string;
  items: DataItemRow[];
  jobs: JobRow[];
}

export async function getDataMgmt(): Promise<DataMgmtData> {
  const p = await probe();
  if (!p.available) return { available: false, reason: p.reason, stamp: now(), items: [], jobs: [] };
  const db = getPool()!;
  const [iq, jq] = await Promise.all([
    db.query(
      `SELECT id, name, freq, factor_layer, api, publish_slot, job_code, COALESCE(rows,0) AS rows
         FROM task.data_item ORDER BY id`,
    ),
    db.query(
      `SELECT j.job_key, j.job_name, j.cron_expr, j.enabled,
              ji.status AS last_status, ji.ended_at AS last_ended, ji.duration_ms AS last_ms
         FROM task.job_def j
         LEFT JOIN LATERAL (
           SELECT status, ended_at, duration_ms FROM task.job_instance i
            WHERE i.job_key = j.job_key ORDER BY started_at DESC LIMIT 1
         ) ji ON true
        ORDER BY j.job_key`,
    ),
  ]);
  return {
    available: true,
    stamp: now(),
    items: iq.rows.map((r) => ({
      id: r.id,
      name: r.name,
      field: r.id, // 字段 = 数据项编码（§4.5 ⑥：名称可改、编码不可变）
      freq: FREQ_LABEL[r.freq as string] ?? r.freq,
      factorLayer: r.factor_layer,
      api: r.api,
      publishSlot: r.publish_slot,
      jobCode: r.job_code,
      rows: r.rows as number,
    })),
    jobs: jq.rows.map((r) => ({
      jobKey: r.job_key,
      jobName: r.job_name,
      cronExpr: r.cron_expr,
      enabled: r.enabled,
      lastRun: r.last_status
        ? {
            status: r.last_status,
            endedAt: r.last_ended ? new Date(r.last_ended).toISOString() : null,
            durationMs: r.last_ms,
          }
        : null,
    })),
  };
}

/** DL-07：按编码查引用，被引用即拒绝删除。 */
export async function checkRefs(dataId: string): Promise<
  { available: boolean; reason?: string; refs: { usedBy: string; kind: string; note: string | null }[] }
> {
  const p = await probe();
  if (!p.available) return { available: false, reason: p.reason, refs: [] };
  const db = getPool()!;
  const q = await db.query(
    "SELECT used_by, kind, note FROM task.data_ref WHERE data_id = $1 ORDER BY id",
    [dataId],
  );
  return {
    available: true,
    refs: q.rows.map((r) => ({ usedBy: r.used_by, kind: r.kind, note: r.note ?? null })),
  };
}

/** DL-08：删除 = 配置 + 全部历史数据 + 运行日志，三处同一事务（引用检查须先通过）。 */
export async function deleteDataItem(dataId: string): Promise<{ ok: boolean; message: string }> {
  const db = getPool();
  if (!db) return { ok: false, message: "数据库不可用" };
  const ref = await checkRefs(dataId);
  if (ref.refs.length > 0) {
    return {
      ok: false,
      message: `无法删除：数据项仍被 ${ref.refs.length} 个使用方引用（${ref.refs
        .map((r) => r.usedBy)
        .join("、")}）。请先解除引用。`,
    };
  }
  const client = await db.connect();
  try {
    await client.query("BEGIN");
    await client.query("DELETE FROM task.data_item WHERE id = $1", [dataId]);
    await client.query("DELETE FROM task.data_ref WHERE data_id = $1", [dataId]);
    // 历史数据 / 运行日志清理点：各数据表按 data_item.api 归属，本期表结构落地后接入
    await client.query("COMMIT");
    return { ok: true, message: `已删除「${dataId}」` };
  } catch (e) {
    await client.query("ROLLBACK");
    return { ok: false, message: e instanceof Error ? e.message : String(e) };
  } finally {
    client.release();
  }
}

function now(): string {
  return new Date().toISOString();
}
