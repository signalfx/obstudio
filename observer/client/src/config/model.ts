import type { FieldKind as EditKind, FieldValue } from "../cloud/configEdits";

/** A JSON Schema type the tab has a control for. */
export type FieldKind = "boolean" | "integer" | "string";

/** One setting, read from GET /api/config/definitions. */
export interface ConfigKeySpec {
  /** Dotted path, such as telemetry.enabled. */
  key: string;
  type: FieldKind;
  title?: string;
  description?: string;
  enum?: FieldValue[];
  minimum?: number;
  maximum?: number;
  /** x-obstudio-apply: whether a change applies live or after a restart. */
  apply?: "live" | "restart";
}

export interface ConfigSection {
  id: string;
  title: string;
  specs: ConfigKeySpec[];
}

export type ParseResult =
  | { ok: true; value: FieldValue }
  | { ok: false; error: string };

type Node = Record<string, unknown>;

function isNode(value: unknown): value is Node {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function isFieldKind(value: unknown): value is FieldKind {
  return value === "boolean" || value === "integer" || value === "string";
}

function isFieldValue(value: unknown): value is FieldValue {
  return typeof value === "boolean" || typeof value === "number" || typeof value === "string";
}

function readSpec(key: string, node: Node): ConfigKeySpec | null {
  if (!isFieldKind(node.type)) return null;
  const spec: ConfigKeySpec = { key, type: node.type };
  if (typeof node.title === "string") spec.title = node.title;
  if (typeof node.description === "string") spec.description = node.description;
  if (Array.isArray(node.enum) && node.enum.every(isFieldValue)) spec.enum = node.enum;
  if (typeof node.minimum === "number") spec.minimum = node.minimum;
  if (typeof node.maximum === "number") spec.maximum = node.maximum;
  if (node["x-obstudio-apply"] === "live" || node["x-obstudio-apply"] === "restart") spec.apply = node["x-obstudio-apply"];
  return spec;
}

/**
 * Read the definitions document into sections, in the order the server lists
 * them. Each top-level property is a section and each of its properties is a
 * setting. Settings of a type the tab has no control for are left out.
 * Returns null when the document does not have that shape.
 */
export function parseDefinitions(document: unknown): ConfigSection[] | null {
  if (!isNode(document) || !isNode(document.properties)) return null;
  const sections: ConfigSection[] = [];
  for (const [name, section] of Object.entries(document.properties)) {
    if (!isNode(section) || !isNode(section.properties)) continue;
    const specs: ConfigKeySpec[] = [];
    for (const [leaf, node] of Object.entries(section.properties)) {
      const spec = isNode(node) ? readSpec(`${name}.${leaf}`, node) : null;
      if (spec !== null) specs.push(spec);
    }
    if (specs.length > 0) sections.push({ id: name, specs, title: name });
  }
  return sections;
}

/** Discrete controls send at once; typed ones wait for the debounce. */
export function editKind(spec: ConfigKeySpec): EditKind {
  return spec.type === "boolean" || hasChoices(spec) ? "immediate" : "debounced";
}

export function hasChoices(spec: ConfigKeySpec): boolean {
  return spec.type !== "boolean" && spec.enum !== undefined && spec.enum.length > 0;
}

/** The configEdits fields for every setting in the sections. */
export function editFields(sections: readonly ConfigSection[]): Record<string, EditKind> {
  const fields: Record<string, EditKind> = {};
  for (const section of sections) {
    for (const spec of section.specs) fields[spec.key] = editKind(spec);
  }
  return fields;
}

/** The server's title for the key, or the exact key when it has none. */
export function displayLabel(spec: ConfigKeySpec): string {
  const label = spec.title?.trim();
  return label !== undefined && label !== "" ? label : spec.key;
}

/** The server's description for the key, if it has one. */
export function displayDescription(spec: ConfigKeySpec): string | null {
  const description = spec.description?.trim();
  return description !== undefined && description !== "" ? description : null;
}

/** How a value is shown in a text field or select. */
export function toText(value: FieldValue | undefined): string {
  return value === undefined ? "" : String(value);
}

function describeAllowed(values: readonly FieldValue[]): string {
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

/** Check typed or chosen text against the definition before sending it. The server stays authoritative. */
export function parseText(spec: ConfigKeySpec, text: string): ParseResult {
  const allowed = hasChoices(spec) ? spec.enum ?? null : null;
  switch (spec.type) {
    case "integer": {
      const trimmed = text.trim();
      if (!/^[+-]?\d+$/.test(trimmed)) return { ok: false, error: "Enter a whole number" };
      const value = Number(trimmed);
      if (!Number.isSafeInteger(value)) return { ok: false, error: "Enter a smaller whole number" };
      const outOfRange = rangeError(spec, value);
      if (outOfRange !== null) return { ok: false, error: outOfRange };
      if (allowed !== null && !allowed.includes(value)) return { ok: false, error: describeAllowed(allowed) };
      return { ok: true, value };
    }
    case "string":
      if (allowed !== null && !allowed.includes(text)) return { ok: false, error: describeAllowed(allowed) };
      return { ok: true, value: text };
    case "boolean":
      return { ok: true, value: text === "true" };
  }
}
