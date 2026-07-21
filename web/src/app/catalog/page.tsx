import { redirect } from "next/navigation";
import { getServerSession } from "next-auth";
import { authOptions } from "@/lib/auth";
import { prisma } from "@/lib/prisma";
import { isAdminEmail } from "@/lib/session";
import { parseTags, syncScriptsFromDisk } from "@/lib/sync";
import { SiteHeader } from "@/components/SiteHeader";

export default async function CatalogPage() {
  const session = await getServerSession(authOptions);
  if (!session?.user?.id || session.user.status !== "approved") {
    redirect("/login");
  }

  // Auto-sync on catalog load so dropped scripts appear without manual step
  try {
    await syncScriptsFromDisk();
  } catch {
    // ignore sync errors on page load
  }

  const scripts = await prisma.script.findMany({
    where: { id: { not: "__session__" } },
    orderBy: [{ category: "asc" }, { name: "asc" }],
  });

  const byCategory = scripts.reduce<Record<string, typeof scripts>>((acc, s) => {
    (acc[s.category] ||= []).push(s);
    return acc;
  }, {});

  return (
    <>
      <SiteHeader email={session.user.email} isAdmin={isAdminEmail(session.user.email)} />
      <main className="page">
        <h1 className="page-title">Catalog</h1>
        <p className="page-sub">
          Browse scripts by category. Source is never shown here — run them in Rhino with the Vader
          plugin.
        </p>

        {scripts.length === 0 ? (
          <p className="msg">No scripts synced yet. Drop folders under <code>scripts/</code> and refresh.</p>
        ) : (
          Object.entries(byCategory).map(([category, items]) => (
            <section key={category} className="category">
              <h2>{category}</h2>
              <div className="script-list">
                {items.map((s) => (
                  <article key={s.id} className="script-row">
                    <div>
                      <h3>{s.name}</h3>
                      <p>{s.description}</p>
                      <div className="tags">
                        {parseTags(s.tags).map((t) => (
                          <span key={t} className="tag">
                            {t}
                          </span>
                        ))}
                      </div>
                      <p className="hint">Open Vader in Rhino → select → Run</p>
                    </div>
                    <div className="script-meta">
                      <div>v{s.version}</div>
                      <div>Rhino {s.rhinoVersion}</div>
                    </div>
                  </article>
                ))}
              </div>
            </section>
          ))
        )}
      </main>
    </>
  );
}
