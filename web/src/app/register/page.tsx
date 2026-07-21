"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { SiteHeader } from "@/components/SiteHeader";

export default function RegisterPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError(null);
    setMessage(null);
    try {
      const res = await fetch("/api/auth/register", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, password }),
      });
      const data = await res.json();
      if (!res.ok) {
        setError(data.error || "Registration failed");
        return;
      }
      setMessage(data.message);
      if (data.user?.status === "approved") {
        setTimeout(() => router.push("/login"), 1200);
      }
    } catch {
      setError("Network error");
    } finally {
      setLoading(false);
    }
  }

  return (
    <>
      <SiteHeader />
      <main className="page">
        <h1 className="page-title">Request access</h1>
        <p className="page-sub">
          Beta is invite-only. Register with email and password — we&apos;ll approve your account.
        </p>
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
            Password (min 8)
            <input
              type="password"
              required
              minLength={8}
              autoComplete="new-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </label>
          <button className="btn btn-primary" type="submit" disabled={loading}>
            {loading ? "Submitting…" : "Register"}
          </button>
          {error && <p className="msg msg-error">{error}</p>}
          {message && <p className="msg msg-ok">{message}</p>}
          <p className="msg">
            Already approved? <Link href="/login">Sign in</Link>
          </p>
        </form>
      </main>
    </>
  );
}
