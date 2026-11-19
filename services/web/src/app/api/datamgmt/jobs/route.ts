import { NextResponse } from "next/server";
import { getDataMgmt } from "@/services/datamgmt";

export const dynamic = "force-dynamic";

export async function GET() {
  try {
    const data = await getDataMgmt();
    return NextResponse.json({ code: 0, message: "ok", data: { jobs: data.jobs } });
  } catch (e) {
    return NextResponse.json({
      code: 1,
      message: e instanceof Error ? e.message : String(e),
      data: null,
    });
  }
}
