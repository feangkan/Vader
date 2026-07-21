"use client";

import { useCallback, useEffect, useState } from "react";
import { useSession } from "next-auth/react";
import { useRouter } from "next/navigation";
import { SiteHeader } from "@/components/SiteHeader";

type UserRow = { id: string; email: string; status: string; createdAt: string };
type FeedbackRow = {
  id: string;
  subject: string;
  body: string;
  createdAt: string;
  email: string;
};

export default function AdminPage() {
  const { data: session, status } = useSession();
  const router = useRouter();
  const [users, setUsers] = useState<UserRow[]>([]);
  const [feedback, setFeedback] = useState<FeedbackRow[]>([]);
  const [syncMsg, setSyncMsg] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    const [uRes, fRes] = await Promise.all([
      fetch("/api/admin/users"),
      fetch("/api/admin/feedback"),
    ]);
    if (uRes.status === 403 || fRes.status === 403) {
      setError("Admin access required (ADMIN_EMAIL).");
      return;
    }
    if (!uRes.ok || !fRes.ok) {
      setError("Failed to load admin data.");
      return;
    }
    const uData = await uRes.json();
    const fData = await fRes.json();
    setUsers(uData.users || []);
    setFeedback(fData.feedback || []);
  }, []);

  useEffect(() => {
    if (status === "unauthenticated") router.replace("/login");
    if (status === "authenticated") load();
  }, [status, router, load]);

  async function setStatus(userId: string, next: string) {
    const res = await fetch("/api/admin/users", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ userId, status: next }),
    });
    if (res.ok) load();
  }

  async function syncScripts() {
    setSyncMsg(null);
    const res = await fetch("/api/scripts/sync", { method: "POST" });
    const data = await res.json();
    if (!res.ok) {
      setSyncMsg(data.error || "Sync failed");
      return;
    }
    setSyncMsg(`Synced ${data.synced} scripts (removed ${data.removed}).`);
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
      <SiteHeader email={session.user.email} isAdmin />
      <main className="page">
        <h1 className="page-title">Admin</h1>
        <p className="page-sub">Approve beta users, sync scripts, read feedback.</p>

        {error && <p className="msg msg-error">{error}</p>}

        <section className="category">
          <h2>Scripts</h2>
          <button className="btn btn-ghost btn-sm" type="button" onClick={syncScripts}>
            Sync from scripts/ folder
          </button>
          {syncMsg && <p className="msg msg-ok">{syncMsg}</p>}
        </section>

        <section className="category">
          <h2>Users</h2>
          <table className="table">
            <thead>
              <tr>
                <th>Email</th>
                <th>Status</th>
                <th>Joined</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {users.map((u) => (
                <tr key={u.id}>
                  <td>{u.email}</td>
                  <td>
                    <span className={`status status-${u.status}`}>{u.status}</span>
                  </td>
                  <td>{new Date(u.createdAt).toLocaleDateString()}</td>
                  <td>
                    <div className="actions">
                      {u.status !== "approved" && (
                        <button
                          className="btn btn-primary btn-sm"
                          type="button"
                          onClick={() => setStatus(u.id, "approved")}
                        >
                          Approve
                        </button>
                      )}
                      {u.status !== "rejected" && (
                        <button
                          className="btn btn-ghost btn-sm"
                          type="button"
                          onClick={() => setStatus(u.id, "rejected")}
                        >
                          Reject
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>

        <section className="category">
          <h2>Feedback</h2>
          {feedback.length === 0 ? (
            <p className="msg">No feedback yet.</p>
          ) : (
            feedback.map((f) => (
              <article key={f.id} className="feedback-item">
                <h3>{f.subject}</h3>
                <div className="feedback-meta">
                  {f.email} · {new Date(f.createdAt).toLocaleString()}
                </div>
                <p>{f.body}</p>
              </article>
            ))
          )}
        </section>
      </main>
    </>
  );
}
