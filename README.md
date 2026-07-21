# VADER

**Vader** is a beta skin for Rhino: collect ready-to-use Python scripts, browse them in a dark galaxy **web catalog**, and run them inside Rhino **only through the Vader connector** — without showing or copying source to end users.

Access is **invite / approve-only** (email + password).

## For your team (web-first)

| Who | What |
|-----|------|
| **You (admin)** | Deploy the web app → share one URL → approve users → add scripts in GitHub |
| **Team (browser)** | Register → sign in → browse catalog at your URL (no source shown) |
| **Team (Rhino)** | Rhino 8 + `plugin/vader_bootstrap.py` once per PC → Run scripts |

**Important:** Python Rhino scripts cannot run inside a browser. The **website** is the hub; **Rhino** on each machine is the runner.

→ **[Deploy for team](DEPLOY.md)** (Railway / Vercel + Postgres)  
→ **[/team](http://localhost:3000/team)** setup page after deploy

## Repo layout

```
scripts/          # Drop your Rhino Python scripts here (see scripts/README.md)
web/              # Next.js catalog, auth, admin, APIs
plugin/           # Rhino connector (vader_bootstrap.py + optional C# .rhp)
DEPLOY.md         # Team cloud deployment
```

## Local dev

```bash
cd web
cp .env.example .env
npm install
npx prisma migrate dev
npm run db:seed
npm run db:sync-scripts
npm run dev              # http://localhost:3000
```

Then in Rhino 8 Script Editor, run [`plugin/vader_bootstrap.py`](plugin/vader_bootstrap.py) with Server `http://localhost:3000`.

## Beta user flow

1. User opens your site → **Request beta access**
2. You approve at **/admin**
3. User browses **/catalog** on the web
4. User runs scripts in Rhino via the connector (see **/team**)

## Drop your scripts

```bash
cp -r scripts/_template scripts/modeling/my-tool
# edit script.py + manifest.json → push → redeploy or Admin Sync
```

See [scripts/README.md](scripts/README.md).

## Environment variables (`web/.env`)

Neon needs **two** URLs (Connection pooling ON = `DATABASE_URL`, OFF = `DIRECT_URL`):

| Variable | Purpose |
|----------|---------|
| `DATABASE_URL` | Neon **pooled** connection (app runtime) |
| `DIRECT_URL` | Neon **direct** connection (migrations) |
| `NEXTAUTH_URL` | Public site URL |
| `NEXT_PUBLIC_APP_URL` | Shown on /team for connector setup |
| `NEXTAUTH_SECRET` | Session secret |
| `ADMIN_EMAIL` | Admin / approver |
| `PLUGIN_API_KEY` | Shared with team for Rhino connector |
| `SCRIPTS_ROOT` | Path to `scripts/` (default `../scripts`) |

## Anti-copy (beta)

- Web catalog never returns source code
- Payload API requires plugin headers + one-time run token
- Connector executes in memory only

## Brand

Original geometric mark inspired by a mask silhouette (not a Star Wars copy). Assets: `web/public/brand/vader-mark.svg`.
