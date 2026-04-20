// @vitest-environment happy-dom

import { readFileSync } from "fs";
import { resolve } from "path";
import { describe, expect, it } from "vitest";

describe("FindingsTab detail panel responsive styles", () => {
  it("uses container-based responsive rules for the validation detail panel", () => {
    const css = readFileSync(resolve(process.cwd(), "src/styles.css"), "utf8");

    expect(css).toContain(".findings-tab__detail-body {\n  padding: 10px 14px 14px;\n  container-type: inline-size;\n  container-name: findings-detail;\n}");
    expect(css).toContain(".findings-tab__detail-panel-shell {\n  display: flex;\n  flex: 1;\n  width: 100%;\n  min-height: 0;\n  overflow: hidden;\n}");
    expect(css).toContain(".findings-tab__detail-panel-shell > .detail-panel {\n  flex: 1;\n  width: 100%;\n  min-width: 0;\n}");
    expect(css).toContain("@container findings-detail (max-width: 520px) {");
    expect(css).toContain("@container findings-detail (max-width: 420px) {");
    expect(css).toContain("@container findings-detail (max-width: 340px) {");
    expect(css).not.toContain(".findings-tab__detail-summary");
    expect(css).not.toContain(".findings-tab__summary-card");
    expect(css).not.toContain(".findings-tab__severity-group-header {\n    align-items: flex-start;\n    flex-direction: column;");
  });
});
