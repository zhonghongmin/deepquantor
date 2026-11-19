/** 空态组件（硬约束 4：缺数据保留区块 + 空态 + 数据时间，不编造值） */
export function EmptyState({ title, sub }: { title: string; sub?: string }) {
  return (
    <div className="empty">
      <span className="t">{title}</span>
      {sub ? <span className="s">{sub}</span> : null}
    </div>
  );
}
