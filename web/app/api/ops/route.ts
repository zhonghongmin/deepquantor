import { NextResponse } from "next/server";

import { fetchOverview, toPayload } from "../../../app/admin/lib/data";

/** 运营看板 数据接口（`#ops` · AD-06） */
export async function GET() {
  return NextResponse.json(toPayload(await fetchOverview()));
}
