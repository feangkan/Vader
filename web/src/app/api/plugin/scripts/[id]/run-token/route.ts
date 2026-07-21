import { NextResponse } from "next/server";
import { prisma } from "@/lib/prisma";
import { createRunToken, isPluginRequest } from "@/lib/run-token";

type Ctx = { params: Promise<{ id: string }> };

async function resolvePluginUser(req: Request) {
  if (!isPluginRequest(req.headers)) return null;
  const token =
    req.headers.get("x-vader-session") ||
    req.headers.get("authorization")?.replace(/^Bearer\s+/i, "");
  if (!token) return null;

  const row = await prisma.runToken.findUnique({ where: { token } });
  if (!row || row.scriptId !== "__session__") return null;
  if (row.expiresAt.getTime() < Date.now()) return null;

  const user = await prisma.user.findUnique({ where: { id: row.userId } });
  if (!user || user.status !== "approved") return null;
  return user;
}

export async function POST(req: Request, ctx: Ctx) {
  const user = await resolvePluginUser(req);
  if (!user) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  const { id } = await ctx.params;
  if (id === "__session__") {
    return NextResponse.json({ error: "Invalid script" }, { status: 400 });
  }

  const script = await prisma.script.findUnique({ where: { id } });
  if (!script) {
    return NextResponse.json({ error: "Script not found" }, { status: 404 });
  }

  const { token, expiresAt } = await createRunToken(user.id, id);
  return NextResponse.json({
    token,
    expiresAt: expiresAt.toISOString(),
    scriptId: id,
  });
}
