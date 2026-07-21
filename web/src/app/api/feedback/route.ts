import { NextResponse } from "next/server";
import { z } from "zod";
import { prisma } from "@/lib/prisma";
import { requireSession } from "@/lib/session";

const schema = z.object({
  subject: z.string().min(2).max(200),
  body: z.string().min(5).max(5000),
});

export async function POST(req: Request) {
  const session = await requireSession();
  if (!session) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  const parsed = schema.safeParse(await req.json());
  if (!parsed.success) {
    return NextResponse.json({ error: "Invalid feedback." }, { status: 400 });
  }

  const feedback = await prisma.feedback.create({
    data: {
      userId: session.user.id,
      subject: parsed.data.subject.trim(),
      body: parsed.data.body.trim(),
    },
  });

  return NextResponse.json({ ok: true, id: feedback.id });
}

export async function GET() {
  const session = await requireSession();
  if (!session) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  // Users only see their own; admin uses /api/admin/feedback
  const items = await prisma.feedback.findMany({
    where: { userId: session.user.id },
    orderBy: { createdAt: "desc" },
    take: 20,
  });

  return NextResponse.json({ feedback: items });
}
