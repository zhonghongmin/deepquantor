"use client";

import { deriveL1, notConnected, type LayerHealth, type LayerStatus } from "../lib/overview";

/**
 * 概览 Dashboard（`#overview` · AD-09）
 *
 * 需求文档 §5.9.3 P1：全页**只有一行三层数据链路卡片**，没有别的模块。
 * 只回答「数据下载是否正常」，不含日志、不含明细表、不下钻。
 */

/** 状态 → 标签配色（与效果图 `.tag.ok/.warn/.bad/.gray` 一一对应） */
const TAG_CLASS: Record<LayerStatus, string> = {
  ok: "ok",
  warn: "warn",
  red: "bad",
  off: "gray",
};

interface Props {
  /** 数据截至时点；null 表示接口未就绪 */
  stamp: string | null;
  /** L1 宏观；null 表示接口失败 → 渲染骨架与重试，不显示 0 值 */
  l1: LayerHealth | null;
  /** 接口是否失败 */
  failed?: boolean;
  onRetry?: () => void;
}

export function Overview({ stamp, l1, failed = false, onRetry }: Props) {
  const l2 = notConnected("L2", "中观", "行业景气 · 产业链上下游 · 板块资金");
  const l3 = notConnected("L3", "微观", "六维因子 · 行业综合评分优先 · 个股与行业 ETF 同级");

  return (
    <>
      <div className="page-h">
        <div>
          <h2>概览</h2>
          <p>一眼看数据下载是否正常：按宏观 / 中观 / 微观三层汇总各层采集健康度</p>
        </div>
        <span className="pill" id="ovStamp">
          {stamp ? `数据截至 ${stamp}` : "数据截至 —"}
        </span>
      </div>

      <div className="layer-row">
        <LayerCard layer={l1} fallbackName="宏观" failed={failed} onRetry={onRetry} />
        <LayerCard layer={l2} fallbackName="中观" />
        <LayerCard layer={l3} fallbackName="微观" />
      </div>
    </>
  );
}

function LayerCard({
  layer,
  fallbackName,
  failed = false,
  onRetry,
}: {
  layer: LayerHealth | null;
  fallbackName: string;
  failed?: boolean;
  onRetry?: () => void;
}) {
  const isOff = layer?.status === "off";

  return (
    <div className={isOff ? "layer off" : "layer on"}>
      <div className="lhd">
        <span className="lnum">{layer?.layer ?? "L1"}</span>
        <b>{layer?.name ?? fallbackName}</b>
        {failed ? (
          <span className="tag gray">加载中</span>
        ) : (
          <span className={`tag ${TAG_CLASS[layer?.status ?? "off"]}`}>
            {layer?.tag ?? "—"}
          </span>
        )}
      </div>

      {isOff ? (
        <>
          <div className="lbody mute">{layer?.note}</div>
          <div className="lfoot">
            <span>暂无采集任务</span>
          </div>
        </>
      ) : (
        <>
          <div className="lbody">
            <Count
              id="ovL1Total"
              value={layer?.total}
              failed={failed}
              fallback="数据项"
            />
            <Count
              id="ovL1Ok"
              value={layer?.ok}
              failed={failed}
              fallback="正常"
              tone="green"
            />
            <Count
              id="ovL1Gap"
              value={layer?.gap}
              failed={failed}
              fallback="期待补"
              tone="amber"
            />
          </div>
          <div className="lfoot">
            <span id="ovL1Foot">
              {failed ? "最近更新 —" : `最近更新 ${layer?.updatedAt ?? "—"}`}
            </span>
            <a className="lk" href="#monitor">
              运维监控 →
            </a>
          </div>
          {failed && onRetry ? (
            <div className="retry">
              <button type="button" onClick={onRetry}>
                重试
              </button>
            </div>
          ) : null}
        </>
      )}
    </div>
  );
}

/**
 * 计数单元格。
 *
 * 需求文档 P1 验收：接口失败显示骨架与重试，**不显示 0 值** ——
 * 所以 value 为 null 时渲染骨架，绝不渲染 "0"。
 */
function Count({
  id,
  value,
  failed,
  fallback,
  tone,
}: {
  id?: string;
  value: number | undefined;
  failed: boolean;
  fallback: string;
  tone?: "green" | "amber";
}) {
  const cls = tone ? ` ${tone}` : "";
  if (failed || value === undefined) {
    return (
      <div className="li">
        <b id={id} className={`skeleton${cls}`}>
          --
        </b>
        <span>{fallback}</span>
      </div>
    );
  }
  return (
    <div className="li">
      <b id={id} className={cls.trim()}>
        {value}
      </b>
      <span>{fallback}</span>
    </div>
  );
}

export { deriveL1 };
