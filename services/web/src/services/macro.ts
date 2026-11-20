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

/** ② 数据支撑：单维度真实序列（market.macro_indicator / signal_json.credit_detail）。 */
export interface DimSeries {
  key: string;
  values: { p: string; v: number }[];
  subs: { name: string; val: string; dir: "up" | "down" | "flat" }[];
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

const CODES = "('PMI','PMI_NM','CPI','PPI','M1','M2','CREDIT')";

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
  const [sq, hq, fq, mq, csq, ixq] = await Promise.all([
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
    // 社融存量同比 / 中长贷多增：单一来源 = 引擎落库的 signal_json.credit_detail（web 层不重算口径）
    db.query(
      `SELECT signal_json->'credit_detail' AS cd FROM signal.macro_signal
         ORDER BY as_of DESC LIMIT 8`,
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
  const pnm = lastN(vals.get("PMI_NM") ?? new Map(), 2);
  const ppi = lastN(yoys.get("PPI") ?? new Map(), 2);
  const m1 = lastN(yoys.get("M1") ?? new Map(), 2);
  const m2s = lastN(yoys.get("M2") ?? new Map(), 2);

  // 信用卡：引擎落库的社融存量同比 / 中长贷同比多增（period = credit_detail.month）
  const afre: { p: string; v: number }[] = [];
  const mlLoan: { p: string; v: number }[] = [];
  for (const row of csq.rows) {
    const cd = row.cd as { afre_yoy?: number; ml_loan_yoy?: number; month?: string } | null;
    if (!cd || cd.afre_yoy == null || !cd.month) continue;
    afre.push({ p: cd.month, v: Number(cd.afre_yoy) });
    if (cd.ml_loan_yoy != null) mlLoan.push({ p: cd.month, v: Number(cd.ml_loan_yoy) });
    if (afre.length >= 6) break;
  }
  afre.reverse();
  mlLoan.reverse();

  const series: DimSeries[] = [
    {
      key: "growth", values: pmi,
      subs: [{ name: "非制造业 PMI", val: f1(pnm[pnm.length - 1]?.v), dir: dirVsPrev(pnm) }],
    },
    {
      key: "inflation", values: cpi,
      subs: [{ name: "PPI 同比", val: f1(ppi[ppi.length - 1]?.v), dir: dirVsPrev(ppi) }],
    },
    {
      key: "money", values: m2,
      subs: [
        { name: "M1 同比", val: f1(m1[m1.length - 1]?.v), dir: dirVsPrev(m1) },
        {
          name: "M1−M2 剪刀差",
          val: m1.length && m2s.length
            ? f1(m1[m1.length - 1].v - m2s[m2s.length - 1].v)
            : "—",
          dir: "flat",
        },
      ],
    },
    {
      key: "credit", values: afre,
      subs: [
        { name: "社融存量同比", val: f1(afre[afre.length - 1]?.v), dir: dirVsPrev(afre) },
        { name: "新增贷款 · 同比多增", val: f1(mlLoan[mlLoan.length - 1]?.v), dir: dirVsPrev(mlLoan) },
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
