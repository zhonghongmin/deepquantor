import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";

import { Overview } from "../components/Overview";

/**
 * 需求文档 §5.9.3 P1 验收点：
 * 「数据未就绪 → 三层卡显骨架 + 重试，**不显示 0 值**（0 与失败必须可区分）」。
 */
describe("概览页渲染（P1 验收）", () => {
  it("接口失败时显示骨架与重试，且不出现 0 值", () => {
    render(<Overview stamp={null} l1={null} failed onRetry={() => {}} />);

    // 骨架存在
    expect(document.querySelector(".skeleton")).not.toBeNull();
    // 重试入口存在
    expect(screen.getByRole("button", { name: "重试" })).toBeTruthy();
    // 关键：不渲染 0
    expect(document.body.textContent).not.toMatch(/>\s*0\s*</);
  });

  it("未接入层恒为灰态「未接入」", () => {
    render(<Overview stamp="10-28 02:00" l1={null} failed={false} />);
    const grayTags = Array.from(document.querySelectorAll(".tag.gray")).map((e) => e.textContent);
    expect(grayTags.filter((t) => t === "未接入")).toHaveLength(2);
  });

  it("L1 有数据时渲染计数与「运维监控 →」跳转", () => {
    render(
      <Overview
        stamp="10-28 02:00"
        l1={{
          layer: "L1",
          name: "宏观",
          tag: "运行中",
          status: "ok",
          total: 15,
          ok: 15,
          gap: 0,
          updatedAt: "10-28 02:00",
        }}
        failed={false}
      />,
    );
    expect(document.querySelector("#ovL1Total")?.textContent).toBe("15");
    expect(document.querySelector("#ovL1Ok")?.textContent).toBe("15");
    expect(document.querySelector("#ovL1Gap")?.textContent).toBe("0");
    expect(document.querySelector("#ovStamp")?.textContent).toContain("10-28 02:00");
    expect(screen.getByText("运维监控 →")).toBeTruthy();
  });

  it("L1 红色「缺失」态映射为 .tag.bad", () => {
    render(
      <Overview
        stamp={null}
        l1={{
          layer: "L1",
          name: "宏观",
          tag: "缺失",
          status: "red",
          total: 15,
          ok: 0,
          gap: 15,
          updatedAt: null,
        }}
        failed={false}
      />,
    );
    expect(document.querySelector(".tag.bad")?.textContent).toBe("缺失");
  });
});
