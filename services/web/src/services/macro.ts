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

/** ② 数据支撑：单维度真实序列（market.macro_indicator）+ 细项 6 期迷你序列（效果图 2026-11-21 新版）。 */
export interface DimSeries {
  key: string;
  values: { p: string; v: number }[];
  /** 细项序列：values 为真实 6 期升序；空数组 = 无真实数据源（前端待采数空态，不造数）。 */
  subs: { name: string; values: number[]; unit: string; dec: number }[];
}

/** ⑤ 周期回溯：沪深300 月末收盘累计涨幅（起点归一 0%，真实行情）。 */
export interface CycleData {
  months: string[];
  cum: number[];
}

export interface MacroData {
  available: boolean;
  reason?: string;
  stamp: string;
  signal: MacroSignalRow | null;
  history: { asOf: string; regime: string }[]; // ⑤ 周期回溯（不足 5 年 → 前端「待回测」空态）
  forecasts: { signalId: string; windowMonths: string; direction: string; status: string }[];
  series: DimSeries[];
  cycle: CycleData | null;
}

const CODES =
  "('PMI','PMI_NM','PMI_ORDER','PMI_PROD','PMI_EXP','CPI','CPI_CORE','CPI_FOOD','PPI','M1','M2','TSF_STOCK','CRED_HH_YOY','CRED_ENT_YOY','CRED_GOV_YOY')";

/** DATE（pg → 本地时区午夜 Date）→ YYYY-MM-DD，避免 toISOString 的 UTC 偏移掉一天。 */
function fmtDate(d: Date): string {
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${d.getFullYear()}-${m}-${day}`;
}

const f1 = (x: number | null | undefined): string =>
  x == null || Number.isNaN(x) ? "—" : (+x).toFixed(1);

/** 与前一比较的方向（真实序列相邻两期，不补零不填前值）。 */
function dirVsPrev(series: { p: string; v: number }[]): "up" | "down" | "flat" {
  if (series.length < 2) return "flat";
  const d = series[series.length - 1].v - series[series.length - 2].v;
  return d > 0 ? "up" : d < 0 ? "down" : "flat";
}

const f6 = (map: Map<string, number>): number[] =>
  lastN(map, 6).map((x) => x.v);

/** 取某指标码最后 n 期序列（升序）。 */
function lastN(map: Map<string, number>, n: number): { p: string; v: number }[] {
  return [...map.entries()].sort((a, b) => (a[0] < b[0] ? -1 : 1)).slice(-n)
    .map(([p, v]) => ({ p, v }));
}

export async function getMacro(): Promise<MacroData> {
  const p = await probe();
  if (!p.available) {
    return {
      available: false, reason: p.reason, stamp: now(),
      signal: null, history: [], forecasts: [], series: [], cycle: null,
    };
  }
  const db = getPool()!;
  const [sq, hq, fq, mq, ixq] = await Promise.all([
    db.query(
      `SELECT as_of, regime, money_credit, equity_weight, confidence, signal_json
         FROM signal.macro_signal ORDER BY as_of DESC LIMIT 1`,
    ),
    db.query(
      `SELECT as_of, regime FROM signal.macro_signal ORDER BY as_of DESC LIMIT 60`,
    ),
    db.query(
      `SELECT signal_id, lead_window, direction, hit_rate_status
         FROM signal.macro_forecast ORDER BY as_of DESC LIMIT 8`,
    ),
    db.query(
      `SELECT indicator_code, period, val, yoy FROM market.macro_indicator
         WHERE freq = 'M' AND indicator_code IN ${CODES}
         ORDER BY indicator_code, period`,
    ),
    // ⑤ 回溯：沪深300 月末收盘（2021-10 起，当月末收盘；基期 = 2021-10 月末）
    db.query(
      `SELECT to_char(trade_date, 'YYYY-MM') AS ym, close FROM market.index_daily
         WHERE index_code = '000300' AND trade_date >= '2021-10-01'
         ORDER BY trade_date`,
    ),
  ]);
  const r = sq.rows[0];

  // ---- ② 维度序列：全部来自真实落库值，缺期即断开（不补零/不填前值） ----
  const vals = new Map<string, Map<string, number>>();
  const yoys = new Map<string, Map<string, number>>();
  for (const row of mq.rows) {
    const code: string = row.indicator_code;
    const period: string = row.period;
    if (!vals.has(code)) vals.set(code, new Map());
    if (row.val != null) vals.get(code)!.set(period, Number(row.val));
    if (row.yoy != null) {
      if (!yoys.has(code)) yoys.set(code, new Map());
      yoys.get(code)!.set(period, Number(row.yoy));
    }
  }
  const pmi = lastN(vals.get("PMI") ?? new Map(), 6);
  const cpi = lastN(yoys.get("CPI") ?? new Map(), 6);
  const m2 = lastN(yoys.get("M2") ?? new Map(), 6);

  // 信用卡主序列：TSF_STOCK（Python 侧央行锚点口径派生，全量重算，无旧口径污染）
  const tsfStock = lastN(yoys.get("TSF_STOCK") ?? new Map(), 6);

  // 细项 6 期序列（效果图 2026-11-21 新版；2026-11-22 起 NBS 新网关 + 央行官网官方源，
  // 辅助码由 macro-aux 落库：PMI_ORDER/PROD/EXP、CPI_CORE/FOOD、CRED_*；无源仍标空数组）
  const pnmVals = f6(vals.get("PMI_NM") ?? new Map());
  const ppiVals = f6(yoys.get("PPI") ?? new Map());
  const m1v = lastN(yoys.get("M1") ?? new Map(), 6);
  const m2v = lastN(yoys.get("M2") ?? new Map(), 6);
  // M1−M2：同月对齐逐期真实相减（期数不齐时取交集，不补算）
  const m2ByP = new Map(m2v.map((x) => [x.p, x.v]));
  const gapVals = m1v.filter((x) => m2ByP.has(x.p)).map((x) => +(x.v - m2ByP.get(x.p)!).toFixed(1));

  const series: DimSeries[] = [
    {
      key: "growth", values: pmi,
      subs: [
        { name: "新订单", values: f6(vals.get("PMI_ORDER") ?? new Map()), unit: "", dec: 1 },
        { name: "生产", values: f6(vals.get("PMI_PROD") ?? new Map()), unit: "", dec: 1 },
        { name: "新出口订单", values: f6(vals.get("PMI_EXP") ?? new Map()), unit: "", dec: 1 },
        { name: "非制造业 PMI", values: pnmVals, unit: "", dec: 1 },
      ],
    },
    {
      key: "inflation", values: cpi,
      subs: [
        { name: "核心 CPI", values: f6(vals.get("CPI_CORE") ?? new Map()), unit: "%", dec: 1 },
        { name: "食品烟酒", values: f6(vals.get("CPI_FOOD") ?? new Map()), unit: "%", dec: 1 },
        { name: "PPI 同比", values: ppiVals, unit: "%", dec: 1 },
      ],
    },
    {
      key: "money", values: m2,
      subs: [
        { name: "M1 同比", values: f6(yoys.get("M1") ?? new Map()), unit: "%", dec: 1 },
        { name: "M1−M2", values: gapVals, unit: "pct", dec: 1 },
        { name: "M2 同比", values: f6(yoys.get("M2") ?? new Map()), unit: "%", dec: 1 },
      ],
    },
    {
      key: "credit", values: tsfStock,
      subs: [
        { name: "居民同比", values: f6(vals.get("CRED_HH_YOY") ?? new Map()), unit: "%", dec: 1 },
        { name: "企业同比", values: f6(vals.get("CRED_ENT_YOY") ?? new Map()), unit: "%", dec: 1 },
        { name: "政府同比", values: f6(vals.get("CRED_GOV_YOY") ?? new Map()), unit: "%", dec: 1 },
      ],
    },
  ];

  // ---- ⑤ 沪深300 月末收盘累计涨幅（起点归一 0%）----
  let cycle: CycleData | null = null;
  const monthEnd = new Map<string, number>();
  for (const row of ixq.rows) monthEnd.set(String(row.ym), Number(row.close));
  const months = [...monthEnd.keys()].filter((m) => m >= "2021-11").sort();
  const base = monthEnd.get("2021-10");
  if (base && months.length) {
    cycle = {
      months,
      cum: months.map((m) => +(((monthEnd.get(m)! / base) - 1) * 100).toFixed(2)),
    };
  }

  return {
    available: true,
    stamp: now(),
    signal: r
      ? {
          asOf: r.as_of instanceof Date ? fmtDate(r.as_of) : String(r.as_of),
          regime: r.regime,
          moneyCredit: r.money_credit ?? null,
          equityWeight: r.equity_weight != null ? Number(r.equity_weight) : null,
          confidence: r.confidence != null ? Number(r.confidence) : null,
          signalJson: r.signal_json ?? null,
        }
      : null,
    history: hq.rows.map((x) => ({
      asOf: x.as_of instanceof Date ? fmtDate(x.as_of) : String(x.as_of),
      regime: x.regime,
    })),
    forecasts: fq.rows.map((x) => ({
      signalId: x.signal_id,
      windowMonths: x.lead_window, // DDL 唯一权威：lead_window（如 "6m"）
      direction: x.direction,
      status: x.hit_rate_status, // 未回测只能 pending（只读派生契约）
    })),
    series,
    cycle,
  };
}

function now(): string {
  return new Date().toISOString();
}
