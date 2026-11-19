import { NextResponse } from "next/server";
import { checkRefs } from "@/services/datamgmt";

export const dynamic = "force-dynamic";

/** DL-07 分支 A：删除前先查引用（按编码判定），被引用即拒绝并返回占用方清单。 */
export async function GET(req: Request) {
  try {
    const dataId = new URL(req.url).searchParams.get("id") ?? "";
    const r = await checkRefs(dataId);
    if (!r.available) {
      return NextResponse.json({ code: 1, message: r.reason ?? "数据库不可用", data: null });
    }
    return NextResponse.json({ code: 0, message: "ok", data: { refs: r.refs } });
  } catch (e) {
    return NextResponse.json({
      code: 1,
      message: e instanceof Error ? e.message : String(e),
      data: null,
    });
  }
}
