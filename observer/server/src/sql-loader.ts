import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

function resolveBaseDir(): string {
  try {
    if (import.meta.url) {
      return path.dirname(fileURLToPath(import.meta.url));
    }
  } catch {
    // CJS fallback (esbuild bundle)
  }
  return __dirname;
}

const SQL_FILE = path.resolve(resolveBaseDir(), "sql", "queries.sql");

let sections: Map<string, string> | null = null;

function parseSections(): Map<string, string> {
  if (sections !== null) return sections;

  const content = fs.readFileSync(SQL_FILE, "utf-8");
  const parsed = new Map<string, string>();
  let currentName: string | null = null;
  let currentLines: string[] = [];

  for (const line of content.split("\n")) {
    const match = line.match(/^--\s*@name\s+(\S+)/);
    if (match) {
      if (currentName !== null) {
        parsed.set(currentName, currentLines.join("\n").trim());
      }
      currentName = match[1];
      currentLines = [];
    } else {
      currentLines.push(line);
    }
  }

  if (currentName !== null) {
    parsed.set(currentName, currentLines.join("\n").trim());
  }

  sections = parsed;
  return parsed;
}

export function loadSQL(name: string): string {
  const map = parseSections();
  const sql = map.get(name);
  if (sql === undefined) {
    throw new Error(`SQL section "${name}" not found in queries.sql`);
  }
  return sql;
}

export function splitStatements(sql: string): string[] {
  return sql
    .split(";")
    .map((s) => s.trim())
    .filter((s) => s.length > 0 && !s.startsWith("--"));
}
