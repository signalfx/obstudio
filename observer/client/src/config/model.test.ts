import { describe, expect, it } from "vitest";
import type { ConfigKeySpec } from "../api/types";
import { displayDescription, displayLabel, fieldKind, groupSections, lookupValue, parseDraft, toDraft } from "./model";

const port: ConfigKeySpec = { key: "ui.port", type: "integer", minimum: 1024, maximum: 65535 };

describe("displayLabel and displayDescription", () => {
  it("prefers the server's label and trims it", () => {
    expect(displayLabel({ key: "splunk.metricsExport", type: "boolean", label: "  Export metrics " })).toBe("Export metrics");
  });

  it("falls back to the exact key, case and all, when the server sent no label or a blank one", () => {
    expect(displayLabel({ key: "o11y.flagStatus", type: "boolean" })).toBe("o11y.flagStatus");
    expect(displayLabel({ key: "o11y.flagStatus", type: "boolean", label: "" })).toBe("o11y.flagStatus");
    expect(displayLabel({ key: "o11y.flagStatus", type: "boolean", label: "  " })).toBe("o11y.flagStatus");
    expect(displayLabel({ key: "splunk.metrics_Export-2", type: "boolean" })).toBe("splunk.metrics_Export-2");
    expect(displayLabel({ key: "workspaceRoot", type: "string" })).toBe("workspaceRoot");
  });

  it("returns the trimmed description, or null when there is none", () => {
    expect(displayDescription({ key: "a", type: "string", description: " Does a thing. " })).toBe("Does a thing.");
    expect(displayDescription({ key: "a", type: "string" })).toBeNull();
    expect(displayDescription({ key: "a", type: "string", description: "  " })).toBeNull();
  });
});

describe("groupSections", () => {
  it("groups by first segment, sorted, with single-segment keys in a leading General section", () => {
    const sections = groupSections([
      { key: "ui.port", type: "integer" },
      { key: "splunk.realm", type: "string" },
      { key: "mode", type: "string" },
      { key: "splunk.metricsExport", type: "boolean" },
    ]);
    expect(sections.map((section) => [section.id, section.title])).toEqual([
      ["general", "General"],
      ["splunk", "splunk"],
      ["ui", "ui"],
    ]);
    expect(sections[1].specs.map((spec) => spec.key)).toEqual(["splunk.metricsExport", "splunk.realm"]);
  });

  it("titles a section with its exact first path segment", () => {
    const sections = groupSections([
      { key: "o11y.realm", type: "string" },
      { key: "o11y.oauthEnabled", type: "boolean" },
    ]);
    expect(sections.map((section) => [section.id, section.title])).toEqual([["o11y", "o11y"]]);
    expect(sections[0].specs.map((spec) => spec.key)).toEqual(["o11y.oauthEnabled", "o11y.realm"]);
  });

  it("returns no sections for no keys", () => {
    expect(groupSections([])).toEqual([]);
  });
});

describe("lookupValue", () => {
  const values = { splunk: { realm: "us1", nested: { flag: false } }, top: 3, list: [1] };

  it("walks dotted paths in the nested values", () => {
    expect(lookupValue(values, "splunk.realm")).toBe("us1");
    expect(lookupValue(values, "splunk.nested.flag")).toBe(false);
    expect(lookupValue(values, "top")).toBe(3);
  });

  it("returns undefined for missing paths and for paths through non-objects", () => {
    expect(lookupValue(values, "splunk.missing")).toBeUndefined();
    expect(lookupValue(values, "top.deeper")).toBeUndefined();
    expect(lookupValue(values, "list.0")).toBeUndefined();
  });
});

describe("toDraft", () => {
  it("shows booleans as booleans and everything else as text", () => {
    expect(toDraft({ key: "a", type: "boolean" }, true)).toBe(true);
    expect(toDraft({ key: "a", type: "boolean" }, undefined)).toBe(false);
    expect(toDraft(port, 17900)).toBe("17900");
    expect(toDraft({ key: "a", type: "string" }, null)).toBe("");
  });

  it("serializes objects for unsupported types", () => {
    expect(toDraft({ key: "a", type: "list" }, ["x"])).toBe('["x"]');
  });
});

describe("fieldKind", () => {
  it("recognises the supported types and flags the rest", () => {
    expect(fieldKind({ key: "a", type: "integer" })).toBe("integer");
    expect(fieldKind({ key: "a", type: "duration" })).toBe("unsupported");
  });
});

describe("parseDraft", () => {
  it("parses whole numbers, tolerating whitespace and a sign", () => {
    expect(parseDraft(port, " 18000 ")).toEqual({ ok: true, value: 18000 });
    expect(parseDraft({ key: "a", type: "integer" }, "+7")).toEqual({ ok: true, value: 7 });
    expect(parseDraft({ key: "a", type: "integer" }, "-3")).toEqual({ ok: true, value: -3 });
  });

  it("rejects non-integers", () => {
    for (const text of ["", " ", "abc", "4.5", "1e3", "0x10", "12 34"]) {
      expect(parseDraft(port, text)).toEqual({ ok: false, error: "Enter a whole number" });
    }
  });

  it("rejects integers beyond the safe range", () => {
    expect(parseDraft({ key: "a", type: "integer" }, "99999999999999999999")).toEqual({
      ok: false,
      error: "Enter a smaller whole number",
    });
  });

  it("checks the range, with a message for each bound combination", () => {
    expect(parseDraft(port, "80")).toEqual({ ok: false, error: "Must be a whole number between 1024 and 65535" });
    expect(parseDraft(port, "70000")).toEqual({ ok: false, error: "Must be a whole number between 1024 and 65535" });
    expect(parseDraft(port, "1024")).toEqual({ ok: true, value: 1024 });
    expect(parseDraft(port, "65535")).toEqual({ ok: true, value: 65535 });
    expect(parseDraft({ key: "a", type: "integer", minimum: 5 }, "4")).toEqual({ ok: false, error: "Must be at least 5" });
    expect(parseDraft({ key: "a", type: "integer", maximum: 5 }, "6")).toEqual({ ok: false, error: "Must be at most 5" });
  });

  it("checks allowed values for strings and integers", () => {
    const level: ConfigKeySpec = { key: "a", type: "string", allowedValues: ["debug", "info"] };
    expect(parseDraft(level, "info")).toEqual({ ok: true, value: "info" });
    expect(parseDraft(level, "loud")).toEqual({ ok: false, error: "Must be one of: debug, info" });
    const size: ConfigKeySpec = { key: "a", type: "integer", allowedValues: [10, 20] };
    expect(parseDraft(size, "20")).toEqual({ ok: true, value: 20 });
    expect(parseDraft(size, "15")).toEqual({ ok: false, error: "Must be one of: 10, 20" });
  });

  it("accepts any string, including empty, when no allowed values apply", () => {
    expect(parseDraft({ key: "a", type: "string" }, "")).toEqual({ ok: true, value: "" });
  });

  it("passes booleans through and refuses unsupported types", () => {
    expect(parseDraft({ key: "a", type: "boolean" }, true)).toEqual({ ok: true, value: true });
    expect(parseDraft({ key: "a", type: "boolean" }, false)).toEqual({ ok: true, value: false });
    expect(parseDraft({ key: "a", type: "duration" }, "5s").ok).toBe(false);
  });
});
