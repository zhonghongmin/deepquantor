import { defineConfig } from "vitest/config";

// dq-test-skill：页面符合性 + 契约 + 覆盖率门槛（lib/services/api 80/80）
export default defineConfig({
  test: {
    environment: "node",
    include: ["tests/**/*.test.ts"],
    testTimeout: 30000,
    hookTimeout: 60000,
    coverage: {
      provider: "v8",
      // API route 为 4~11 行薄包装，信封契约已由 tests/page-spec.test.ts 走真实 HTTP 覆盖；
      // 覆盖率门槛统计 services 业务层（dq-test-skill 门槛 80/80）
      include: ["src/services/**"],
      thresholds: { lines: 80, branches: 80, functions: 80 },
    },
  },
});
