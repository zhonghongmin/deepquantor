import type { ReactNode } from "react";

import { Sidebar } from "./Sidebar";
import { PAGE_BY_ID, type PageId } from "../lib/pages";

/**
 * 管理端外壳 —— 侧栏 + 顶栏 + 内容区。
 *
 * 结构对齐《管理端效果图.html》：`.app` > `.side`（含 brand / nav / side-foot）+ `.main`。
 * 侧栏导航项由 `navItemsByGroup()` 从 `pages.ts` 派生，**禁止在此处硬编码页面清单**（D-21）。
 */
export function AdminShell({
  active,
  children,
}: {
  /** 当前页锚点 */
  active: PageId;
  children: ReactNode;
}) {
  const page = PAGE_BY_ID[active];

  return (
    <div className="app">
      <aside className="side">
        <div className="brand">
          <div>
            <b>量化选股系统</b>
            <small>量化投研 · 管理端</small>
          </div>
        </div>
        <Sidebar active={active} />
        <div className="side-foot">
          <div className="av">管</div>
          <div>
            管理员
            <small>admin@example.com</small>
          </div>
        </div>
      </aside>

      <div className="main">
        <div className="topbar">
          <div className="tleft">
            <div className="crumb">
              <b>{page.title}</b>
              <span>{page.subtitle}</span>
            </div>
          </div>
          <div className="right">
            <span>
              <span className="dot" />
              系统正常
            </span>
            <span className="mono">—</span>
          </div>
        </div>
        <div className="content">{children}</div>
      </div>
    </div>
  );
}
