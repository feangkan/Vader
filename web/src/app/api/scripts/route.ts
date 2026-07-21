import { NextResponse } from "next/server";
import { prisma } from "@/lib/prisma";
import { requireSession } from "@/lib/session";
import { parseTags } from "@/lib/sync";

export async function GET() {
  const session = await requireSession();
  if (!session) {
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
      // intentionally no source / path for clients
    })),
  });
}
