import type { ConfigKeySpec } from "../api/types";

export type FieldKind = "boolean" | "integer" | "string" | "unsupported";

/** What a control shows: booleans are toggled, everything else is typed or chosen as text. */
export type DraftValue = string | boolean;

export type ParseResult =
  | { ok: true; value: string | number | boolean }
  | { ok: false; error: string };

export interface ConfigSection {
  id: string;
  title: string;
  specs: ConfigKeySpec[];
}

export function fieldKind(spec: ConfigKeySpec): FieldKind {
  switch (spec.type) {
    case "boolean":
    case "integer":
    case "string":
      return spec.type;
    default:
      return "unsupported";
  }
}

/** The server's label for the key, or the exact key when it has none. */
export function displayLabel(spec: ConfigKeySpec): string {
  const label = spec.label?.trim();
  return label !== undefined && label !== "" ? label : spec.key;
}

/** The server's description for the key, if it has one. */
export function displayDescription(spec: ConfigKeySpec): string | null {
  const description = spec.description?.trim();
  return description !== undefined && description !== "" ? description : null;
}

function sectionKey(key: string): string {
  const segments = key.split(".");
  return segments.length > 1 ? segments[0] : "";
}

/** Group keys by their first path segment. Single-segment keys go in a leading "General" section. */
export function groupSections(specs: ConfigKeySpec[]): ConfigSection[] {
  const sorted = [...specs].sort((a, b) => (a.key < b.key ? -1 : a.key > b.key ? 1 : 0));
  const sections = new Map<string, ConfigSection>();
  for (const spec of sorted) {
    const name = sectionKey(spec.key);
    let section = sections.get(name);
    if (section === undefined) {
      section = {
        id: name === "" ? "general" : name,
        specs: [],
        title: name === "" ? "General" : name,
      };
      sections.set(name, section);
    }
    section.specs.push(spec);
  }
  const general = sections.get("");
  const rest = [...sections.entries()].filter(([name]) => name !== "").map(([, section]) => section);
  return general === undefined ? rest : [general, ...rest];
}

/** Read a dotted key out of the nested GET /api/config values. */
export function lookupValue(values: Record<string, unknown>, key: string): unknown {
  let node: unknown = values;
  for (const segment of key.split(".")) {
    if (typeof node !== "object" || node === null || Array.isArray(node)) return undefined;
    node = (node as Record<string, unknown>)[segment];
  }
  return node;
}

export function toDraft(spec: ConfigKeySpec, value: unknown): DraftValue {
  if (fieldKind(spec) === "boolean") return value === true;
  if (value === undefined || value === null) return "";
  if (fieldKind(spec) === "unsupported" && typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function describeAllowed(values: Array<string | number | boolean>): string {
  return `Must be one of: ${values.join(", ")}`;
}

function rangeError(spec: ConfigKeySpec, value: number): string | null {
  const { minimum, maximum } = spec;
  if (minimum !== undefined && maximum !== undefined && (value < minimum || value > maximum)) {
    return `Must be a whole number between ${minimum} and ${maximum}`;
  }
  if (minimum !== undefined && value < minimum) return `Must be at least ${minimum}`;
  if (maximum !== undefined && value > maximum) return `Must be at most ${maximum}`;
  return null;
}

/** Check a draft against the schema before sending it. The server stays authoritative. */
export function parseDraft(spec: ConfigKeySpec, draft: DraftValue): ParseResult {
  const allowed = spec.allowedValues !== undefined && spec.allowedValues.length > 0 ? spec.allowedValues : null;
  switch (fieldKind(spec)) {
    case "boolean":
      return { ok: true, value: draft === true };
    case "integer": {
      const text = typeof draft === "string" ? draft.trim() : "";
      if (!/^[+-]?\d+$/.test(text)) return { ok: false, error: "Enter a whole number" };
      const value = Number(text);
      if (!Number.isSafeInteger(value)) return { ok: false, error: "Enter a smaller whole number" };
      const outOfRange = rangeError(spec, value);
      if (outOfRange !== null) return { ok: false, error: outOfRange };
      if (allowed !== null && !allowed.includes(value)) return { ok: false, error: describeAllowed(allowed) };
      return { ok: true, value };
    }
    case "string": {
      const text = typeof draft === "string" ? draft : "";
      if (allowed !== null && !allowed.includes(text)) return { ok: false, error: describeAllowed(allowed) };
      return { ok: true, value: text };
    }
    default:
      return { ok: false, error: "This setting's type is not supported here" };
  }
}
