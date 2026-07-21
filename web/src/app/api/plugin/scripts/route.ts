import { NextResponse } from "next/server";
import { prisma } from "@/lib/prisma";
import { isPluginRequest } from "@/lib/run-token";
import { parseTags } from "@/lib/sync";

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

export async function GET(req: Request) {
  const user = await resolvePluginUser(req);
  if (!user) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  const scripts = await prisma.script.findMany({
    where: { id: { not: "__session__" } },
    orderBy: [{ category: "asc" }, { name: "asc" }],
  });

  return NextResponse.json({
    scripts: scripts.map((s) => ({
      id: s.id,
      name: s.name,
      description: s.description,
      category: s.category,
      tags: parseTags(s.tags),
      rhinoVersion: s.rhinoVersion,
      version: s.version,
    })),
  });
}
