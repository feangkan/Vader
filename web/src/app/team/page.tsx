import Link from "next/link";
import { getServerSession } from "next-auth";
import { authOptions } from "@/lib/auth";
import { SiteHeader } from "@/components/SiteHeader";

const APP_URL = process.env.NEXT_PUBLIC_APP_URL || process.env.NEXTAUTH_URL || "https://your-vader-site.com";

export default async function TeamPage() {
  const session = await getServerSession(authOptions);

  return (
    <>
      <SiteHeader email={session?.user?.email} />
      <main className="page team-page">
        <h1 className="page-title">Team setup</h1>
        <p className="page-sub">
          Vader runs as a <strong>web hub + Rhino runner</strong>. Your team uses the website for
          login and the script catalog. Each member runs scripts inside Rhino 8 on their own computer
          — Python cannot execute in a browser alone.
        </p>

        <section className="team-section">
          <h2>How it works</h2>
          <ol className="team-steps">
            <li>
              <strong>You deploy this web app</strong> (see{" "}
              <Link href="https://github.com/feangkan/Vader/blob/main/DEPLOY.md">DEPLOY.md</Link>).
              Team visits one URL, e.g.{" "}
              <code>{APP_URL}</code>
            </li>
            <li>
              <strong>Team registers</strong> → you approve at <Link href="/admin">/admin</Link>
            </li>
            <li>
              <strong>Each member installs Rhino 8</strong> and opens the Vader connector once (see
              below)
            </li>
            <li>
              <strong>Browse on web</strong> → <strong>Run in Rhino</strong> via the connector.
              Source never appears in the browser.
            </li>
          </ol>
        </section>

        <section className="team-section">
          <h2>Rhino connector (one-time per machine)</h2>
          <p className="msg">
            Download or copy{" "}
            <a
              href="https://raw.githubusercontent.com/feangkan/Vader/main/plugin/vader_bootstrap.py"
              target="_blank"
              rel="noopener noreferrer"
            >
              vader_bootstrap.py
            </a>{" "}
            from the repo. In Rhino 8: <strong>ScriptEditor → Open → Run</strong>.
          </p>
          <div className="team-config">
            <div>
              <span className="team-label">Server URL</span>
              <code>{APP_URL}</code>
            </div>
            <div>
              <span className="team-label">Plugin API key</span>
              <code>Ask your admin (PLUGIN_API_KEY on server)</code>
            </div>
            <div>
              <span className="team-label">Login</span>
              <span>Same email + password as the website (must be approved)</span>
            </div>
          </div>
        </section>

        <section className="team-section">
          <h2>For admins</h2>
          <ul className="team-list">
            <li>Add scripts under <code>scripts/&lt;category&gt;/&lt;id&gt;/</code> in GitHub</li>
            <li>Redeploy or click <strong>Sync</strong> in <Link href="/admin">Admin</Link></li>
            <li>Share the site URL + API key with your team securely</li>
          </ul>
        </section>

        <div className="hero-ctas">
          <Link href="/register" className="btn btn-primary">
            Request access
          </Link>
          <Link href="/catalog" className="btn btn-ghost">
            Open catalog
          </Link>
        </div>
      </main>
    </>
  );
}
