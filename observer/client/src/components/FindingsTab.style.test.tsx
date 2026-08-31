// @vitest-environment happy-dom

import { readFileSync } from "fs";
import { resolve } from "path";
import { describe, expect, it } from "vitest";

describe("FindingsTab detail panel responsive styles", () => {
  it("uses container-based responsive rules for the validation detail panel", () => {
    const css = readFileSync(resolve(process.cwd(), "src/styles.css"), "utf8");

    expect(css).toContain(".findings-tab__detail-body {\n  padding: 10px 14px 14px;\n  container-type: inline-size;\n  container-name: findings-detail;\n}");
    expect(css).toContain(".findings-tab__panel-shell {\n  display: flex;\n  flex: 1;\n  width: 100%;\n  min-height: 0;\n  overflow: hidden;\n}");
    expect(css).toContain(".findings-tab__panel-shell > .detail-panel {\n  flex: 1;\n  width: 100%;\n  min-width: 0;\n}");
    expect(css).toContain("@container findings-detail (max-width: 520px) {");
    expect(css).toContain("@container findings-detail (max-width: 420px) {");
    expect(css).toContain("@container findings-detail (max-width: 340px) {");
    expect(css).toContain(".data-table__head--findings,\n.data-table__row--findings {\n  --table-columns: minmax(160px, 3fr) minmax(84px, 1fr) minmax(108px, 1fr) minmax(44px, 1fr) minmax(120px, 6fr);\n}");
    expect(css).toContain(".findings-tab__head .data-table__th {\n  padding: 0 6px;\n  min-width: 0;\n  overflow: hidden;\n  text-overflow: ellipsis;\n  white-space: nowrap;\n}");
    // Current row layout contract — data-table__row--findings cell alignment
    expect(css).toContain(".data-table__row--findings .data-table__td--numeric {\n  justify-content: center;\n  text-align: center;\n}");
    expect(css).toContain(".findings-tab__rule-cell {\n  display: flex;\n  flex-wrap: wrap;\n  align-items: center;\n  gap: 4px;");
    expect(css).toContain(".findings-tab__count--violation.is-zero,\n.findings-tab__count--improvement.is-zero,\n.findings-tab__count--information.is-zero {\n  color: var(--text-soft);\n  opacity: 0.4;\n}");
    // Legacy item-wrapper/trigger/grid/title/rule/count styles must be absent
    expect(css).not.toContain(".findings-tab__item-trigger");
    expect(css).not.toContain(".findings-tab__item-grid");
    expect(css).not.toContain(".findings-tab__item-title");
    expect(css).not.toContain(".findings-tab__item-rule");
    expect(css).not.toContain(".findings-tab__item-count");
    expect(css).not.toContain(".findings-tab__item-pill");
    expect(css).not.toContain(".findings-tab__detail-summary");
    expect(css).not.toContain(".findings-tab__summary-card");
    expect(css).not.toContain(".findings-tab__severity-group-header {\n    align-items: flex-start;\n    flex-direction: column;");
  });
});
