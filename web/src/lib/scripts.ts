import path from "path";
import fs from "fs";

/** Absolute path to the monorepo scripts/ folder. */
export function getScriptsRoot(): string {
  const configured = process.env.SCRIPTS_ROOT || "../scripts";
  return path.resolve(process.cwd(), configured);
}

export type ScriptManifest = {
  id: string;
  name: string;
  description: string;
  category: string;
  tags: string[];
  rhinoVersion: string;
  version: string;
};

export type DiscoveredScript = ScriptManifest & {
  relativePath: string;
  absolutePath: string;
};

/**
 * Walk scripts/<category>/<id>/ looking for manifest.json + script.py.
 * Skips _template and folders without both files.
 */
export function discoverScripts(root = getScriptsRoot()): DiscoveredScript[] {
  if (!fs.existsSync(root)) return [];

  const results: DiscoveredScript[] = [];
  const categories = fs
    .readdirSync(root, { withFileTypes: true })
    .filter((d) => d.isDirectory() && !d.name.startsWith("_") && !d.name.startsWith("."));

  for (const cat of categories) {
    const catPath = path.join(root, cat.name);
    const scriptDirs = fs
      .readdirSync(catPath, { withFileTypes: true })
      .filter((d) => d.isDirectory());

    for (const dir of scriptDirs) {
      const scriptDir = path.join(catPath, dir.name);
      const manifestPath = path.join(scriptDir, "manifest.json");
      const pyPath = path.join(scriptDir, "script.py");
      if (!fs.existsSync(manifestPath) || !fs.existsSync(pyPath)) continue;

      try {
        const raw = JSON.parse(fs.readFileSync(manifestPath, "utf8")) as Partial<ScriptManifest>;
        const id = raw.id || dir.name;
        results.push({
          id,
          name: raw.name || id,
          description: raw.description || "",
          category: raw.category || cat.name,
          tags: Array.isArray(raw.tags) ? raw.tags : [],
          rhinoVersion: raw.rhinoVersion || "8",
          version: raw.version || "1.0.0",
          relativePath: path.join(cat.name, dir.name),
          absolutePath: scriptDir,
        });
      } catch {
        // skip invalid manifests
      }
    }
  }

  return results;
}

export function readScriptSourceFromDisk(relativePath: string): string | null {
  const full = path.join(getScriptsRoot(), relativePath, "script.py");
  if (!fs.existsSync(full)) return null;
  return fs.readFileSync(full, "utf8");
}
