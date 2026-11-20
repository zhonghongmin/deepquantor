"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { NAV_ITEMS_META } from "@/lib/nav";

/** 侧栏分组（对齐 _ref/管理端效果图.html #nav）：总览 / 数据与运维 / 投研 / 运营与管理。 */
const NAV: { group: string; items: { key: string; label: string; ic: string; inScope: boolean }[] }[] = [
  { group: "总览", items: [{ key: "overview", label: "概览 Dashboard", ic: "▦", inScope: true }] },
  {
    group: "数据与运维",
    items: [
      { key: "monitor", label: "运维监控", ic: "◉", inScope: true },
      { key: "datamgmt", label: "数据管理", ic: "⚙", inScope: true },
    ],
  },
  {
    group: "投研",
    items: [
      { key: "research", label: "投研与回测", ic: "📈", inScope: false },
      { key: "macro", label: "宏观数据", ic: "◎", inScope: true },
      { key: "micro", label: "微观数据", ic: "⊞", inScope: false },
      { key: "strategy", label: "策略与因子", ic: "Σ", inScope: false },
      { key: "advice", label: "投资建议（对内）", ic: "❖", inScope: true },
    ],
  },
  {
    group: "运营与管理",
    items: [
      { key: "ops", label: "运营看板", ic: "📊", inScope: false },
      { key: "users", label: "用户管理", ic: "👤", inScope: false },
      { key: "audit", label: "权限与审计", ic: "🛡", inScope: false },
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
        <div className="brand">
          {/* logo：白底圆角 + 蓝色柱形图（对齐效果图 brand 形态） */}
          <svg viewBox="0 0 34 34" className="brand-logo" aria-hidden="true">
            <rect width="34" height="34" rx="8" fill="#fff" />
            <rect x="7" y="17" width="4.5" height="10" rx="1" fill="#0060c0" />
            <rect x="14.75" y="11" width="4.5" height="16" rx="1" fill="#0a2a4e" />
            <rect x="22.5" y="6" width="4.5" height="21" rx="1" fill="#0060c0" />
            <path d="M8 13 L17 8 L26 11" stroke="#f59e0b" strokeWidth="2" fill="none" strokeLinecap="round" />
          </svg>
          <div>
            <b>量化选股系统</b>
            <small>量化投研 · 管理端</small>
          </div>
        </div>
        <nav className="nav flex-1 overflow-y-auto pb-4" id="nav">
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
                  <span className="ic" aria-hidden="true">
                    {it.ic}
                  </span>
                  {it.label}
                </Link>
              ))}
            </div>
          ))}
        </nav>
        <div className="side-foot">
          <div className="av">管</div>
          <div>
            管理员
            <small>admin@example.com</small>
          </div>
        </div>
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
