import { NextResponse } from "next/server";

import { fetchOverview, toPayload } from "../../../app/admin/lib/data";

/** 概览 数据接口（`#overview` · AD-09） */
export async function GET() {
  return NextResponse.json(toPayload(await fetchOverview()));
}
