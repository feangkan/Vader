# Vader Rhino Plugin

C# Rhino 8 panel that signs in to the Vader API, lists catalog metadata, and runs Python **in memory** without showing or saving source.

## Build (Windows + Rhino 8)

1. Install [.NET 7 SDK](https://dotnet.microsoft.com/download) and Rhino 8.
2. From this folder:

```bat
dotnet build -c Release -p:RhinoSystemDir="C:\Program Files\Rhino 8\System"
```

3. Copy `bin\Release\Vader.rhp` (and `Vader.dll` if separate) into your Rhino plugins folder, or drag the `.rhp` onto Rhino.
4. In Rhino, run command: `Vader`

## Configure

In the panel:

- **Server** — your Vader web URL (e.g. `http://localhost:3000`)
- **Plugin API key** — must match `PLUGIN_API_KEY` on the server
- Sign in with an **approved** beta email/password

## Flow

1. Login → `/api/plugin/login`
2. Refresh catalog → `/api/plugin/scripts` (metadata only)
3. Run → request run-token → fetch payload → `ScriptRunner.RunInMemory` (no editor, no temp `.py`)
