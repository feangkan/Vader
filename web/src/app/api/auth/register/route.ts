import { NextResponse } from "next/server";
import bcrypt from "bcryptjs";
import { z } from "zod";
import { prisma } from "@/lib/prisma";

const schema = z.object({
  email: z.string().email(),
  password: z.string().min(8).max(128),
});

export async function POST(req: Request) {
  try {
    const body = await req.json();
    const parsed = schema.safeParse(body);
    if (!parsed.success) {
      return NextResponse.json(
        { error: "Valid email and password (min 8 characters) required." },
        { status: 400 }
      );
    }

    const email = parsed.data.email.toLowerCase().trim();
    const existing = await prisma.user.findUnique({ where: { email } });
    if (existing) {
      return NextResponse.json({ error: "Email already registered." }, { status: 409 });
    }

    const passwordHash = await bcrypt.hash(parsed.data.password, 12);
    const adminEmail = (process.env.ADMIN_EMAIL || "").toLowerCase();
    const autoApprove = adminEmail && email === adminEmail;

    const user = await prisma.user.create({
      data: {
        email,
        passwordHash,
        status: autoApprove ? "approved" : "pending",
      },
      select: { id: true, email: true, status: true },
    });

    return NextResponse.json({
      user,
      message: autoApprove
        ? "Admin account created. You can sign in."
        : "Registration received. Wait for beta approval before signing in.",
    });
  } catch {
    return NextResponse.json({ error: "Registration failed." }, { status: 500 });
  }
}
