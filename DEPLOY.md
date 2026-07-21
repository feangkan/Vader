# Deploy Vader for your team

Your team uses **one website URL** for login, catalog, and approvals.  
Scripts still **run inside Rhino 8** on each person's computer (they need Rhino + the small connector once).

## Architecture

```
Team browser  →  https://your-vader.app  (catalog, auth, admin)
Rhino on PC   →  vader_bootstrap.py      (Run — source never shown)
                      ↓
                 your-vader.app API      (protected payload)
Database      →  Neon Postgres (free tier OK)
```

---

## Recommended: Vercel + Neon (cheapest — $0)

You already have Neon. Use **two** connection strings from the Neon dashboard:

| Env var | Neon setting |
|---------|----------------|
| `DATABASE_URL` | **Connection pooling ON** (pooler host) |
| `DIRECT_URL` | **Connection pooling OFF** (direct host) — for migrations |

### 1. Vercel

1. [vercel.com](https://vercel.com) → **Add New Project** → import **feangkan/Vader**
2. **Root Directory:** leave empty (repo root) or set build per below
3. **Environment variables:**

| Variable | Value |
|----------|--------|
| `DATABASE_URL` | Neon pooled connection string |
| `DIRECT_URL` | Neon direct connection string |
| `NEXTAUTH_URL` | `https://YOUR-APP.vercel.app` (update after first deploy) |
| `NEXTAUTH_SECRET` | run `openssl rand -base64 32` |
| `NEXT_PUBLIC_APP_URL` | same as NEXTAUTH_URL |
| `ADMIN_EMAIL` | your email |
| `ADMIN_PASSWORD` | your admin password |
| `PLUGIN_API_KEY` | secret for Rhino connector (share with team) |
| `SCRIPTS_ROOT` | `../scripts` |

4. **Build & Output Settings** (override defaults):

- **Install Command:** `cd web && npm ci`
- **Build Command:**
  ```bash
  cd web && npx prisma generate && npx prisma migrate deploy && SCRIPTS_ROOT=../scripts node scripts/sync-scripts-to-db.mjs && npm run build
  ```
- **Output Directory:** `web/.next`
- **Framework Preset:** Next.js

5. Deploy

6. **Seed admin once** (on your PC):
   ```bash
   cd web
   cp .env.example .env
   # paste DATABASE_URL + DIRECT_URL + ADMIN_* from Vercel/Neon
   npm run db:seed
   ```

7. Open `https://YOUR-APP.vercel.app/admin` → approve team → share `/team`

---

## Alternative: Railway (full repo)

1. [railway.app](https://railway.app) → deploy from GitHub
2. Add Postgres **or** paste your Neon `DATABASE_URL` + `DIRECT_URL`
3. Build: `cd web && npm run build:deploy`
4. Start: `cd web && npm start`

---

## After deploy — team workflow

1. **You:** `/admin` → approve users
2. **Team:** register → browse `/catalog` on the web
3. **Team:** Rhino 8 → `plugin/vader_bootstrap.py` → Server = your Vercel URL
4. **Run** scripts in Rhino (source never shown in browser)

---

## Updating scripts

Push new folders under `scripts/` → redeploy (build syncs to DB) **or** Admin → Sync.

---

## Cost

| Service | Beta cost |
|---------|-----------|
| Neon Free | $0 |
| Vercel Hobby | $0 |
| Vader | $0 |
| Rhino 8 | per seat (McNeel) |

---

## What cannot run in the browser

Scripts use Rhino APIs. Web = hub; Rhino on each PC = runner.
