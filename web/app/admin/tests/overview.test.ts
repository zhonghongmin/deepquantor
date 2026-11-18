import { describe, expect, it } from "vitest";

import { deriveL1, judgeL1, notConnected } from "../lib/overview";

/**
 * 需求文档 §5.9.3 P1「健康判定口径」表的单测。
 *
 * 这张表是概览页与运维监控页的**唯一口径**，故口径本身必须有测试锁定。
 */
describe("L1 健康判定（需求文档 §5.9.3 P1）", () => {
  it("待补 = 0 → 运行中（绿）", () => {
    expect(judgeL1({ total: 15, ok: 15, gap: 0, present: 15 })).toEqual({
      tag: "运行中",
      status: "ok",
    });
  });

  it("待补 > 0 且有数据 → 部分滞后（琥珀）", () => {
    expect(judgeL1({ total: 15, ok: 12, gap: 3, present: 15 })).toEqual({
      tag: "部分滞后",
      status: "warn",
    });
  });

  it("全部数据项无任何数据 → 缺失（红）", () => {
    expect(judgeL1({ total: 15, ok: 0, gap: 15, present: 0 })).toEqual({
      tag: "缺失",
      status: "red",
    });
  });

  it("待补 = 0 但一项都没数据 → 仍是缺失（红），不误判为运行中", () => {
    expect(judgeL1({ total: 15, ok: 0, gap: 0, present: 0 })).toEqual({
      tag: "缺失",
      status: "red",
    });
  });

  it("present 缺省时退化为 ok", () => {
    expect(judgeL1({ total: 15, ok: 12, gap: 3 }).tag).toBe("部分滞后");
  });
});

describe("deriveL1 / notConnected", () => {
  it("派生保留计数，不填默认值", () => {
    const l1 = deriveL1({ total: 15, ok: 12, gap: 3, updatedAt: "10-28 02:00", present: 15 });
    expect(l1).toEqual({
      layer: "L1",
      name: "宏观",
      tag: "部分滞后",
      status: "warn",
      total: 15,
      ok: 12,
      gap: 3,
      updatedAt: "10-28 02:00",
    });
  });

  it("未接入层恒为灰态且计数为 0", () => {
    const l2 = notConnected("L2", "中观", "行业景气");
    expect(l2.status).toBe("off");
    expect(l2.tag).toBe("未接入");
    expect(l2.total).toBe(0);
  });
});
