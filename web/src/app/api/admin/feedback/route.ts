import { NextResponse } from "next/server";
import { prisma } from "@/lib/prisma";
import { requireAdmin } from "@/lib/session";

export async function GET() {
  const session = await requireAdmin();
  if (!session) {
    return NextResponse.json({ error: "Admin only" }, { status: 403 });
  }

  const feedback = await prisma.feedback.findMany({
    orderBy: { createdAt: "desc" },
    include: {
      user: { select: { email: true } },
    },
  });

  return NextResponse.json({
    feedback: feedback.map((f) => ({
      id: f.id,
      subject: f.subject,
      body: f.body,
      createdAt: f.createdAt,
      email: f.user.email,
    })),
  });
}
