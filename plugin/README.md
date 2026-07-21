# Vader Rhino Plugin

Two ways to try Vader inside Rhino 8.

## Quick try (recommended first) — Python bootstrap

No Visual Studio / .rhp build needed.

### 1. Start the web app on the same PC as Rhino

```bat
cd web
copy .env.example .env
npm install
npx prisma migrate dev
npm run db:seed
npm run dev
```

Open http://localhost:3000  
Sign in as seeded admin (`ADMIN_EMAIL` / `ADMIN_PASSWORD` from `.env`, defaults in root README)  
or register → approve yourself at `/admin`.

### 2. Open the bootstrap in Rhino

1. Rhino 8 → **ScriptEditor**
2. Open [`vader_bootstrap.py`](vader_bootstrap.py)
3. **Run**
4. In the VADER panel:
   - Server: `http://localhost:3000`
   - Plugin API key: same as `PLUGIN_API_KEY` in `web/.env` (default `vader-plugin-dev-key-change-me`)
   - Email / password of an **approved** account
   - **Sign in** → **Refresh** → pick a script → **Run selected**

Source is never shown in the panel. Scripts execute in memory.

> The API must be reachable from Rhino. `localhost` only works if the web app runs on that same machine. A cloud/dev-server URL will not reach your desktop Rhino unless you deploy the web app publicly.

---

## Full plugin (C# .rhp)

C# Rhino 8 panel that signs in to the Vader API, lists catalog metadata, and runs Python **in memory** without showing or saving source.

### Build (Windows + Rhino 8)

1. Install [.NET 7 SDK](https://dotnet.microsoft.com/download) and Rhino 8.
2. From the `Vader/` folder:

```bat
dotnet build -c Release -p:RhinoSystemDir="C:\Program Files\Rhino 8\System"
```

3. Copy `bin\Release\Vader.rhp` into your Rhino plugins folder, or drag the `.rhp` onto Rhino.
4. In Rhino, run command: `Vader`

### Configure

- **Server** — your Vader web URL (e.g. `http://localhost:3000`)
- **Plugin API key** — must match `PLUGIN_API_KEY` on the server
- Sign in with an **approved** beta email/password

### Flow

1. Login → `/api/plugin/login`
2. Refresh catalog → `/api/plugin/scripts` (metadata only)
3. Run → request run-token → fetch payload → execute in memory (no editor, no temp `.py`)
