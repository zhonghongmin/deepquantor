/**
 * 路由键清单 —— 与 `pages.ts` 同源。
 *
 * D-21 结构断言要求：页数 = section 数 = 导航项数 = **路由键数**。
 * 路由键即 `app/api/<page>/route.ts`，故这里只声明路由目录名，
 * 实际 route.ts 由生成脚本批量产出，杜绝手抄 11 份造成数量漂移。
 */
import { ADMIN_PAGES } from "./pages";

/** 11 个 API 路由目录名（与管理端页面一一对应） */
export const API_ROUTES = ADMIN_PAGES.map((p) => p.id);

/** 11 个页面文件路径（app/admin/<id>/page.tsx） */
export const PAGE_ROUTES = ADMIN_PAGES.map((p) => p.id);
