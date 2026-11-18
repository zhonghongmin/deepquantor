/**
 * 管理端数据访问层 —— 当前为**占位实现**。
 *
 * 本期管理端前端先落地「结构 + 视觉 + 口径」，数据接口尚未接通。
 * 这里定义接口形状与失败语义，让页面与 API 路由的契约先固化：
 *
 * - `fetchOverview()` 返回 `OverviewResult`，**失败时返回 failed=true 而非 0 值**
 *   （需求文档 §5.9.3 P1：0 与失败必须可区分）。
 * - 页面拿到 failed 后渲染骨架 + 重试，不渲染「0」。
 *
 * 接入真实数据源时，只需替换 `fetchOverview` 的内部实现，契约不变。
 */

import { deriveL1, type LayerHealth } from "./overview";

export interface OverviewResult {
  /** 数据截至时点；null 表示未知 */
  readonly stamp: string | null;
  /** L1 宏观健康度；null 表示接口未就绪 */
  readonly l1: LayerHealth | null;
  /** 是否失败（失败 → 骨架 + 重试，绝不显示 0） */
  readonly failed: boolean;
}

/**
 * API 传输形状。
 *
 * 字段类型与 `LayerHealth` 严格对齐（`layer` 是 LayerId、`status` 是 LayerStatus），
 * 避免 JSON 反序列化后类型被放宽成 `string` 而丢掉穷尽性检查。
 */
export interface OverviewPayload {
  stamp: string | null;
  l1: Pick<
    LayerHealth,
    "layer" | "name" | "tag" | "status" | "total" | "ok" | "gap" | "updatedAt"
  > | null;
  failed: boolean;
}

/**
 * 拉取概览数据。
 *
 * 当前返回「接口未就绪」——因为后端尚未接通。
 * **不是**返回全 0：那样页面会把「失败」误显示成「一切正常」。
 */
export async function fetchOverview(): Promise<OverviewResult> {
  return { stamp: null, l1: null, failed: true };
}

/** 把内部结果转成 API 传输形状 */
export function toPayload(r: OverviewResult): OverviewPayload {
  return {
    stamp: r.stamp,
    l1: r.l1
      ? {
          layer: r.l1.layer,
          name: r.l1.name,
          tag: r.l1.tag,
          status: r.l1.status,
          total: r.l1.total,
          ok: r.l1.ok,
          gap: r.l1.gap,
          updatedAt: r.l1.updatedAt,
        }
      : null,
    failed: r.failed,
  };
}

export { deriveL1 };
