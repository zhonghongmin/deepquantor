"use client";

import Link from "next/link";

import { navItemsByGroup, type PageId } from "../lib/pages";

/**
 * 侧栏导航 —— 导航项从 `pages.ts` 派生，不另抄一份。
 *
 * D-21：导航项数必须等于页数，故此处禁止硬编码页面名。
 * `data-p` 与效果图基线的锚点标识一一对应（`data-p="micro"` ↔ `#micro`）。
 */
export function Sidebar({ active }: { active: PageId }) {
  return (
    <nav className="nav" id="nav">
      {navItemsByGroup().map(({ group, items }) => (
        <div key={group}>
          <div className="grp">{group}</div>
          {items.map((p) => (
            <Link
              key={p.id}
              href={`/admin/${p.id}`}
              data-p={p.id}
              className={active === p.id ? "active" : undefined}
              scroll={false}
            >
              <span className="ic">{p.icon}</span>
              {p.label}
            </Link>
          ))}
        </div>
      ))}
    </nav>
  );
}
