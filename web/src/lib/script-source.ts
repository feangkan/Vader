import { prisma } from "./prisma";
import { readScriptSourceFromDisk } from "./scripts";

/** Resolve script source: DB first (cloud), then disk (local dev). */
export async function getScriptSource(
  scriptId: string,
  relativePath: string
): Promise<string | null> {
  const row = await prisma.script.findUnique({
    where: { id: scriptId },
    select: { source: true },
  });
  if (row?.source) return row.source;
  return readScriptSourceFromDisk(relativePath);
}
