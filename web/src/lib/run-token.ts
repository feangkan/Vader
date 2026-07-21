import { randomBytes } from "crypto";
import { prisma } from "./prisma";

const TTL_MS = 60_000; // 60 seconds

export async function createRunToken(userId: string, scriptId: string) {
  const token = randomBytes(32).toString("hex");
  const expiresAt = new Date(Date.now() + TTL_MS);
  await prisma.runToken.create({
    data: { token, userId, scriptId, expiresAt },
  });
  return { token, expiresAt };
}

export async function consumeRunToken(token: string, scriptId: string) {
  const row = await prisma.runToken.findUnique({ where: { token } });
  if (!row) return { ok: false as const, error: "Invalid token" };
  if (row.scriptId !== scriptId) return { ok: false as const, error: "Token mismatch" };
  if (row.usedAt) return { ok: false as const, error: "Token already used" };
  if (row.expiresAt.getTime() < Date.now()) {
    return { ok: false as const, error: "Token expired" };
  }

  await prisma.runToken.update({
    where: { id: row.id },
    data: { usedAt: new Date() },
  });

  return { ok: true as const, userId: row.userId };
}

export function isPluginRequest(headers: Headers) {
  const apiKey = headers.get("x-vader-plugin-key");
  const ua = headers.get("user-agent") || "";
  const expected = process.env.PLUGIN_API_KEY || "";
  if (expected && apiKey === expected) return true;
  if (ua.toLowerCase().includes("vader-rhino-plugin")) return true;
  return false;
}
