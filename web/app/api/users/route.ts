import { NextResponse } from "next/server";

import { fetchOverview, toPayload } from "../../../app/admin/lib/data";

/** 用户管理 数据接口（`#users` · AD-01） */
export async function GET() {
  return NextResponse.json(toPayload(await fetchOverview()));
}
