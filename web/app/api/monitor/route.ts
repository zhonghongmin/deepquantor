import { NextResponse } from "next/server";

import { fetchOverview, toPayload } from "../../../app/admin/lib/data";

/** 运维监控 数据接口（`#monitor` · AD-02） */
export async function GET() {
  return NextResponse.json(toPayload(await fetchOverview()));
}
