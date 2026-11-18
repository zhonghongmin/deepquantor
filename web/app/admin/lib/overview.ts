/**
 * 概览页三层数据链路 —— 健康度判定与派生。
 *
 * **唯一口径来源**：需求文档 §5.9.3 P1「健康判定口径」表。
 * 各页不得各算各的：L1 计数与运维监控页同源一致。
 */

export type LayerId = "L1" | "L2" | "L3";
/** ok=绿 / warn=琥珀 / red=红 / off=灰（未接入） */
export type LayerStatus = "ok" | "warn" | "red" | "off";

export interface LayerHealth {
  /** 层级标识 */
  readonly layer: LayerId;
  /** 层名 */
  readonly name: string;
  /** 状态标签文案 */
  readonly tag: string;
  /** 状态类别 */
  readonly status: LayerStatus;
  /** 数据项总数 */
  readonly total: number;
  /** 正常项数 */
  readonly ok: number;
  /** 期待补项数 */
  readonly gap: number;
  /** 最近更新时间 */
  readonly updatedAt: string | null;
  /** 领域说明（未接入层展示） */
  readonly note?: string;
}

/**
 * 健康判定表（需求文档 §5.9.3 P1）——三档取值：
 *
 * | L1 状态标签   | 触发条件                        | 含义                                   |
 * | ------------- | ------------------------------- | -------------------------------------- |
 * | `运行中`（绿） | 待补期数 = 0                    | 全部数据项已是最新期，无需人工介入     |
 * | `部分滞后`（琥珀）| 待补期数 > 0 且至少 1 项有数据  | 有缺口，需到运维监控页增量补齐         |
 * | `缺失`（红）  | 全部数据项均无任何数据           | 采集链路整体异常，需排查               |
 *
 * 「缺失」是「部分滞后」的**前置特判**：完全没有数据的场景不是「滞后」，
 * 而是链路异常，必须红色区分，否则会漏掉最严重的一类故障。
 */
export function judgeL1(input: {
  /** 数据项总数 */
  total: number;
  /** 正常（已有数据且已到最新期）项数 */
  ok: number;
  /** 期待补期数 */
  gap: number;
  /** 已落库（哪怕落后）的数据项数 —— 判定「是否完全无数据」用 */
  present?: number;
}): { tag: string; status: LayerStatus } {
  // 全部数据项无任何数据 → 链路异常，红色「缺失」
  // present 未给出时退化为 ok（调用方应显式给出「已落库项数」）
  const present = input.present ?? input.ok;
  if (input.total > 0 && present === 0) {
    return { tag: "缺失", status: "red" };
  }
  if (input.gap === 0) {
    return { tag: "运行中", status: "ok" };
  }
  // 待补 > 0 且至少 1 项有数据 → 有缺口，琥珀「部分滞后」
  return { tag: "部分滞后", status: "warn" };
}

/** 未接入层（灰态） */
export function notConnected(layer: LayerId, name: string, note: string): LayerHealth {
  return {
    layer,
    name,
    tag: "未接入",
    status: "off",
    total: 0,
    ok: 0,
    gap: 0,
    updatedAt: null,
    note,
  };
}

/**
 * 派生 L1 概览数据。
 *
 * 需求文档 P1 验收：接口失败时显示骨架与重试，**不显示 0 值**——
 * 因此这里不提供默认值，失败态由调用方以 `null` 表达并渲染骨架。
 */
export function deriveL1(input: {
  total: number;
  ok: number;
  gap: number;
  updatedAt: string | null;
  /** 已落库的数据项数（区别于 ok） */
  present?: number;
}): LayerHealth {
  const judged = judgeL1(input);  return {
    layer: "L1",
    name: "宏观",
    tag: judged.tag,
    status: judged.status,
    total: input.total,
    ok: input.ok,
    gap: input.gap,
    updatedAt: input.updatedAt,
  };
}
