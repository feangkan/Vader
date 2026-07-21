import type { NextAuthOptions } from "next-auth";
import CredentialsProvider from "next-auth/providers/credentials";
import bcrypt from "bcryptjs";
import { prisma } from "./prisma";

declare module "next-auth" {
  interface User {
    status?: string;
  }
  interface Session {
    user: {
      id: string;
      email: string;
      status: string;
    };
  }
}

declare module "next-auth/jwt" {
  interface JWT {
    id?: string;
    status?: string;
  }
}

export const authOptions: NextAuthOptions = {
  session: { strategy: "jwt" },
  pages: {
    signIn: "/login",
  },
  providers: [
    CredentialsProvider({
      name: "Email",
      credentials: {
        email: { label: "Email", type: "email" },
        password: { label: "Password", type: "password" },
      },
      async authorize(credentials) {
        if (!credentials?.email || !credentials?.password) return null;

        const user = await prisma.user.findUnique({
          where: { email: credentials.email.toLowerCase().trim() },
        });
        if (!user) return null;

        const ok = await bcrypt.compare(credentials.password, user.passwordHash);
        if (!ok) return null;

        if (user.status !== "approved") {
          throw new Error(
            user.status === "pending"
              ? "Your account is pending approval."
              : "Your account has been rejected."
          );
        }

        return {
          id: user.id,
          email: user.email,
          status: user.status,
        };
      },
    }),
  ],
  callbacks: {
    async jwt({ token, user }) {
      if (user) {
        token.id = user.id;
        token.status = user.status;
      } else if (token.id) {
        const fresh = await prisma.user.findUnique({
          where: { id: token.id as string },
          select: { status: true, email: true },
        });
        if (fresh) {
          token.status = fresh.status;
          token.email = fresh.email;
        }
      }
      return token;
    },
    async session({ session, token }) {
      if (token.id && token.email) {
        session.user = {
          id: token.id as string,
          email: token.email as string,
          status: (token.status as string) || "pending",
        };
      }
      return session;
    },
  },
  secret: process.env.NEXTAUTH_SECRET,
};
