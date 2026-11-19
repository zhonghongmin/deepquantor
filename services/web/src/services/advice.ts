import { getPool, probe } from "./db";
import { getMacro } from "./macro";

/** P6 投资建议（AD-08）：两段式（① 周期结论条 → ② 大类资产配置）。零计算，只读信号。 */
export interface AdviceData {
  available: boolean;
  reason?: string;
  stamp: string;
  signal: {
    asOf: string;
    regime: string;
    phase: string | null;
    moneyCredit: string | null;
    equityWeight: number | null;
    confidence: number | null;
    unconfirmed: boolean;
    assetAlloc: Record<string, number> | null;
    styleTilt: Record<string, string> | null;
    sayings: string[];
  } | null;
  drilldown: null; // 下钻理由链（RK 总装启用后接入；本期空态）
}

export async function getAdvice(): Promise<AdviceData> {
  const p = await probe();
  if (!p.available) return { available: false, reason: p.reason, stamp: now(), signal: null, drilldown: null };
  const m = await getMacro();
  const s = m.signal;
  if (!s) return { available: true, stamp: now(), signal: null, drilldown: null };
  const j = (s.signalJson ?? {}) as Record<string, unknown>;
  const alloc = (s.signalJson && (j.asset_alloc as Record<string, number> | undefined)) || null;
  const style = (j.style_tilt as Record<string, string> | undefined) || null;
  const meta = (j._meta as Record<string, unknown> | undefined) || {};
  return {
    available: true,
    stamp: now(),
    signal: {
      asOf: s.asOf,
      regime: s.regime,
      phase: (j.phase as string | undefined) ?? null,
      moneyCredit: s.moneyCredit,
      equityWeight: s.equityWeight,
      confidence: s.confidence,
      unconfirmed: Boolean(meta.unconfirmed),
      assetAlloc: alloc,
      styleTilt: style,
      sayings: (j.sayings as string[] | undefined) ?? [],
    },
    drilldown: null,
  };
}

function now(): string {
  return new Date().toISOString();
}
