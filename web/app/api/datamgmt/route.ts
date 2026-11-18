import { NextResponse } from "next/server";

import { fetchOverview, toPayload } from "../../../app/admin/lib/data";

/** 数据管理 数据接口（`#datamgmt` · AD-02、DL-05/06） */
export async function GET() {
  return NextResponse.json(toPayload(await fetchOverview()));
}
