import { defineConfig } from "vitest/config";
import path from "node:path";

export default defineConfig({
  // 不引 @vitejs/plugin-react：它要 vite 7，与 vitest 2 的 vite 5 冲突。
  // JSX 交给 esbuild 内置的 automatic 转换即可（React 17+ 新 JSX 变换）。
  esbuild: {
    jsx: "automatic",
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./vitest.setup.ts"],
    include: ["app/**/*.{test,spec}.{ts,tsx}"],
  },
  resolve: {
    alias: { "@": path.resolve(__dirname, ".") },
  },
});
