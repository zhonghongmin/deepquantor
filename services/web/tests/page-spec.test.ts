/**
 * 页面符合性测试（dq-test-skill 硬约束 1~4）
 *
 * 断言来源 = 设计基线，非实现自证：
 *  - 《需求文档》AD-08 / AD-09 / AD-10 / DL-07 / DL-08 / C-13 / D-18 / D-30 / MC-07
 *  - 《管理端效果图》#overview / #monitor / #datamgmt / #macro / #advice 锚点
 *  - dq-gen-ui-skill design-baseline.md §2 断点矩阵（8 档）+ §3 硬形态（抽屉 / stacktable）
 *
 * 「即判失败」条款逐条对应：
 *  - AD-10 ② 补零 / 前值填充 → TestMacro ②（折线区空态、无伪造序列）
 *  - AD-10 ④ 伪造命中率     → TestMacro ④（仅「待回测」，无百分比数值）
 *  - AD-08 ② 迁移残留       → TestAdvice 负断言（不得出现维度卡 / 折线 / 回溯图）
 *  - 硬约束 4 缺数据反例     → 空态 + 数据时间，非整块隐藏、非编造值
 *
 * 运行前提：next build 已产出 .next；测试自起 `next start -p 3100`（空库空态模式）。
 */
import { spawn, type ChildProcess } from "node:child_process";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { afterAll, beforeAll, describe, expect, it } from "vitest";

const PORT = 3100;
const BASE = `http://127.0.0.1:${PORT}`;
const ROOT = join(__dirname, "..");

let server: ChildProcess;

async function waitReady(): Promise<void> {
  for (let i = 0; i < 60; i++) {
    try {
      const res = await fetch(`${BASE}/api/overview`);
      if (res.ok) return;
    } catch { /* not ready yet */ }
    await new Promise((r) => setTimeout(r, 500));
  }
  throw new Error("next start 未在 30s 内就绪");
}

beforeAll(async () => {
  server = spawn("npx", ["next", "start", "-p", String(PORT)], {
    cwd: ROOT,
    shell: true,
    stdio: "ignore",
  });
  await waitReady();
}, 90000);

afterAll(() => {
  server?.kill();
});

async function page(path: string): Promise<string> {
  const res = await fetch(`${BASE}${path}`);
  expect(res.status, `GET ${path}`).toBe(200);
  return res.text();
}

const slice = (html: string, startMark: string, endMark: string): string => {
  const a = html.indexOf(startMark);
  const b = endMark ? html.indexOf(endMark, a + startMark.length) : html.length;
  expect(a, `标记缺失：${startMark}`).toBeGreaterThanOrEqual(0);
  return html.slice(a, b);
};

// ─────────────────────────────────────────────────────────────
// P1 概览 #overview（AD-09）
// ─────────────────────────────────────────────────────────────
describe("P1 #overview 符合性（AD-09）", () => {
  // 页头「数据截至」与三层卡为数据加载后的条件渲染（空库 SSR 为加载态）→ 源级断言
  const src = () => readFileSync(join(ROOT, "src/app/admin/overview/page.tsx"), "utf-8");

  it("OV-1 页头含「数据截至」元数据标注（源级：条件渲染）", () => {
    expect(src()).toContain("数据截至");
  });

  it("OV-2/OV-3 三层链路卡顺序 L1→L2→L3，L2/L3 恒灰态不可点（源级：条件渲染）", () => {
    const s = src();
    const l1 = s.indexOf("L1");
    const l2 = s.indexOf("L2");
    const l3 = s.indexOf("L3");
    expect(l1).toBeGreaterThan(0);
    expect(l2).toBeGreaterThan(l1);
    expect(l3).toBeGreaterThan(l2);
    // 恒灰态：领域说明保留（不删区块），且无「接入后」可点入口
    expect((s.match(/未接入/g) ?? []).length).toBeGreaterThanOrEqual(2);
    expect((s.match(/暂无采集任务/g) ?? []).length).toBeGreaterThanOrEqual(2);
    const l23 = s.slice(l2, l3) + s.slice(l3);
    expect(l23).not.toContain("href=");
    expect(l23).not.toContain("<button");
  });
});

// ─────────────────────────────────────────────────────────────
// P2 运维监控 #monitor（AD-02）
// ─────────────────────────────────────────────────────────────
describe("P2 #monitor 符合性（AD-02）", () => {
  // 数据项表为数据加载后的条件渲染（空库 SSR 为加载态）→ 表头/堆叠契约源级断言
  const src = () => readFileSync(join(ROOT, "src/app/admin/monitor/page.tsx"), "utf-8");

  it("MO-5 数据项表 7 列表头齐全且顺序固定（源级：条件渲染）", () => {
    const s = src();
    const cols = ["数据项", "频率", "库内最新期次", "官方最新可获取", "待补", "最近采集时间", "状态"];
    let pos = -1;
    for (const c of cols) {
      const i = s.search(new RegExp(`<th[^>]*>${c}`)); // 允许 th 带 title/ⓘ 等属性后缀
      expect(i, `表头缺失：${c}`).toBeGreaterThan(pos);
      pos = i;
    }
  });

  it("MO-2 状态条 4 计数（监测/正常/待补/无数据口径）存在", async () => {
    const html = await page("/admin/monitor");
    for (const w of ["监测", "正常", "待补", "无数据"]) {
      expect(html).toContain(w);
    }
  });

  it("MO-5 表格满足 stacktable 契约：td 必须带 data-l（≤560 硬形态 2，源级）", () => {
    expect(src()).toContain('data-l="数据项"');
  });
});

// ─────────────────────────────────────────────────────────────
// P3 数据管理 #datamgmt（DL-07 / DL-08 弹窗为交互态，SSR 不可见 → 源级断言）
// ─────────────────────────────────────────────────────────────
describe("P3 #datamgmt 符合性（AD-02 / DL-07 / DL-08）", () => {
  const src = () => readFileSync(join(ROOT, "src/app/admin/datamgmt/page.tsx"), "utf-8");

  it("DM-1 两 Tab：数据项 / 定时任务", async () => {
    const html = await page("/admin/datamgmt");
    expect(html).toContain("数据项");
    expect(html).toContain("定时任务");
  });

  it("DL-07 分支 A：被引用拒绝弹窗仅「我知道了」，无确认删除入口", () => {
    const s = src();
    const branchA = slice(s, "DL-07 分支 A", "DL-08 分支 B");
    expect(branchA).toContain("我知道了");
    expect(branchA).not.toContain("确认删除");
  });

  it("DL-08 分支 B：先列删除范围再二次确认「确认删除并清除数据」", () => {
    const s = src();
    expect(slice(s, "DL-08 分支 B")).toContain("确认删除并清除数据");
  });

  it("DM-2 新增/编辑表单因子层级必填标注（*）", () => {
    expect(src()).toContain("因子层级 *");
  });
});

// ─────────────────────────────────────────────────────────────
// P6 投资建议 #advice（AD-08 两段式）
// ─────────────────────────────────────────────────────────────
describe("P6 #advice 符合性（AD-08）", () => {
  it("AD-08 ② 迁移负断言：本页不得出现 4 维度卡 / 近 6 月折线 / 5 年回溯图 / 预测信号区", async () => {
    const html = await page("/admin/advice");
    for (const banned of [
      "② 数据支撑", "③ 日频辅助预警", "④ 预测信号", "⑤ 周期回溯",
      "经济 · 产出", "近 6 个月走势", "九宫格", "折线",
    ]) {
      expect(html, `迁移残留：${banned}`).not.toContain(banned);
    }
  });

  it("AD-6「当前可执行」结论条存在（C-13：预算 vs 实际持仓两段，源级：信号加载后渲染）", () => {
    const s = readFileSync(join(ROOT, "src/app/admin/advice/page.tsx"), "utf-8");
    expect(s).toContain("当前可执行");
    expect(s).toContain("目标风险预算");
    expect(s).toContain("货币资金");
  });

  it("AD-5 下钻理由链缺数据 → 空态 + 数据时间，不编造理由（硬约束 4，源级：信号加载后渲染）", () => {
    const s = readFileSync(join(ROOT, "src/app/admin/advice/page.tsx"), "utf-8");
    expect(s).toContain("下钻理由链待接入");
    expect(s).toContain("数据截至");
  });

  it("空态反例：无已发布信号时显式空态而非 0 值兜底", async () => {
    const html = await page("/admin/advice");
    expect(html).toContain("暂无已发布宏观信号");
    expect(html).toContain("数据不编造");
  });
});

// ─────────────────────────────────────────────────────────────
// P10 宏观数据 #macro（AD-10 五区单列）
// ─────────────────────────────────────────────────────────────
describe("P10 #macro 符合性（AD-10）", () => {
  it("AD-10 五区标题齐全且顺序固定：①主判→②数据支撑→③预警→④预测→⑤回溯", async () => {
    const html = await page("/admin/macro");
    const marks = ["① 当前结论", "② 数据支撑", "③ 日频辅助预警", "④ 预测信号", "⑤ 周期回溯"];
    let pos = -1;
    for (const m of marks) {
      const i = html.indexOf(m);
      expect(i, `区块缺失或顺序错误：${m}`).toBeGreaterThan(pos);
      pos = i;
    }
  });

  it("AD-10 ②【即判失败：补零/前值填充】4 张维度卡存在，折线区空态、无伪造序列", async () => {
    const html = await page("/admin/macro");
    const sec2 = slice(html, "② 数据支撑", "③ 日频辅助预警");
    for (const dim of ["经济 · 产出", "通胀", "货币", "信用"]) {
      expect(sec2, `维度卡缺失：${dim}`).toContain(dim);
    }
    // 采数未落库 → 每卡空态（4 处），且不渲染任何 SVG 折线点集
    expect((sec2.match(/待数据落库/g) ?? []).length).toBe(4);
    expect(sec2).not.toContain("polyline");
    expect(sec2).not.toContain("points=");
  });

  it("AD-10 ③ D-30 后移：空态占位「后续迭代 · D-30」，区块内零数据行", async () => {
    const html = await page("/admin/macro");
    const sec3 = slice(html, "③ 日频辅助预警", "④ 预测信号");
    expect(sec3).toContain("后续迭代 · D-30");
    expect(sec3).not.toContain("<td");
    expect(sec3).not.toContain("<tr");
  });

  it("AD-10 ④【即判失败：伪造命中率】预测信号仅「待回测」，无百分比数值", async () => {
    const html = await page("/admin/macro");
    const sec4 = slice(html, "④ 预测信号", "⑤ 周期回溯");
    expect(sec4).toContain("待回测");
    expect(sec4).not.toMatch(/\d+(\.\d+)?\s*%/);
  });

  it("AD-10 ⑤ 回溯不足 5 年 → 「待回测」空态，且标注示例数据性质", async () => {
    const html = await page("/admin/macro");
    const sec5 = slice(html, "⑤ 周期回溯");
    expect(sec5).toMatch(/待回测|示例数据|历史批次/);
  });

  it("D-18 DR001 零输入：主判区不引用日频利率字段", async () => {
    const html = await page("/admin/macro");
    expect(html).not.toContain("DR001");
  });

  it("MC-05 只读契约：页面标注只读 signal.macro_signal、不重算", async () => {
    expect(await page("/admin/macro")).toContain("只读 signal.macro_signal");
  });
});

// ─────────────────────────────────────────────────────────────
// design-baseline §2 断点矩阵（8 档）+ §3 硬形态（源级断言）
// ─────────────────────────────────────────────────────────────
describe("design-baseline 断点与窄屏形态", () => {
  const css = () => readFileSync(join(ROOT, "src/app/globals.css"), "utf-8");

  it("8 档断点全部以 max-width 降级（1420/1100/1080/980/900/820/760/560）", () => {
    const cssText = css();
    for (const bp of [1420, 1100, 1080, 980, 900, 820, 760, 560]) {
      expect(cssText, `缺断点 ≤${bp}`).toContain(`@media (max-width: ${bp}px)`);
    }
    // 禁止用默认 min-width sm/md/lg 顶替（§2 语义相反）
    expect(cssText).not.toMatch(/@media\s*\(min-width/);
  });

  it("硬形态 1（≤900）：侧栏固定抽屉 + navToggle 入口 + scrim 遮罩", () => {
    const b900 = slice(css(), "@media (max-width: 900px)", "@media (max-width: 820px)");
    expect(b900).toContain("translateX(-100%)");
    expect(b900).toContain(".side.open");
    expect(b900).toContain(".scrim.show");
  });

  it("硬形态 2（≤560）：stacktable — thead 隐藏、td::before=attr(data-l)、首列不显示标签", () => {
    const b560 = slice(css(), "@media (max-width: 560px)");
    expect(b560).toContain("table.stacktable thead { display: none; }");
    expect(b560).toContain("content: attr(data-l)");
    expect(b560).toContain("td:first-child::before { content: none; }");
  });

  it("表格均带 data-l 字段名（monitor / datamgmt 源级）", () => {
    expect(readFileSync(join(ROOT, "src/app/admin/monitor/page.tsx"), "utf-8")).toContain('data-l="数据项"');
    expect(readFileSync(join(ROOT, "src/app/admin/datamgmt/page.tsx"), "utf-8")).toContain('data-l="因子层级"');
  });

  it("涨红跌绿令牌符合 A 股惯例（up=红 down=绿，不得反用，tailwind.config 源级）", () => {
    const cfg = readFileSync(join(ROOT, "tailwind.config.ts"), "utf-8");
    const up = cfg.match(/up:\s*"(#[0-9a-fA-F]{6})"/)?.[1];
    const down = cfg.match(/down:\s*"(#[0-9a-fA-F]{6})"/)?.[1];
    expect(up).toBeDefined();
    expect(down).toBeDefined();
    // 红色 R 分量显著高于 G；绿色 G 分量显著高于 R
    const ch = (h: string) => [parseInt(h.slice(1, 3), 16), parseInt(h.slice(3, 5), 16), parseInt(h.slice(5, 7), 16)];
    const [ur, ug] = ch(up!);
    const [dr, dg] = ch(down!);
    expect(ur).toBeGreaterThan(ug);
    expect(dg).toBeGreaterThan(dr);
  });
});

// ─────────────────────────────────────────────────────────────
// API 契约（统一信封 {code,message,data}）
// ─────────────────────────────────────────────────────────────
describe("API 契约信封", () => {
  const endpoints = [
    "/api/overview", "/api/monitor", "/api/macro", "/api/advice",
    "/api/datamgmt/items", "/api/datamgmt/jobs",
  ];

  it.each(endpoints)("GET %s 返回 {code,message,data} 结构（空库 code=0 空态降级）", async (ep) => {
    const res = await fetch(`${BASE}${ep}`);
    expect(res.status).toBe(200);
    const body = (await res.json()) as { code: unknown; message: unknown; data: unknown };
    expect(typeof body.code).toBe("number");
    expect(typeof body.message).toBe("string");
    expect("data" in body).toBe(true);
  });
});
