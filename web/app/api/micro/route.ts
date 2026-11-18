import { NextResponse } from "next/server";

import { fetchOverview, toPayload } from "../../../app/admin/lib/data";

/** 微观数据 数据接口（`#micro` · AD-12） */
export async function GET() {
  return NextResponse.json(toPayload(await fetchOverview()));
}
