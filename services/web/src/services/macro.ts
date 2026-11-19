import { getPool, probe } from "./db";

/** P10 宏观数据（AD-10）：五区单列；只读 signal.macro_signal，页面不重算。 */

export interface MacroSignalRow {
  asOf: string;
  regime: string;
  moneyCredit: string | null;
  equityWeight: number | null;
  confidence: number | null;
  signalJson: Record<string, unknown> | null;
}

export interface MacroData {
  available: boolean;
  reason?: string;
  stamp: string;
  signal: MacroSignalRow | null;
  history: { asOf: string; regime: string }[]; // ⑤ 周期回溯（不足 5 年 → 前端「待回测」空态）
  forecasts: { signalId: string; windowMonths: number; direction: string; status: string }[];
}

export async function getMacro(): Promise<MacroData> {
  const p = await probe();
  if (!p.available) {
    return { available: false, reason: p.reason, stamp: now(), signal: null, history: [], forecasts: [] };
  }
  const db = getPool()!;
  const [sq, hq, fq] = await Promise.all([
    db.query(
      `SELECT as_of, regime, money_credit, equity_weight, confidence, signal_json
         FROM signal.macro_signal ORDER BY as_of DESC LIMIT 1`,
    ),
    db.query(
      `SELECT as_of, regime FROM signal.macro_signal ORDER BY as_of DESC LIMIT 60`,
    ),
    db.query(
      `SELECT signal_id, window_months, direction, status
         FROM signal.macro_forecast ORDER BY as_of DESC LIMIT 8`,
    ),
  ]);
  const r = sq.rows[0];
  return {
    available: true,
    stamp: now(),
    signal: r
      ? {
          asOf: r.as_of instanceof Date ? r.as_of.toISOString().slice(0, 10) : String(r.as_of),
          regime: r.regime,
          moneyCredit: r.money_credit ?? null,
          equityWeight: r.equity_weight != null ? Number(r.equity_weight) : null,
          confidence: r.confidence != null ? Number(r.confidence) : null,
          signalJson: r.signal_json ?? null,
        }
      : null,
    history: hq.rows.map((x) => ({
      asOf: x.as_of instanceof Date ? x.as_of.toISOString().slice(0, 10) : String(x.as_of),
      regime: x.regime,
    })),
    forecasts: fq.rows.map((x) => ({
      signalId: x.signal_id,
      windowMonths: x.window_months,
      direction: x.direction,
      status: x.status, // 未回测只能 pending（只读派生契约）
    })),
  };
}

function now(): string {
  return new Date().toISOString();
}
