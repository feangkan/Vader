import { NextResponse } from "next/server";
import { prisma } from "@/lib/prisma";
import { requireSession } from "@/lib/session";
import { createRunToken } from "@/lib/run-token";

type Ctx = { params: Promise<{ id: string }> };

export async function POST(_req: Request, ctx: Ctx) {
  const session = await requireSession();
  if (!session) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  const { id } = await ctx.params;
  const script = await prisma.script.findUnique({ where: { id } });
  if (!script) {
    return NextResponse.json({ error: "Script not found" }, { status: 404 });
  }

  const { token, expiresAt } = await createRunToken(session.user.id, id);
  return NextResponse.json({
    token,
    expiresAt: expiresAt.toISOString(),
    scriptId: id,
  });
}
