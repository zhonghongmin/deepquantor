import { NextResponse } from "next/server";

import { fetchOverview, toPayload } from "../../../app/admin/lib/data";

/** 投资建议（对内版） 数据接口（`#advice` · AD-08） */
export async function GET() {
  return NextResponse.json(toPayload(await fetchOverview()));
}
