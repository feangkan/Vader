import { getServerSession } from "next-auth";
import { authOptions } from "./auth";
import { prisma } from "./prisma";

export async function requireSession() {
  const session = await getServerSession(authOptions);
  if (!session?.user?.id) return null;
  if (session.user.status !== "approved") return null;
  return session;
}

export async function requireAdmin() {
  const session = await requireSession();
  if (!session) return null;
  const adminEmail = (process.env.ADMIN_EMAIL || "").toLowerCase();
  if (!adminEmail || session.user.email.toLowerCase() !== adminEmail) return null;
  return session;
}

export async function getUserById(id: string) {
  return prisma.user.findUnique({ where: { id } });
}

export function isAdminEmail(email: string) {
  const adminEmail = (process.env.ADMIN_EMAIL || "").toLowerCase();
  return !!adminEmail && email.toLowerCase() === adminEmail;
}
