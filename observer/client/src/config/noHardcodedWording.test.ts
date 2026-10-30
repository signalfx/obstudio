import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, resolve } from "node:path";
import { describe, expect, it } from "vitest";

interface ProductionWording {
  sectionTitle: string;
  title: string;
  description: string;
}

function productionWording(): ProductionWording {
  const golden = JSON.parse(readFileSync(resolve("../internal/userconfig/testdata/definitions.golden.json"), "utf8"));
  const section = golden.properties.telemetry as { title: string; properties: { enabled: { title: string; description: string } } };
  return { sectionTitle: section.title, title: section.properties.enabled.title, description: section.properties.enabled.description };
}

describe("client wording", () => {
  it("contains no copy of the production wording", () => {
    const { sectionTitle, title, description } = productionWording();
    const quoted = sectionTitle.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    // A hardcoded heading is the whole title as a string literal or as JSX text;
    // longer client strings may contain the same words.
    const wholeSectionTitle = new RegExp(`(['"\`])${quoted}\\1|>\\s*${quoted}\\s*<`);
    const firstSentence = description.slice(0, description.indexOf(".") + 1);
    const root = resolve("src");
    const files: string[] = [];
    const walk = (dir: string): void => {
      for (const name of readdirSync(dir)) {
        const full = join(dir, name);
        if (statSync(full).isDirectory()) walk(full);
        else if (/\.(ts|tsx|css)$/.test(name) && !/\.test\.tsx?$/.test(name)) files.push(full);
      }
    };
    walk(root);
    expect(files.length).toBeGreaterThan(0);
    for (const file of files) {
      const source = readFileSync(file, "utf8");
      expect(source.includes(title), file).toBe(false);
      expect(source.includes(description), file).toBe(false);
      expect(source.includes(firstSentence), file).toBe(false);
      expect(wholeSectionTitle.test(source), file).toBe(false);
    }
  });
});
