import { NextResponse } from "next/server";
import { getOverview } from "@/services/overview";

export const dynamic = "force-dynamic";

export async function GET() {
  try {
    const data = await getOverview();
    return NextResponse.json({ code: 0, message: "ok", data });
  } catch (e) {
    return NextResponse.json({
      code: 1,
      message: e instanceof Error ? e.message : String(e),
      data: null,
    });
  }
}
