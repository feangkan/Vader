"use client";

import { useState } from "react";
import Link from "next/link";
import { signIn } from "next-auth/react";
import { useRouter } from "next/navigation";
import { SiteHeader } from "@/components/SiteHeader";

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError(null);
    const res = await signIn("credentials", {
      email,
      password,
      redirect: false,
    });
    setLoading(false);
    if (res?.error) {
      setError(
        res.error === "CredentialsSignin"
          ? "Invalid credentials or account not approved."
          : res.error
      );
      return;
    }
    router.push("/catalog");
    router.refresh();
  }

  return (
    <>
      <SiteHeader />
      <main className="page">
        <h1 className="page-title">Sign in</h1>
        <p className="page-sub">Approved beta accounts only.</p>
        <form className="form" onSubmit={onSubmit}>
          <label>
            Email
            <input
              type="email"
              required
              autoComplete="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
          </label>
          <label>
            Password
            <input
              type="password"
              required
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </label>
          <button className="btn btn-primary" type="submit" disabled={loading}>
            {loading ? "Signing in…" : "Sign in"}
          </button>
          {error && <p className="msg msg-error">{error}</p>}
          <p className="msg">
            Need access? <Link href="/register">Request beta</Link>
          </p>
        </form>
      </main>
    </>
  );
}
