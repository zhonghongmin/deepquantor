/**
 * services 层单测（dq-test-skill：集成层，mock pg 不触真实 DB，DATABASE_URL 已配置）
 *
 * 断言口径源自设计基线：
 *  - P1 对账 OV-2：L1 与 #monitor 同源计数（COUNT FILTER 口径）
 *  - P2 MO-5：缺失项置顶、官方最新可获取缺日历 → null（前端空态）
 *  - DL-07：被引用即拒绝删除；DL-08：三处同一事务 + 失败 ROLLBACK
 *  - MC-05 只读契约：#macro 只读 signal.macro_signal；预测信号 status 原样透传（pending）
 */
import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

type Row = Record<string, unknown>;

const { state, client } = vi.hoisted(() => {
  // fake pg client：记录 BEGIN/DELETE/COMMIT/ROLLBACK 调用序列
  const client = {
    calls: [] as string[],
    failOnCommit: false,
    query: async (sql: string) => {
      client.calls.push(sql);
      if (client.failOnCommit && /COMMIT/.test(sql)) throw new Error("commit failed");
      return { rows: [] as Row[] };
    },
    release: () => {},
  };
  // fake pool.query 路由：按 SQL 关键字返回各测试注入的行
  const state = {
    handler: null as null | ((sql: string, params?: unknown[]) => Row[]),
    error: null as null | string,
  };
  return { state, client };
});

vi.mock("pg", () => ({
  Pool: class FakePool {
    async query(sql: string, params?: unknown[]) {
      if (state.error) throw new Error(state.error);
      return { rows: state.handler ? state.handler(sql, params) : [] };
    }
    async connect() {
      return client;
    }
  },
}));

let db: typeof import("../../src/services/db");
let overview: typeof import("../../src/services/overview");
let monitor: typeof import("../../src/services/monitor");
let macro: typeof import("../../src/services/macro");
let advice: typeof import("../../src/services/advice");
let datamgmt: typeof import("../../src/services/datamgmt");

beforeAll(async () => {
  vi.stubEnv("DATABASE_URL", "postgres://fake");
  db = await import("../../src/services/db");
  overview = await import("../../src/services/overview");
  monitor = await import("../../src/services/monitor");
  macro = await import("../../src/services/macro");
  advice = await import("../../src/services/advice");
  datamgmt = await import("../../src/services/datamgmt");
});

beforeEach(() => {
  state.handler = null;
  state.error = null;
  client.calls = [];
  client.failOnCommit = false;
});

// ─────────────────────────────────────────────────────────────
// overview.ts（P1 / OV-2）
// ─────────────────────────────────────────────────────────────
describe("overview.ts", () => {
  it("宏观数据项 0 项 → L1 state=缺失（OV-2 口径）", async () => {
    state.handler = () => [{ total: 0, ok: 0, gap: 0, no_data: 0, last_fetch_at: null }];
    const d = await overview.getOverview();
    expect(d.available).toBe(true);
    expect(d.l1?.state).toBe("缺失");
  });

  it("gap>0 → L1 state=部分滞后；gap=0 → 运行中；last_fetch_at → ISO（OV-2 判定口径）", async () => {
    state.handler = () => [{ total: 15, ok: 10, gap: 5, no_data: 0, last_fetch_at: "2026-11-19T10:00:00Z" }];
    expect((await overview.getOverview()).l1?.state).toBe("部分滞后");
    state.handler = () => [{ total: 15, ok: 15, gap: 0, no_data: 0, last_fetch_at: null }];
    const d = await overview.getOverview();
    expect(d.l1?.state).toBe("运行中");
    expect(d.l1?.lastFetchAt).toBeNull();
  });
});

// ─────────────────────────────────────────────────────────────
// monitor.ts（P2 / MO-5）
// ─────────────────────────────────────────────────────────────
describe("monitor.ts", () => {
  it("状态映射：rows=0→no_data、gap>0→gap、否则 ok；缺失项置顶；频率中文化", async () => {
    state.handler = () => [
      { id: "pmi", name: "制造业PMI", freq: "monthly", latest_period: "2026-10", gap_periods: 0, rows: 120, last_fetch_at: "2026-11-19T10:00:00Z" },
      { id: "reverse_repo", name: "逆回购", freq: "daily", latest_period: null, gap_periods: 0, rows: 0, last_fetch_at: null },
      { id: "cpi", name: "CPI", freq: "quarterly", latest_period: "2026-09", gap_periods: 2, rows: 60, last_fetch_at: null },
    ];
    const d = await monitor.getMonitor();
    expect(d.items.map((i) => i.status)).toEqual(["gap", "ok", "no_data"]); // gap 置顶
    expect(d.items.find((i) => i.id === "pmi")?.freq).toBe("月频");
    expect(d.items.find((i) => i.id === "cpi")?.freq).toBe("季频");
    expect(d.items.find((i) => i.id === "pmi")?.lastFetchAt).toBe("2026-11-19T10:00:00.000Z");
    expect(d.items.every((i) => i.officialLatest === null)).toBe(true); // 发布日历未接入 → 空态
  });
});

// ─────────────────────────────────────────────────────────────
// datamgmt.ts（P3 / DL-07 / DL-08）
// ─────────────────────────────────────────────────────────────
describe("datamgmt.ts", () => {
  it("getDataMgmt：数据项/任务映射，无运行史 → lastRun=null", async () => {
    state.handler = (sql) => {
      if (/job_def/.test(sql)) {
        return [
          { job_key: "macro-monthly", job_name: "宏观月频", cron_expr: "0 10 10-20 * *", enabled: true, last_status: "success", last_ended: "2026-11-17T02:00:00Z", last_ms: 1200 },
          { job_key: "macro-daily", job_name: "宏观日频", cron_expr: "0 2 * * *", enabled: false, last_status: null, last_ended: null, last_ms: null },
        ];
      }
      return [
        { id: "pmi", name: "制造业PMI", freq: "monthly", factor_layer: "macro", api: "pmi", publish_slot: "10:00", job_code: "macro-monthly", rows: 120 },
      ];
    };
    const d = await datamgmt.getDataMgmt();
    expect(d.items[0]).toMatchObject({ field: "pmi", freq: "月频" }); // 字段=编码不可变（§4.5 ⑥）
    expect(d.jobs[1].lastRun).toBeNull();
    expect(d.jobs[0].lastRun?.status).toBe("success");
  });

  it("DL-07：被引用 → 拒绝删除，消息列占用方，不触事务", async () => {
    state.handler = () => [
      { used_by: "MC-01", kind: "factor_input", note: null },
      { used_by: "MC-09", kind: "grid_ref", note: "36 格查表" },
    ];
    const r = await datamgmt.deleteDataItem("pmi");
    expect(r.ok).toBe(false);
    expect(r.message).toContain("MC-01");
    expect(r.message).toContain("2 个"); // 引用计数
    expect(client.calls).toEqual([]); // 分支 A：拒绝即不动数据
  });

  it("DL-08：无引用 → BEGIN→DELETE 配置/引用→COMMIT 同事务，成功回报", async () => {
    state.handler = () => [];
    const r = await datamgmt.deleteDataItem("pmi");
    expect(r.ok).toBe(true);
    expect(client.calls.filter((s) => /BEGIN|DELETE|COMMIT/.test(s))).toHaveLength(4);
    expect(client.calls.some((s) => /ROLLBACK/.test(s))).toBe(false);
  });

  it("DL-08：事务失败 → ROLLBACK + ok=false（三处同事务原子性）", async () => {
    state.handler = () => [];
    client.failOnCommit = true;
    const r = await datamgmt.deleteDataItem("pmi");
    expect(r.ok).toBe(false);
    expect(client.calls.some((s) => /ROLLBACK/.test(s))).toBe(true);
  });

  it("checkRefs：映射 used_by/kind/note，note 缺失 → null", async () => {
    state.handler = () => [{ used_by: "MC-01", kind: "factor_input", note: null }];
    const r = await datamgmt.checkRefs("pmi");
    expect(r.available).toBe(true);
    expect(r.refs[0]).toEqual({ usedBy: "MC-01", kind: "factor_input", note: null });
  });
});

// ─────────────────────────────────────────────────────────────
// macro.ts（P10 只读契约）
// ─────────────────────────────────────────────────────────────
describe("macro.ts", () => {
  it("只读信号行映射：Date/字符串双形态、空值规范化（MC-05）", async () => {
    state.handler = (sql) => {
      if (/macro_forecast/.test(sql)) {
        return [{ signal_id: "f1", window_months: 2, direction: "宽货币", status: "pending" }];
      }
      if (/LIMIT 60/.test(sql)) {
        return [{ as_of: new Date("2026-10-31"), regime: "复苏" }, { as_of: "2026-09-30", regime: "衰退" }];
      }
      return [{
        as_of: new Date("2026-10-31"), regime: "复苏", money_credit: null,
        equity_weight: null, confidence: null, signal_json: null,
      }];
    };
    const d = await macro.getMacro();
    expect(d.signal?.asOf).toBe("2026-10-31"); // Date 形态
    expect(d.signal?.moneyCredit).toBeNull();
    expect(d.signal?.equityWeight).toBeNull();
    expect(d.signal?.signalJson).toBeNull();
    expect(d.history[0].asOf).toBe("2026-10-31");
    expect(d.forecasts[0].status).toBe("pending"); // 只读派生，不写回
  });

  it("字符串形态 as_of + 数值权重/置信规范化", async () => {
    state.handler = (sql) => {
      if (/macro_forecast/.test(sql) || /LIMIT 60/.test(sql)) return [];
      return [{
        as_of: "2026-10-31", regime: "复苏", money_credit: "双宽",
        equity_weight: "0.62", confidence: "0.6",
        signal_json: { phase: "复苏", asset_alloc: { stock: 62 } },
      }];
    };
    const d = await macro.getMacro();
    expect(d.signal).toMatchObject({ asOf: "2026-10-31", moneyCredit: "双宽", equityWeight: 0.62, confidence: 0.6 });
    expect(d.signal?.signalJson).toEqual({ phase: "复苏", asset_alloc: { stock: 62 } });
  });
});

// ─────────────────────────────────────────────────────────────
// advice.ts（P6 零计算只读）
// ─────────────────────────────────────────────────────────────
describe("advice.ts", () => {
  it("无已发布信号 → available=true 但 signal=null（前端显式空态，不编造）", async () => {
    state.handler = () => [];
    const d = await advice.getAdvice();
    expect(d.available).toBe(true);
    expect(d.signal).toBeNull();
    expect(d.drilldown).toBeNull(); // 本期下钻恒空态（AD-08 验收③）
  });

  it("有信号 → MC-07 未确认副标签/五项资产/风格倾斜/金句从 signal_json 提取，零计算", async () => {
    state.handler = (sql) => {
      if (/macro_forecast/.test(sql) || /LIMIT 60/.test(sql)) return [];
      return [{
        as_of: "2026-10-31", regime: "复苏", money_credit: "双宽",
        equity_weight: 62, confidence: 1.0,
        signal_json: {
          phase: "复苏", asset_alloc: { stock: 62, bond: 30, commodity: 0, gold: 4, cash: 4 },
          style_tilt: { size: "大盘", value: "价值" }, sayings: ["金句"],
          _meta: { unconfirmed: true },
        },
      }];
    };
    const d = await advice.getAdvice();
    expect(d.signal?.unconfirmed).toBe(true); // 副标签「政策发力 · 待经济确认」依据
    expect(d.signal?.assetAlloc?.stock).toBe(62);
    expect(d.signal?.styleTilt).toEqual({ size: "大盘", value: "价值" });
    expect(d.signal?.sayings).toEqual(["金句"]);
  });

  it("signal_json 缺 asset_alloc/style_tilt → null（前端按空态处理）", async () => {
    state.handler = (sql) => {
      if (/macro_forecast/.test(sql) || /LIMIT 60/.test(sql)) return [];
      return [{
        as_of: "2026-10-31", regime: "复苏", money_credit: "双宽",
        equity_weight: 62, confidence: 1.0, signal_json: { _meta: {} },
      }];
    };
    const d = await advice.getAdvice();
    expect(d.signal?.assetAlloc).toBeNull();
    expect(d.signal?.styleTilt).toBeNull();
    expect(d.signal?.sayings).toEqual([]);
  });
});
