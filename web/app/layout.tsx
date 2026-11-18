import type { Metadata } from "next";
import type { ReactNode } from "react";

import "./globals.css";
import "./admin/admin.css";

export const metadata: Metadata = {
  title: "量化选股系统 · 管理端",
  description: "量化投研管理端",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}
