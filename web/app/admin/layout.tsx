import type { ReactNode } from "react";

/**
 * 管理端布局。
 *
 * 视觉基线 CSS 由根 layout `app/layout.tsx` 统一引入 ——
 * Next.js 只允许在根 layout 导入全局样式，子 layout 重复导入会失效。
 */
export default function AdminLayout({ children }: { children: ReactNode }) {
  return <>{children}</>;
}
