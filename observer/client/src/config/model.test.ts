import { describe, expect, it } from "vitest";
import {
  type ConfigDefinition,
  displayDescription,
  displayTitle,
  editFields,
  fieldKind,
  findDefinition,
  parseDefinitions,
  parseText,
  toText,
} from "./model";

const count: ConfigDefinition = { path: "sample.count", type: "integer", minimum: 10, maximum: 500 };

describe("parseDefinitions", () => {
  it("reads the served v1 document into one section with one switch", () => {
    const sections = parseDefinitions({
      type: "object",
      properties: {
        telemetry: {
          type: "object",
          properties: {
            enabled: {
              type: "boolean",
              title: "Send anonymous usage data",
              description: "Sends anonymous usage counts.",
              default: true,
              "x-obstudio-failSafe": false,
              "x-obstudio-apply": "live",
            },
          },
        },
      },
    });
    expect(sections).toEqual([{
      definitions: [{
        apply: "live",
        default: true,
        description: "Sends anonymous usage counts.",
        path: "telemetry.enabled",
        title: "Send anonymous usage data",
        type: "boolean",
      }],
      name: "telemetry",
      title: "telemetry",
    }]);
  });

  it("keeps the server's order of sections and definitions, and reads enum and range", () => {
    const sections = parseDefinitions({
      properties: {
        display: { properties: { theme: { type: "string", enum: ["dark", "light"] }, size: { type: "integer", minimum: 1, maximum: 9 } } },
        output: { properties: { format: { type: "string" } } },
      },
    });
    expect(sections?.map((section) => section.name)).toEqual(["display", "output"]);
    expect(sections?.[0].definitions).toEqual([
      { enum: ["dark", "light"], path: "display.theme", type: "string" },
      { maximum: 9, minimum: 1, path: "display.size", type: "integer" },
    ]);
  });

  it("leaves out settings it has no control for, and sections left empty", () => {
    const sections = parseDefinitions({
      properties: {
        a: { properties: { list: { type: "array" }, on: { type: "boolean" }, odd: "x" } },
        b: { properties: { map: { type: "object" } } },
        c: "not a section",
      },
    });
    expect(sections).toEqual([{ definitions: [{ path: "a.on", type: "boolean" }], name: "a", title: "a" }]);
  });

  it("returns no sections for an empty document, and null for one of the wrong shape", () => {
    expect(parseDefinitions({ type: "object", properties: {} })).toEqual([]);
    for (const document of [null, [], "x", {}, { properties: [] }]) {
      expect(parseDefinitions(document)).toBeNull();
    }
  });
});

describe("findDefinition", () => {
  const document = {
    properties: {
      display: { properties: { theme: { type: "string" } } },
      telemetry: { properties: { enabled: { type: "boolean", title: "T", description: "D." } } },
    },
  };

  it("finds a setting by its dotted path", () => {
    expect(findDefinition(document, "telemetry.enabled")).toEqual({ description: "D.", path: "telemetry.enabled", title: "T", type: "boolean" });
  });

  it("returns null for a missing path or a document of the wrong shape", () => {
    expect(findDefinition(document, "telemetry.missing")).toBeNull();
    expect(findDefinition({ properties: {} }, "telemetry.enabled")).toBeNull();
    expect(findDefinition("<!doctype html>", "telemetry.enabled")).toBeNull();
  });
});

describe("fieldKind and editFields", () => {
  it("sends switches and choices at once and debounces typed fields", () => {
    expect(fieldKind({ path: "a.b", type: "boolean" })).toBe("immediate");
    expect(fieldKind({ path: "a.b", type: "string", enum: ["x", "y"] })).toBe("immediate");
    expect(fieldKind({ path: "a.b", type: "integer", enum: [1, 2] })).toBe("immediate");
    expect(fieldKind({ path: "a.b", type: "string" })).toBe("debounced");
    expect(fieldKind({ path: "a.b", type: "string", enum: [] })).toBe("debounced");
    expect(fieldKind(count)).toBe("debounced");
  });

  it("covers every setting in every section", () => {
    expect(editFields([
      { definitions: [{ path: "a.on", type: "boolean" }, { path: "a.name", type: "string" }], name: "a", title: "a" },
      { definitions: [count], name: "b", title: "b" },
    ])).toEqual({ "a.name": "debounced", "a.on": "immediate", "sample.count": "debounced" });
  });
});

describe("displayTitle and displayDescription", () => {
  it("prefers the server's title and trims it", () => {
    expect(displayTitle({ path: "sample.enabled", type: "boolean", title: "  Enable sample " })).toBe("Enable sample");
  });

  it("falls back to the exact path, case and all, when the server sent no title or a blank one", () => {
    expect(displayTitle({ path: "sample.flagStatus", type: "boolean" })).toBe("sample.flagStatus");
    expect(displayTitle({ path: "sample.flagStatus", type: "boolean", title: "" })).toBe("sample.flagStatus");
    expect(displayTitle({ path: "sample.flagStatus", type: "boolean", title: "  " })).toBe("sample.flagStatus");
  });

  it("returns the trimmed description, or null when there is none", () => {
    expect(displayDescription({ path: "a.b", type: "string", description: " Does a thing. " })).toBe("Does a thing.");
    expect(displayDescription({ path: "a.b", type: "string" })).toBeNull();
    expect(displayDescription({ path: "a.b", type: "string", description: "  " })).toBeNull();
  });
});

describe("toText", () => {
  it("shows values as text, and a missing value as empty", () => {
    expect(toText(200)).toBe("200");
    expect(toText("abc")).toBe("abc");
    expect(toText(false)).toBe("false");
    expect(toText(undefined)).toBe("");
  });
});

describe("parseText", () => {
  it("parses whole numbers, tolerating whitespace and a sign", () => {
    expect(parseText(count, " 200 ")).toEqual({ ok: true, value: 200 });
    expect(parseText({ path: "a.b", type: "integer" }, "+7")).toEqual({ ok: true, value: 7 });
    expect(parseText({ path: "a.b", type: "integer" }, "-3")).toEqual({ ok: true, value: -3 });
  });

  it("rejects non-integers", () => {
    for (const text of ["", " ", "abc", "4.5", "1e3", "0x10", "12 34"]) {
      expect(parseText(count, text)).toEqual({ ok: false, error: "Enter a whole number" });
    }
  });

  it("rejects integers beyond the safe range", () => {
    expect(parseText({ path: "a.b", type: "integer" }, "99999999999999999999")).toEqual({
      ok: false,
      error: "Enter a smaller whole number",
    });
  });

  it("checks the range, with a message for each bound combination", () => {
    expect(parseText(count, "5")).toEqual({ ok: false, error: "Must be a whole number between 10 and 500" });
    expect(parseText(count, "900")).toEqual({ ok: false, error: "Must be a whole number between 10 and 500" });
    expect(parseText(count, "10")).toEqual({ ok: true, value: 10 });
    expect(parseText(count, "500")).toEqual({ ok: true, value: 500 });
    expect(parseText({ path: "a.b", type: "integer", minimum: 5 }, "4")).toEqual({ ok: false, error: "Must be at least 5" });
    expect(parseText({ path: "a.b", type: "integer", maximum: 5 }, "6")).toEqual({ ok: false, error: "Must be at most 5" });
  });

  it("checks allowed values for strings and integers", () => {
    const level: ConfigDefinition = { path: "a.b", type: "string", enum: ["debug", "info"] };
    expect(parseText(level, "info")).toEqual({ ok: true, value: "info" });
    expect(parseText(level, "loud")).toEqual({ ok: false, error: "Must be one of: debug, info" });
    const size: ConfigDefinition = { path: "a.b", type: "integer", enum: [10, 20] };
    expect(parseText(size, "20")).toEqual({ ok: true, value: 20 });
    expect(parseText(size, "15")).toEqual({ ok: false, error: "Must be one of: 10, 20" });
  });

  it("accepts any string, including empty, when no allowed values apply", () => {
    expect(parseText({ path: "a.b", type: "string" }, "")).toEqual({ ok: true, value: "" });
  });
});
