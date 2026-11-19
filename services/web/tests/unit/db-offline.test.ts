/**
 * DB 离线降级路径（硬约束 4：缺数据 → 空态降级，绝不编造兜底值）。
 * 本文件不配置 DATABASE_URL：模块图为全新实例，覆盖 db/offline 分支。
 */
import { beforeAll, describe, expect, it, vi } from "vitest";

const { state, client } = vi.hoisted(() => {
  const client = { calls: [] as string[], query: async () => ({ rows: [] }), release: () => {} };
  const state = { error: null as null | string };
  return { state, client };
});

vi.mock("pg", () => ({
  Pool: class FakePool {
    async query() {
      if (state.error) throw new Error(state.error);
      return { rows: [] };
    }
    async connect() {
      return client;
    }
  },
}));

describe("离线降级（未配置 DATABASE_URL）", () => {
  let db: typeof import("../../src/services/db");
  let overview: typeof import("../../src/services/overview");
  let monitor: typeof import("../../src/services/monitor");
  let macro: typeof import("../../src/services/macro");
  let advice: typeof import("../../src/services/advice");
  let datamgmt: typeof import("../../src/services/datamgmt");

  beforeAll(async () => {
    db = await import("../../src/services/db");
    overview = await import("../../src/services/overview");
    monitor = await import("../../src/services/monitor");
    macro = await import("../../src/services/macro");
    advice = await import("../../src/services/advice");
    datamgmt = await import("../../src/services/datamgmt");
  });

  it("db：getPool()=null，probe 不可用带原因", async () => {
    expect(db.getPool()).toBeNull();
    const p = await db.probe();
    expect(p.available).toBe(false);
    expect(p.reason).toContain("DATABASE_URL");
  });

  it("overview：available=false、l1=null（不编造 0 值）", async () => {
    const d = await overview.getOverview();
    expect(d.available).toBe(false);
    expect(d.l1).toBeNull();
  });

  it("monitor：items=[]", async () => {
    expect((await monitor.getMonitor()).items).toEqual([]);
  });

  it("macro：signal=null、history/forecast 空", async () => {
    const d = await macro.getMacro();
    expect(d.signal).toBeNull();
    expect(d.history).toEqual([]);
    expect(d.forecasts).toEqual([]);
  });

  it("advice：available=false（走 probe 降级分支）", async () => {
    const d = await advice.getAdvice();
    expect(d.available).toBe(false);
    expect(d.signal).toBeNull();
  });

  it("datamgmt：getDataMgmt 空、deleteDataItem 直接拒绝（数据库不可用）", async () => {
    const d = await datamgmt.getDataMgmt();
    expect(d.available).toBe(false);
    expect(d.items).toEqual([]);
    expect(d.jobs).toEqual([]);
    const r = await datamgmt.deleteDataItem("pmi");
    expect(r.ok).toBe(false);
    expect(r.message).toContain("数据库不可用");
  });
});
