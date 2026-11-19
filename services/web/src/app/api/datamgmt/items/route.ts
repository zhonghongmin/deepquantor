import { NextResponse } from "next/server";
import { getDataMgmt, deleteDataItem } from "@/services/datamgmt";
import { getPool } from "@/services/db";

export const dynamic = "force-dynamic";

export async function GET() {
  try {
    const data = await getDataMgmt();
    return NextResponse.json({ code: 0, message: "ok", data });
  } catch (e) {
    return NextResponse.json({
      code: 1,
      message: e instanceof Error ? e.message : String(e),
      data: null,
    });
  }
}

/** 新增/编辑数据项（名称全库唯一、因子层级必填；编码系统生成不可改）。 */
export async function POST(req: Request) {
  try {
    const db = getPool();
    if (!db) {
      return NextResponse.json({ code: 1, message: "数据库不可用", data: null });
    }
    const b = (await req.json()) as Record<string, string>;
    if (!b.name) return NextResponse.json({ code: 1, message: "数据项名不能为空", data: null });
    if (!b.factor_layer)
      return NextResponse.json({ code: 1, message: "因子层级必填，不落库", data: null });
    const id =
      b.id ||
      `DI-${b.factor_layer?.toUpperCase()}-${Date.now().toString(36).toUpperCase()}`; // 编码系统生成
    await db.query(
      `INSERT INTO task.data_item (id, name, freq, factor_layer, api, publish_slot, job_code)
       VALUES ($1,$2,$3,$4,$5,$6,$7)
       ON CONFLICT (id) DO UPDATE SET name=$2, freq=$3, factor_layer=$4, api=$5,
         publish_slot=$6, job_code=$7, updated_at=now()`,
      [id, b.name, b.freq || "monthly", b.factor_layer, b.api || null, b.publish_slot || null, b.job_code || null],
    );
    return NextResponse.json({ code: 0, message: "ok", data: { id } });
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e);
    return NextResponse.json({ code: 1, message: msg.includes("unique") ? "数据项名重复，阻止保存" : msg, data: null });
  }
}

/** 删除数据项：DL-07 引用检查 → DL-08 三处同事务清除。 */
export async function DELETE(req: Request) {
  try {
    const { id } = (await req.json()) as { id: string };
    const r = await deleteDataItem(id);
    return NextResponse.json({ code: r.ok ? 0 : 1, message: r.message, data: null });
  } catch (e) {
    return NextResponse.json({
      code: 1,
      message: e instanceof Error ? e.message : String(e),
      data: null,
    });
  }
}
