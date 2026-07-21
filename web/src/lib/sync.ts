import fs from "fs";
import path from "path";
import { prisma } from "./prisma";
import { discoverScripts, getScriptsRoot } from "./scripts";

function readSourceFromDisk(relativePath: string): string | null {
  const full = path.join(getScriptsRoot(), relativePath, "script.py");
  if (!fs.existsSync(full)) return null;
  return fs.readFileSync(full, "utf8");
}

export async function syncScriptsFromDisk() {
  const discovered = discoverScripts();
  const seen = new Set<string>();

  for (const s of discovered) {
    seen.add(s.id);
    const source = readSourceFromDisk(s.relativePath);
    await prisma.script.upsert({
      where: { id: s.id },
      create: {
        id: s.id,
        name: s.name,
        description: s.description,
        category: s.category,
        tags: JSON.stringify(s.tags),
        rhinoVersion: s.rhinoVersion,
        version: s.version,
        relativePath: s.relativePath,
        source,
      },
      update: {
        name: s.name,
        description: s.description,
        category: s.category,
        tags: JSON.stringify(s.tags),
        rhinoVersion: s.rhinoVersion,
        version: s.version,
        relativePath: s.relativePath,
        source,
      },
    });
  }

  // Remove DB entries that no longer exist on disk (keep internal sentinels)
  const all = await prisma.script.findMany({ select: { id: true } });
  const toDelete = all
    .filter((s) => !seen.has(s.id) && !s.id.startsWith("__"))
    .map((s) => s.id);
  if (toDelete.length) {
    await prisma.script.deleteMany({ where: { id: { in: toDelete } } });
  }

  return { synced: discovered.length, removed: toDelete.length };
}

export function parseTags(tags: string): string[] {
  try {
    const parsed = JSON.parse(tags);
    return Array.isArray(parsed) ? parsed.map(String) : [];
  } catch {
    return [];
  }
}
