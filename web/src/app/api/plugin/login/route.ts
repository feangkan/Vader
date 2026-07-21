import { NextResponse } from "next/server";
import bcrypt from "bcryptjs";
import { prisma } from "@/lib/prisma";
import { isPluginRequest } from "@/lib/run-token";

/**
 * Plugin login — returns a short-lived session-style token stored as RunToken-like JWT substitute.
 * For beta: issues a plugin access token (user id + email) as a signed-ish opaque token in DB via User lookup.
 */
export async function POST(req: Request) {
  if (!isPluginRequest(req.headers)) {
    return NextResponse.json({ error: "Plugin only" }, { status: 403 });
  }

  const body = await req.json();
  const email = String(body.email || "")
    .toLowerCase()
    .trim();
  const password = String(body.password || "");

  if (!email || !password) {
    return NextResponse.json({ error: "Email and password required" }, { status: 400 });
  }

  const user = await prisma.user.findUnique({ where: { email } });
  if (!user) {
    return NextResponse.json({ error: "Invalid credentials" }, { status: 401 });
  }

  const ok = await bcrypt.compare(password, user.passwordHash);
  if (!ok) {
    return NextResponse.json({ error: "Invalid credentials" }, { status: 401 });
  }

  if (user.status !== "approved") {
    return NextResponse.json(
      { error: user.status === "pending" ? "Pending approval" : "Account rejected" },
      { status: 403 }
    );
  }

  // Reuse RunToken table with scriptId = "__session__" for plugin session (beta)
  const { randomBytes } = await import("crypto");
  const token = randomBytes(32).toString("hex");
  const expiresAt = new Date(Date.now() + 7 * 24 * 60 * 60 * 1000);

  // Ensure a dummy script exists for session tokens, or use Feedback-free approach:
  // Store plugin session as a special RunToken against a sentinel script.
  await prisma.script.upsert({
    where: { id: "__session__" },
    create: {
      id: "__session__",
      name: "Session",
      description: "Internal",
      category: "_system",
      tags: "[]",
      relativePath: "_system",
    },
    update: {},
  });

  await prisma.runToken.create({
    data: {
      token,
      userId: user.id,
      scriptId: "__session__",
      expiresAt,
    },
  });

  return NextResponse.json({
    token,
    expiresAt: expiresAt.toISOString(),
    email: user.email,
    userId: user.id,
  });
}
