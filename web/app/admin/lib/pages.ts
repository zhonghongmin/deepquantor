/**
 * 管理端页面清单 —— **唯一真值源**（D-25 / D-21）。
 *
 * 需求文档 §5.9.3 规定：页数 = section 数 = 导航项数 = 路由键数，四者同源。
 * 因此清单只在这里定义一次，侧栏导航、section 渲染、标题映射都从它派生，
 * 任何地方都不得另抄一份页面列表。
 *
 * 口径依据：《量化选股系统·需求文档》§5.9.3「页面清单与锚点」。
 */

export type PageId =
  | "overview"
  | "monitor"
  | "datamgmt"
  | "research"
  | "macro"
  | "micro"
  | "strategy"
  | "advice"
  | "ops"
  | "users"
  | "audit";

export interface PageDef {
  /** 路由锚点，同时是 <section id> 与 data-p 的值 */
  readonly id: PageId;
  /** 侧栏显示名 */
  readonly label: string;
  /** 侧栏分组 */
  readonly group: string;
  /** 导航图标 */
  readonly icon: string;
  /** 页头标题 */
  readonly title: string;
  /** 页头副标 */
  readonly subtitle: string;
  /** 关联需求条目 */
  readonly req: string;
}

export const ADMIN_PAGES: readonly PageDef[] = [
  {
    id: "overview",
    label: "概览 Dashboard",
    group: "总览",
    icon: "▦",
    title: "概览",
    subtitle: "一眼看数据下载是否正常：按宏观 / 中观 / 微观三层汇总各层采集健康度",
    req: "AD-09",
  },
  {
    id: "monitor",
    label: "运维监控",
    group: "数据与运维",
    icon: "◉",
    title: "运维监控",
    subtitle: "宏观采集数据项逐项展示期次、待补期数与状态",
    req: "AD-02",
  },
  {
    id: "datamgmt",
    label: "数据管理",
    group: "数据与运维",
    icon: "⚙",
    title: "数据管理",
    subtitle: "数据项与定时任务：增删改查、启停与执行历史",
    req: "AD-02、DL-05/06",
  },
  {
    id: "research",
    label: "投研与回测",
    group: "投研",
    icon: "📈",
    title: "投研与回测",
    subtitle: "信号、宏观因子与回测结论的只读查阅",
    req: "AD-04",
  },
  {
    id: "macro",
    label: "宏观数据",
    group: "投研",
    icon: "◎",
    title: "宏观数据",
    subtitle: "宏观数据项、资产配置与周期判定",
    req: "AD-10",
  },
  {
    id: "micro",
    label: "微观数据",
    group: "投研",
    icon: "⊞",
    title: "微观数据",
    subtitle: "六维因子与行业综合评分",
    req: "AD-12",
  },
  {
    id: "strategy",
    label: "策略与因子",
    group: "投研",
    icon: "Σ",
    title: "策略与因子",
    subtitle: "策略参数配置与因子挖掘入库",
    req: "AD-05、FA-07/08",
  },
  {
    id: "advice",
    label: "投资建议（对内）",
    group: "投研",
    icon: "❖",
    title: "投资建议（对内版）",
    subtitle: "含 reason 的投资建议树，仅内部可见",
    req: "AD-08",
  },
  {
    id: "ops",
    label: "运营看板",
    group: "运营与管理",
    icon: "📊",
    title: "运营看板",
    subtitle: "使用量、活跃度与转化情况",
    req: "AD-06",
  },
  {
    id: "users",
    label: "用户管理",
    group: "运营与管理",
    icon: "👤",
    title: "用户管理",
    subtitle: "内部账号的增删改查",
    req: "AD-01",
  },
  {
    id: "audit",
    label: "权限与审计",
    group: "运营与管理",
    icon: "🛡",
    title: "权限与审计",
    subtitle: "角色权限与操作留痕",
    req: "AD-07",
  },
] as const;

/** 侧栏分组顺序（与《管理端效果图.html》一致：总览 / 数据与运维 / 投研 / 运营与管理） */
export const NAV_GROUPS: readonly string[] = ["总览", "数据与运维", "投研", "运营与管理"] as const;

/** 按分组归拢后的导航项，供侧栏渲染 */
export function navItemsByGroup(): { group: string; items: PageDef[] }[] {
  return NAV_GROUPS.map((group) => ({
    group,
    items: ADMIN_PAGES.filter((p) => p.group === group),
  }));
}

/** 锚点 → 页面定义 */
export const PAGE_BY_ID: Readonly<Record<PageId, PageDef>> = Object.fromEntries(
  ADMIN_PAGES.map((p) => [p.id, p]),
) as Record<PageId, PageDef>;

/** 锚点 → 页头标题（与效果图 titles 同源） */
export const TITLES: Readonly<Record<PageId, string>> = Object.fromEntries(
  ADMIN_PAGES.map((p) => [p.id, p.title]),
) as Record<PageId, string>;
