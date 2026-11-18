import { NextResponse } from "next/server";

import { fetchOverview, toPayload } from "../../../app/admin/lib/data";

/** 策略与因子 数据接口（`#strategy` · AD-05、FA-07/08） */
export async function GET() {
  return NextResponse.json(toPayload(await fetchOverview()));
}
