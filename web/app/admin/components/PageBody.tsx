import { PAGE_BY_ID, type PageId } from "../lib/pages";

/**
 * 未实现页的统一占位体。
 *
 * 需求文档 §5.9.3 只给了 P1（概览）的完整规格，其余页 P2–P11 本期不实现。
 * 占位体必须**明确写清「未实现 + 对应需求条目 + 一期目标」**，
 * 不允许留白 —— 留白会被误读成「已实现但没数据」。
 *
 * 标题 / 副标 / 需求条目全部取自 `pages.ts` 真值源，此处不硬编码。
 */
export function PageBody({ pageId }: { pageId: PageId }) {
  const page = PAGE_BY_ID[pageId];

  return (
    <>
      <div className="page-h">
        <div>
          <h2>{page.title}</h2>
          <p>{page.subtitle}</p>
        </div>
      </div>

      <div className="todo-card">
        <h3>本页本期未实现</h3>
        <p>
          该页属于后续迭代范围。本期管理端只落地「概览」页（AD-09），
          其余页面先固化结构、路由与口径，交互与数据接入随后续迭代补齐。
        </p>
        <p>规划中的能力：{page.subtitle}。</p>
        <span className="req">{page.req}</span>
      </div>
    </>
  );
}
