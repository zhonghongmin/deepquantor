import { NextResponse } from "next/server";

import { fetchOverview, toPayload } from "../../../app/admin/lib/data";

/** 权限与审计 数据接口（`#audit` · AD-07） */
export async function GET() {
  return NextResponse.json(toPayload(await fetchOverview()));
}
