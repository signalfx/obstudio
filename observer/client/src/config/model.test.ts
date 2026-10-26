import { describe, expect, it } from "vitest";
import {
  type ConfigDefinition,
  type ValueType,
  editFields,
  fieldKind,
  findDefinition,
  parseDefinitions,
  parseText,
  toText,
} from "./model";

/** A definition with placeholder wording; the tests here are about everything else. */
function definition(path: string, type: ValueType, more: Partial<ConfigDefinition> = {}): ConfigDefinition {
  return { description: "D.", path, title: "T", type, ...more };
}

const count = definition("sample.count", "integer", { minimum: 10, maximum: 500 });

describe("parseDefinitions", () => {
  it("reads the served v1 document into one section with one switch", () => {
    const sections = parseDefinitions({
      type: "object",
      properties: {
        telemetry: {
          type: "object",
          title: "Usage data",
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
      title: "Usage data",
    }]);
  });

  it("keeps the server's order of sections and definitions, and reads enum and range", () => {
    const sections = parseDefinitions({
      properties: {
        display: {
          title: "Display",
          description: "How it looks.",
          properties: {
            theme: { type: "string", title: "T", description: "D.", enum: ["dark", "light"] },
            size: { type: "integer", title: "T", description: "D.", minimum: 1, maximum: 9 },
          },
        },
        output: { title: "Output", properties: { format: { type: "string", title: "T", description: "D." } } },
      },
    });
    expect(sections?.map((section) => section.name)).toEqual(["display", "output"]);
    expect(sections?.map((section) => [section.title, section.description])).toEqual([["Display", "How it looks."], ["Output", undefined]]);
    expect(sections?.[0].definitions).toEqual([
      definition("display.theme", "string", { enum: ["dark", "light"] }),
      definition("display.size", "integer", { maximum: 9, minimum: 1 }),
    ]);
  });

  it("leaves out settings it has no control for or that lack the served wording, and sections left empty or without a title", () => {
    const sections = parseDefinitions({
      properties: {
        a: {
          title: "A",
          properties: {
            list: { type: "array", title: "T", description: "D." },
            on: { type: "boolean", title: "T", description: "D." },
            untitled: { type: "boolean", description: "D." },
            undescribed: { type: "boolean", title: "T" },
            odd: "x",
          },
        },
        b: { title: "B", properties: { map: { type: "object", title: "T", description: "D." } } },
        c: "not a section",
        untitled: { properties: { on: { type: "boolean", title: "T", description: "D." } } },
      },
    });
    expect(sections).toEqual([{ definitions: [definition("a.on", "boolean")], name: "a", title: "A" }]);
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
      display: { title: "Display", properties: { theme: { type: "string", title: "Theme", description: "The theme." } } },
      telemetry: { title: "S", properties: { enabled: { type: "boolean", title: "T", description: "D." } } },
    },
  };

  it("finds a setting and its section by the setting's dotted path", () => {
    const enabled = definition("telemetry.enabled", "boolean");
    expect(findDefinition(document, "telemetry.enabled")).toEqual({
      definition: enabled,
      section: { definitions: [enabled], name: "telemetry", title: "S" },
    });
  });

  it("returns null for a missing path or a document of the wrong shape", () => {
    expect(findDefinition(document, "telemetry.missing")).toBeNull();
    expect(findDefinition({ properties: {} }, "telemetry.enabled")).toBeNull();
    expect(findDefinition("<!doctype html>", "telemetry.enabled")).toBeNull();
  });
});

describe("fieldKind and editFields", () => {
  it("sends switches and choices at once and debounces typed fields", () => {
    expect(fieldKind(definition("a.b", "boolean"))).toBe("immediate");
    expect(fieldKind(definition("a.b", "string", { enum: ["x", "y"] }))).toBe("immediate");
    expect(fieldKind(definition("a.b", "integer", { enum: [1, 2] }))).toBe("immediate");
    expect(fieldKind(definition("a.b", "string"))).toBe("debounced");
    expect(fieldKind(definition("a.b", "string", { enum: [] }))).toBe("debounced");
    expect(fieldKind(count)).toBe("debounced");
  });

  it("covers every setting in every section", () => {
    expect(editFields([
      { definitions: [definition("a.on", "boolean"), definition("a.name", "string")], name: "a", title: "a" },
      { definitions: [count], name: "b", title: "b" },
    ])).toEqual({ "a.name": "debounced", "a.on": "immediate", "sample.count": "debounced" });
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
    expect(parseText(definition("a.b", "integer"), "+7")).toEqual({ ok: true, value: 7 });
    expect(parseText(definition("a.b", "integer"), "-3")).toEqual({ ok: true, value: -3 });
  });

  it("rejects non-integers", () => {
    for (const text of ["", " ", "abc", "4.5", "1e3", "0x10", "12 34"]) {
      expect(parseText(count, text)).toEqual({ ok: false, error: "Enter a whole number" });
    }
  });

  it("rejects integers beyond the safe range", () => {
    expect(parseText(definition("a.b", "integer"), "99999999999999999999")).toEqual({
      ok: false,
      error: "Enter a smaller whole number",
    });
  });

  it("checks the range, with a message for each bound combination", () => {
    expect(parseText(count, "5")).toEqual({ ok: false, error: "Must be a whole number between 10 and 500" });
    expect(parseText(count, "900")).toEqual({ ok: false, error: "Must be a whole number between 10 and 500" });
    expect(parseText(count, "10")).toEqual({ ok: true, value: 10 });
    expect(parseText(count, "500")).toEqual({ ok: true, value: 500 });
    expect(parseText(definition("a.b", "integer", { minimum: 5 }), "4")).toEqual({ ok: false, error: "Must be at least 5" });
    expect(parseText(definition("a.b", "integer", { maximum: 5 }), "6")).toEqual({ ok: false, error: "Must be at most 5" });
  });

  it("checks allowed values for strings and integers", () => {
    const level: ConfigDefinition = definition("a.b", "string", { enum: ["debug", "info"] });
    expect(parseText(level, "info")).toEqual({ ok: true, value: "info" });
    expect(parseText(level, "loud")).toEqual({ ok: false, error: "Must be one of: debug, info" });
    const size: ConfigDefinition = definition("a.b", "integer", { enum: [10, 20] });
    expect(parseText(size, "20")).toEqual({ ok: true, value: 20 });
    expect(parseText(size, "15")).toEqual({ ok: false, error: "Must be one of: 10, 20" });
  });

  it("accepts any string, including empty, when no allowed values apply", () => {
    expect(parseText(definition("a.b", "string"), "")).toEqual({ ok: true, value: "" });
  });
});
