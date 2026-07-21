"use client";

import { useEffect, useState } from "react";
import { useSession } from "next-auth/react";
import { useRouter } from "next/navigation";
import { SiteHeader } from "@/components/SiteHeader";

export default function FeedbackPage() {
  const { data: session, status } = useSession();
  const router = useRouter();
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (status === "unauthenticated") router.replace("/login");
  }, [status, router]);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError(null);
    setMessage(null);
    const res = await fetch("/api/feedback", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ subject, body }),
    });
    const data = await res.json();
    setLoading(false);
    if (!res.ok) {
      setError(data.error || "Failed to send");
      return;
    }
    setMessage("Thanks — your feedback was sent to the developer.");
    setSubject("");
    setBody("");
  }

  if (status === "loading" || !session?.user) {
    return (
      <>
        <SiteHeader />
        <main className="page">
          <p className="msg">Loading…</p>
        </main>
      </>
    );
  }

  return (
    <>
      <SiteHeader email={session.user.email} />
      <main className="page">
        <h1 className="page-title">Feedback</h1>
        <p className="page-sub">Send a report or idea directly to the Vader developer.</p>
        <form className="form" onSubmit={onSubmit}>
          <label>
            Subject
            <input
              required
              minLength={2}
              value={subject}
              onChange={(e) => setSubject(e.target.value)}
            />
          </label>
          <label>
            Message
            <textarea
              required
              minLength={5}
              value={body}
              onChange={(e) => setBody(e.target.value)}
            />
          </label>
          <button className="btn btn-primary" type="submit" disabled={loading}>
            {loading ? "Sending…" : "Send feedback"}
          </button>
          {error && <p className="msg msg-error">{error}</p>}
          {message && <p className="msg msg-ok">{message}</p>}
        </form>
      </main>
    </>
  );
}
