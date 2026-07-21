import { NextResponse } from "next/server";
import { prisma } from "@/lib/prisma";
import { consumeRunToken, isPluginRequest } from "@/lib/run-token";
import { getScriptSource } from "@/lib/script-source";

type Ctx = { params: Promise<{ id: string }> };

/**
 * Plugin-only payload endpoint.
 * Requires: valid one-time run token + plugin identity header.
 * Never expose this response in the web UI.
 */
export async function GET(req: Request, ctx: Ctx) {
  if (!isPluginRequest(req.headers)) {
    return NextResponse.json(
      { error: "Payload available only via Vader Rhino plugin." },
      { status: 403 }
    );
  }

  const { id } = await ctx.params;
  const url = new URL(req.url);
  const token = url.searchParams.get("token") || req.headers.get("x-vader-run-token");
  if (!token) {
    return NextResponse.json({ error: "Missing run token" }, { status: 401 });
  }

  const consumed = await consumeRunToken(token, id);
  if (!consumed.ok) {
    return NextResponse.json({ error: consumed.error }, { status: 401 });
  }

  const script = await prisma.script.findUnique({ where: { id } });
  if (!script) {
    return NextResponse.json({ error: "Script not found" }, { status: 404 });
  }

  const source = await getScriptSource(script.id, script.relativePath);
  if (source == null) {
    return NextResponse.json({ error: "Script file missing on server" }, { status: 404 });
  }

  return NextResponse.json({
    id: script.id,
    version: script.version,
    // source delivered only to authenticated plugin for in-memory execution
    source,
  });
}
