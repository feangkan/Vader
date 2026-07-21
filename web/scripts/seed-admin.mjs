import { PrismaClient } from "@prisma/client";
import bcrypt from "bcryptjs";

const prisma = new PrismaClient();

async function main() {
  const email = (process.env.ADMIN_EMAIL || "admin@vader.app").toLowerCase();
  const password = process.env.ADMIN_PASSWORD || "vader-admin-change-me";
  const hash = await bcrypt.hash(password, 12);
  const user = await prisma.user.upsert({
    where: { email },
    create: { email, passwordHash: hash, status: "approved" },
    update: { passwordHash: hash, status: "approved" },
  });
  console.log("Admin ready:", user.email, "(password from ADMIN_PASSWORD or default)");
}

main()
  .catch((e) => {
    console.error(e);
    process.exit(1);
  })
  .finally(() => prisma.$disconnect());
