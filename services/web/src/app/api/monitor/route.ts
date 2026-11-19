import { NextResponse } from "next/server";
import { getMonitor } from "@/services/monitor";

export const dynamic = "force-dynamic";

export async function GET() {
  try {
    const data = await getMonitor();
    return NextResponse.json({ code: 0, message: "ok", data });
  } catch (e) {
    return NextResponse.json({
      code: 1,
      message: e instanceof Error ? e.message : String(e),
      data: null,
    });
  }
}
