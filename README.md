# VADER

**Vader** is a beta skin for Rhino: collect ready-to-use Python scripts, browse them in a dark galaxy web catalog, and run them inside Rhino **only through the Vader plugin** — without showing or copying source to end users.

Access is **invite / approve-only** (email + password). No paid billing in this beta.

## Repo layout

```
scripts/          # Drop your Rhino Python scripts here (see scripts/README.md)
web/              # Next.js catalog, auth, admin, APIs
plugin/Vader/     # Rhino 8 C# panel plugin
```

## Quick start (web)

```bash
cd web
cp .env.example .env
# edit ADMIN_EMAIL, NEXTAUTH_SECRET, PLUGIN_API_KEY
npm install
npx prisma migrate dev
npm run db:seed          # creates approved admin from ADMIN_EMAIL
npm run dev              # http://localhost:3000
```

Default seed admin (override with env):

- Email: `ADMIN_EMAIL` (default `admin@vader.app`)
- Password: `ADMIN_PASSWORD` (default `vader-admin-change-me`) — **change this**

### Beta user flow

1. User opens the site → **Request beta access** (register)
2. You open **/admin** (as `ADMIN_EMAIL`) → **Approve**
3. User signs in → browses **/catalog** (metadata only, no source)
4. User sends ideas via **/feedback**
5. User installs the Rhino plugin → signs in → **Run** scripts in Rhino

### Drop your scripts

```bash
cp -r scripts/_template scripts/geometry/my-cool-tool
# edit scripts/geometry/my-cool-tool/script.py
# edit scripts/geometry/my-cool-tool/manifest.json
```

Catalog auto-syncs from `scripts/` when an approved user opens `/catalog`, or click **Sync** in Admin.

See [scripts/README.md](scripts/README.md).

## Try it in Rhino (same PC)

The Vader API must run on the **same machine** as Rhino (or be publicly deployed). Cloud `localhost` is not reachable from your desktop.

```bash
cd web
cp .env.example .env   # Windows: copy .env.example .env
npm install
npx prisma migrate dev
npm run db:seed
npm run dev
```

Then in Rhino 8 Script Editor, open and run:

[`plugin/vader_bootstrap.py`](plugin/vader_bootstrap.py)

Sign in with an approved account → Refresh → select a script → **Run selected**.

Full C# `.rhp` build steps: [plugin/README.md](plugin/README.md).


## Environment variables (`web/.env`)

| Variable | Purpose |
|----------|---------|
| `DATABASE_URL` | SQLite path (`file:./dev.db`) |
| `NEXTAUTH_URL` | Public site URL |
| `NEXTAUTH_SECRET` | Session secret |
| `ADMIN_EMAIL` | Approver / admin inbox identity |
| `PLUGIN_API_KEY` | Shared secret for Rhino plugin |
| `SCRIPTS_ROOT` | Path to `scripts/` (default `../scripts`) |

## Anti-copy (beta)

- Web catalog never returns `script.py`
- Payload endpoint requires plugin headers + one-time run token
- Plugin executes source in memory and does not show an editor

This deters casual copying; it is not perfect DRM against a determined reverse engineer.

## Brand

Original geometric mark inspired by a mask silhouette (not a Star Wars / Darth Vader copy). Assets: `web/public/brand/vader-mark.svg`.
