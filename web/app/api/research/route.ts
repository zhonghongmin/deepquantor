import { NextResponse } from "next/server";

import { fetchOverview, toPayload } from "../../../app/admin/lib/data";

/** 投研与回测 数据接口（`#research` · AD-04） */
export async function GET() {
  return NextResponse.json(toPayload(await fetchOverview()));
}
