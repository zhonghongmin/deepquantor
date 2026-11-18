import { NextResponse } from "next/server";

import { fetchOverview, toPayload } from "../../../app/admin/lib/data";

/** 宏观数据 数据接口（`#macro` · AD-10） */
export async function GET() {
  return NextResponse.json(toPayload(await fetchOverview()));
}
