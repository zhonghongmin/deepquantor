import type { Config } from "tailwindcss";

/**
 * design-baseline.md §5：效果图用 max-width 逐级降级，禁用默认 sm/md/lg（语义相反）。
 * 8 档断点集中具名，逐档对齐效果图，不得四舍五入或合并。
 */
const config: Config = {
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        navy: "#003058",
        navy2: "#013a6b",
        brand: "#0060C0",
        "brand-soft": "#e8f1fc",
        bg: "#f4f6f9",
        line: "#e6ebf1",
        line2: "#eef2f6",
        text: "#1f2a37",
        muted: "#6b7785",
        muted2: "#9aa6b2",
        up: "#e5484d",          // 涨（中国市场惯例，不得反用）
        "up-bg": "#fdeaea",
        down: "#16a34a",        // 跌
        "down-bg": "#e7f6ec",
        warn: "#d98a00",
        "warn-bg": "#fdf3e0",
        chip: "#f1f5f9",
      },
    },
  },
  plugins: [],
};
export default config;
