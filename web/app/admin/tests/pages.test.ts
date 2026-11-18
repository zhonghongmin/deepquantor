import { describe, expect, it } from "vitest";

import {
  ADMIN_PAGES,
  NAV_GROUPS,
  PAGE_BY_ID,
  TITLES,
  navItemsByGroup,
  type PageId,
} from "../lib/pages";

/**
 * D-21 / D-25 的**运行时**断言。
 *
 * spec_lint.py 已在静态层（集合比对）校验「真值源 = 页面目录 = section = 路由目录」，
 * 本测试在运行时校验同一组不变量，防止后续有人绕过门禁手改页面清单。
 */
describe("页面清单真值源（D-21）", () => {
  it("共 11 个页面", () => {
    expect(ADMIN_PAGES).toHaveLength(11);
  });

  it("id 唯一且与路由锚点同源", () => {
    const ids = ADMIN_PAGES.map((p) => p.id);
    expect(new Set(ids).size).toBe(ids.length);
    expect(ids).toEqual([
      "overview",
      "monitor",
      "datamgmt",
      "research",
      "macro",
      "micro",
      "strategy",
      "advice",
      "ops",
      "users",
      "audit",
    ]);
  });

  it("每个页面都有 PAGE_BY_ID 与 TITLES 映射", () => {
    for (const p of ADMIN_PAGES) {
      expect(PAGE_BY_ID[p.id]).toBe(p);
      expect(TITLES[p.id]).toBe(p.title);
    }
  });

  it("导航分组顺序与效果图一致，且每页恰属一组", () => {
    expect(NAV_GROUPS).toEqual(["总览", "数据与运维", "投研", "运营与管理"]);
    const grouped = navItemsByGroup();
    expect(grouped.flatMap((g) => g.items)).toHaveLength(11);
    for (const g of grouped) {
      expect(NAV_GROUPS).toContain(g.group);
    }
  });

  it("TITLES.micro 与 PAGE_BY_ID.micro 同源（D-25）", () => {
    const micro: PageId = "micro";
    expect(TITLES[micro]).toBe(PAGE_BY_ID[micro].title);
    expect(PAGE_BY_ID[micro].req).toBe("AD-12");
  });
});
