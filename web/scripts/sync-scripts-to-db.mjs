/**
 * Sync scripts/ folder into the database (metadata + source).
 * Run before deploy so cloud hosts don't need the scripts/ filesystem.
 *
 * Usage (from web/):
 *   node scripts/sync-scripts-to-db.mjs
 */
import { PrismaClient } from "@prisma/client";
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const prisma = new PrismaClient();

function getScriptsRoot() {
  const configured = process.env.SCRIPTS_ROOT || "../scripts";
  return path.resolve(process.cwd(), configured);
}

function discover(root) {
  const results = [];
  if (!fs.existsSync(root)) return results;

  for (const cat of fs
    .readdirSync(root, { withFileTypes: true })
    .filter((d) => d.isDirectory() && !d.name.startsWith("_") && !d.name.startsWith("."))) {
    const catPath = path.join(root, cat.name);
    for (const dir of fs
      .readdirSync(catPath, { withFileTypes: true })
      .filter((d) => d.isDirectory())) {
      const scriptDir = path.join(catPath, dir.name);
      const manifestPath = path.join(scriptDir, "manifest.json");
      const pyPath = path.join(scriptDir, "script.py");
      if (!fs.existsSync(manifestPath) || !fs.existsSync(pyPath)) continue;

      try {
        const raw = JSON.parse(fs.readFileSync(manifestPath, "utf8"));
        const id = raw.id || dir.name;
        results.push({
          id,
          name: raw.name || id,
          description: raw.description || "",
          category: raw.category || cat.name,
          tags: JSON.stringify(Array.isArray(raw.tags) ? raw.tags : []),
          rhinoVersion: raw.rhinoVersion || "8",
          version: raw.version || "1.0.0",
          relativePath: path.join(cat.name, dir.name),
          source: fs.readFileSync(pyPath, "utf8"),
        });
      } catch {
        // skip invalid
      }
    }
  }
  return results;
}

async function main() {
  const root = getScriptsRoot();
  console.log("Syncing from:", root);
  const discovered = discover(root);
  const seen = new Set();

  for (const s of discovered) {
    seen.add(s.id);
    await prisma.script.upsert({
      where: { id: s.id },
      create: s,
      update: s,
    });
  }

  const all = await prisma.script.findMany({ select: { id: true } });
  const toDelete = all
    .filter((s) => !seen.has(s.id) && !s.id.startsWith("__"))
    .map((s) => s.id);
  if (toDelete.length) {
    await prisma.script.deleteMany({ where: { id: { in: toDelete } } });
  }

  console.log(`Synced ${discovered.length} scripts (removed ${toDelete.length})`);
}

main()
  .catch((e) => {
    console.error(e);
    process.exit(1);
  })
  .finally(() => prisma.$disconnect());
