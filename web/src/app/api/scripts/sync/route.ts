import { NextResponse } from "next/server";
import { requireAdmin } from "@/lib/session";
import { syncScriptsFromDisk } from "@/lib/sync";

export async function POST() {
  const session = await requireAdmin();
  if (!session) {
    return NextResponse.json({ error: "Admin only" }, { status: 403 });
  }

  try {
    const result = await syncScriptsFromDisk();
    return NextResponse.json({ ok: true, ...result });
  } catch (e) {
    const message = e instanceof Error ? e.message : "Sync failed";
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
