import { Pool } from "pg";

/**
 * 数据库连接（硬约束 8：配置走 env，不硬编码 host/密码）。
 * 未配置 DATABASE_URL → 返回 null，各 service 降级为「不可用」，
 * 页面展示空态 + 数据时间，绝不编造兜底值。
 */
let pool: Pool | null = null;

export function getPool(): Pool | null {
  const dsn = process.env.DATABASE_URL;
  if (!dsn) return null;
  if (!pool) {
    pool = new Pool({ connectionString: dsn, max: 5, connectionTimeoutMillis: 4000 });
  }
  return pool;
}

export interface Available {
  available: boolean;
  reason?: string;
}

export async function probe(): Promise<Available> {
  const p = getPool();
  if (!p) return { available: false, reason: "未配置 DATABASE_URL" };
  try {
    await p.query("SELECT 1");
    return { available: true };
  } catch (e) {
    return { available: false, reason: e instanceof Error ? e.message : String(e) };
  }
}
