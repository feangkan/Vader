# Deploy Vader for your team

Your team uses **one website URL** for login, catalog, and approvals.  
Scripts still **run inside Rhino 8** on each person's computer (they need Rhino + the small connector once).

## Architecture

```
Team browser  →  https://your-vader.app  (catalog, auth, admin)
Rhino on PC   →  vader_bootstrap.py      (Run — source never shown)
                      ↓
                 your-vader.app API      (protected payload)
```

---

## Recommended: Railway (full repo, easiest)

1. Push this repo to GitHub.
2. [railway.app](https://railway.app) → **New Project** → **Deploy from GitHub** → select `Vader`.
3. Add **PostgreSQL** plugin in the same project.
4. Set **Root Directory** / start settings:
   - **Build command:** `cd web && npm ci && npx prisma generate && npx prisma migrate deploy && SCRIPTS_ROOT=../scripts node scripts/sync-scripts-to-db.mjs && npm run build`
   - **Start command:** `cd web && npm start`
5. **Environment variables** (web service):

| Variable | Value |
|----------|--------|
| `DATABASE_URL` | `${{Postgres.DATABASE_URL}}` (Railway reference) |
| `NEXTAUTH_URL` | `https://your-app.up.railway.app` |
| `NEXTAUTH_SECRET` | long random string |
| `ADMIN_EMAIL` | your email |
| `ADMIN_PASSWORD` | strong password (for seed) |
| `PLUGIN_API_KEY` | shared secret for Rhino connector |
| `SCRIPTS_ROOT` | `../scripts` |
| `NEXT_PUBLIC_APP_URL` | same as NEXTAUTH_URL |

6. Deploy → run seed once (Railway shell or one-off):
   ```bash
   cd web && npm run db:seed
   ```
7. Share the URL with your team → **Team setup** page at `/team`.

---

## Alternative: Vercel + Neon Postgres

SQLite does **not** work on Vercel (serverless). Use [Neon](https://neon.tech) for Postgres.

1. Create Neon DB → copy `DATABASE_URL` (postgres://…).
2. Vercel → Import repo → set **Root Directory** to empty (repo root).
3. **Framework:** Next.js — override:
   - Install: `cd web && npm ci`
   - Build: `cd web && npx prisma generate && npx prisma migrate deploy && SCRIPTS_ROOT=../scripts node scripts/sync-scripts-to-db.mjs && npm run build`
   - Output: `web/.next` (may need `vercel.json` — see below)
4. Env vars: same table as Railway (`DATABASE_URL` = Neon URL).
5. After first deploy: run `npm run db:seed` locally against production `DATABASE_URL` once.

`vercel.json` at repo root (if needed):

```json
{
  "buildCommand": "cd web && npx prisma generate && npx prisma migrate deploy && SCRIPTS_ROOT=../scripts node scripts/sync-scripts-to-db.mjs && npm run build",
  "installCommand": "cd web && npm ci",
  "outputDirectory": "web/.next"
}
```

---

## After deploy — team workflow

1. **You:** open `/admin` → approve teammates.
2. **Team:** register → sign in → browse `/catalog`.
3. **Each member:** Rhino 8 → run `plugin/vader_bootstrap.py` once per machine.
   - Server: your deployed URL
   - API key: `PLUGIN_API_KEY` you set
   - Their approved email/password
4. **Run:** Refresh in panel → pick script → **Run selected**.

---

## Updating scripts

1. Add folders under `scripts/` in GitHub.
2. Redeploy (build runs sync), **or** Admin → **Sync from scripts/ folder** on a server with disk access.

---

## What cannot run in the browser

Your tools use `Rhino`, `Eto.Forms`, `rhinoscriptsyntax`, etc. They **require Rhino 8 installed**. The web app protects and delivers scripts; Rhino executes them. True “no Rhino” cloud execution would need **Rhino.Compute** (separate server + McNeel licensing) — out of scope for this beta.
