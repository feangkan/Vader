import { NextResponse } from "next/server";
import { prisma } from "@/lib/prisma";
import { requireAdmin } from "@/lib/session";

export async function GET() {
  const session = await requireAdmin();
  if (!session) {
    return NextResponse.json({ error: "Admin only" }, { status: 403 });
  }

  const users = await prisma.user.findMany({
    orderBy: { createdAt: "desc" },
    select: {
      id: true,
      email: true,
      status: true,
      createdAt: true,
    },
  });

  return NextResponse.json({ users });
}

export async function PATCH(req: Request) {
  const session = await requireAdmin();
  if (!session) {
    return NextResponse.json({ error: "Admin only" }, { status: 403 });
  }

  const body = await req.json();
  const { userId, status } = body as { userId?: string; status?: string };
  if (!userId || !["approved", "rejected", "pending"].includes(status || "")) {
    return NextResponse.json({ error: "Invalid request" }, { status: 400 });
  }

  const user = await prisma.user.update({
    where: { id: userId },
    data: { status: status! },
    select: { id: true, email: true, status: true },
  });

  return NextResponse.json({ user });
}
