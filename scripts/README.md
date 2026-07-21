# Vader Scripts Library

Drop ready-to-use Rhino Python scripts here. The web app syncs this folder into the catalog (metadata only). End users never see or download source — they run scripts only through the Vader Rhino plugin.

## How to add a script

1. Copy `_template/` into a category folder:

```bash
cp -r scripts/_template scripts/geometry/my-script-name
```

2. Edit `script.py` with your Rhino Python code (`#! python 3` recommended for Rhino 8).

3. Fill in `manifest.json`:

| Field | Description |
|-------|-------------|
| `id` | Unique slug (must match folder name, e.g. `my-script-name`) |
| `name` | Display name in the catalog |
| `description` | Short one-line summary |
| `category` | Folder category: `geometry`, `utilities`, `modeling`, `annotation`, or your own |
| `tags` | Array of search tags |
| `rhinoVersion` | e.g. `"8"` |
| `version` | Script version string, e.g. `"1.0.0"` |

4. Commit and push. On the server (or locally), run sync from the admin UI or `POST /api/scripts/sync`.

## Folder layout

```
scripts/
  _template/          # copy this for new scripts
  climate/
  geometry/
  modeling/
  simulation/
  utilities/
  annotation/
  <your-category>/
    <script-id>/
      script.py
      manifest.json
```

Do **not** drop loose `.py` files at the `scripts/` root — put each script in its own folder with a `manifest.json` (or copy `_template/`).

## Rules

- One script per folder.
- Folder name must equal `manifest.id`.
- Do not put secrets in scripts.
- Source stays in this repo / on the server — the catalog API never returns `script.py` to browsers.
