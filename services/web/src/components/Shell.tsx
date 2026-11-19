"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { NAV_ITEMS_META } from "@/lib/nav";

/** 侧栏分组（需求文档 §5.9.3：总览 / 数据与运维 / 投研 / 运营与管理）。 */
const NAV: { group: string; items: { key: string; label: string; inScope: boolean }[] }[] = [
  { group: "总览", items: [{ key: "overview", label: "概览 Dashboard", inScope: true }] },
  {
    group: "数据与运维",
    items: [
      { key: "monitor", label: "运维监控", inScope: true },
      { key: "datamgmt", label: "数据管理", inScope: true },
      { key: "macro", label: "宏观数据", inScope: true },
      { key: "micro", label: "微观数据", inScope: false },
    ],
  },
  {
    group: "投研",
    items: [
      { key: "research", label: "投研与回测", inScope: false },
      { key: "strategy", label: "策略与因子", inScope: false },
      { key: "advice", label: "投资建议（对内版）", inScope: true },
    ],
  },
  {
    group: "运营与管理",
    items: [
      { key: "ops", label: "运营看板", inScope: false },
      { key: "users", label: "用户管理", inScope: false },
      { key: "audit", label: "权限与审计", inScope: false },
    ],
  },
];

export default function Shell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const current = pathname.split("/").pop() ?? "overview";
  const [open, setOpen] = useState(false);

  useEffect(() => setOpen(false), [pathname]); // 路由切换关闭抽屉

  return (
    <div className="app-shell">
      <aside className={`side ${open ? "open" : ""}`}>
        <div className="px-5 pt-5 pb-3">
          <div className="text-[16px] font-bold tracking-wide">DeepQuantor</div>
          <div className="text-[11px] text-[#7f95ab] mt-0.5">管理端 · 内部</div>
        </div>
        <nav className="nav flex-1 overflow-y-auto pb-4">
          {NAV.map((g) => (
            <div key={g.group}>
              <div className="nav-group">{g.group}</div>
              {g.items.map((it) => (
                <Link
                  key={it.key}
                  href={`/admin/${it.key}`}
                  className={current === it.key ? "active" : ""}
                  onClick={() => setOpen(false)}
                >
                  {it.label}
                </Link>
              ))}
            </div>
          ))}
        </nav>
      </aside>
      <div
        className={`scrim ${open ? "show" : ""}`}
        onClick={() => setOpen(false)}
        aria-hidden="true"
      />
      <div>
        {/* ≤900 顶栏：抽屉入口（design-baseline §3 硬形态 1） */}
        <div className="topbar">
          <button className="navToggle" onClick={() => setOpen(!open)} aria-label="打开导航">
            ☰
          </button>
          <span className="text-[14px] font-semibold">DeepQuantor 管理端</span>
        </div>
        <main className="content">{children}</main>
      </div>
    </div>
  );
}
