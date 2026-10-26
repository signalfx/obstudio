import type { FieldKind, FieldValue } from "../cloud/configEdits";

/** A setting's value type, as the definitions document names it in `type`. */
export type ValueType = "boolean" | "integer" | "string";

/** Whether a change takes effect while the observer runs or after a restart. */
export type Apply = "live" | "restart";

/** One definition, as GET /api/config/definitions serves it. */
export interface DefinitionNode {
  type: ValueType;
  title: string;
  description: string;
  default: FieldValue;
  enum?: FieldValue[];
  minimum?: number;
  maximum?: number;
  "x-obstudio-failSafe": FieldValue;
  "x-obstudio-apply": Apply;
}

/** One section: its properties are its definitions, by name. */
export interface SectionNode {
  type: "object";
  properties: Record<string, DefinitionNode>;
}

/** The GET /api/config/definitions document: its properties are the sections, by name. */
export interface DefinitionsDocument {
  type: "object";
  properties: Record<string, SectionNode>;
}

/** One setting, with the served field names and its dotted path. */
export interface ConfigDefinition
  extends Pick<DefinitionNode, "title" | "description">,
    Partial<Pick<DefinitionNode, "default" | "enum" | "minimum" | "maximum">> {
  /** `<section>.<name>`, such as telemetry.enabled. */
  path: string;
  type: ValueType;
  apply?: Apply;
}

export interface ConfigSection {
  name: string;
  title: string;
  definitions: ConfigDefinition[];
}

export type ParseResult =
  | { ok: true; value: FieldValue }
  | { ok: false; error: string };

/** A served shape whose values have not been checked yet. */
type Unchecked<T> = { [K in keyof T]?: unknown };

function isObject(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function isValueType(value: unknown): value is ValueType {
  return value === "boolean" || value === "integer" || value === "string";
}

function isFieldValue(value: unknown): value is FieldValue {
  return typeof value === "boolean" || typeof value === "number" || typeof value === "string";
}

function readDefinition(path: string, node: Unchecked<DefinitionNode>): ConfigDefinition | null {
  if (!isValueType(node.type) || typeof node.title !== "string" || typeof node.description !== "string") return null;
  const definition: ConfigDefinition = { description: node.description, path, title: node.title, type: node.type };
  if (isFieldValue(node.default)) definition.default = node.default;
  if (Array.isArray(node.enum) && node.enum.every(isFieldValue)) definition.enum = node.enum;
  if (typeof node.minimum === "number") definition.minimum = node.minimum;
  if (typeof node.maximum === "number") definition.maximum = node.maximum;
  // The one renamed field: x-obstudio-apply is read into apply here and nowhere else.
  const apply = node["x-obstudio-apply"];
  if (apply === "live" || apply === "restart") definition.apply = apply;
  return definition;
}

/**
 * Read the definitions document into sections, in the order the server lists
 * them. Settings of a type the tab has no control for, or without the served
 * title and description, are left out. Returns
 * null when the document does not have the served shape.
 */
export function parseDefinitions(document: unknown): ConfigSection[] | null {
  if (!isObject(document)) return null;
  const root: Unchecked<DefinitionsDocument> = document;
  if (!isObject(root.properties)) return null;
  const sections: ConfigSection[] = [];
  for (const [name, section] of Object.entries(root.properties)) {
    if (!isObject(section)) continue;
    const node: Unchecked<SectionNode> = section;
    if (!isObject(node.properties)) continue;
    const definitions: ConfigDefinition[] = [];
    for (const [leaf, definitionNode] of Object.entries(node.properties)) {
      const definition = isObject(definitionNode) ? readDefinition(`${name}.${leaf}`, definitionNode) : null;
      if (definition !== null) definitions.push(definition);
    }
    // TODO: use the section's own title once the definitions document serves one. Until then the heading is the section name.
    if (definitions.length > 0) sections.push({ definitions, name, title: name });
  }
  return sections;
}

/** One setting from a definitions document, by dotted path, or null when the document does not have it. */
export function findDefinition(document: unknown, path: string): ConfigDefinition | null {
  for (const section of parseDefinitions(document) ?? []) {
    const definition = section.definitions.find((candidate) => candidate.path === path);
    if (definition !== undefined) return definition;
  }
  return null;
}

/** Discrete controls send at once; typed ones wait for the debounce. */
export function fieldKind(definition: ConfigDefinition): FieldKind {
  return definition.type === "boolean" || hasChoices(definition) ? "immediate" : "debounced";
}

export function hasChoices(definition: ConfigDefinition): boolean {
  return definition.type !== "boolean" && definition.enum !== undefined && definition.enum.length > 0;
}

/** The configEdits fields for every setting in the sections. */
export function editFields(sections: readonly ConfigSection[]): Record<string, FieldKind> {
  const fields: Record<string, FieldKind> = {};
  for (const section of sections) {
    for (const definition of section.definitions) fields[definition.path] = fieldKind(definition);
  }
  return fields;
}

/** How a value is shown in a text field or select. */
export function toText(value: FieldValue | undefined): string {
  return value === undefined ? "" : String(value);
}

function describeAllowed(values: readonly FieldValue[]): string {
  return `Must be one of: ${values.join(", ")}`;
}

function rangeError(definition: ConfigDefinition, value: number): string | null {
  const { minimum, maximum } = definition;
  if (minimum !== undefined && maximum !== undefined && (value < minimum || value > maximum)) {
    return `Must be a whole number between ${minimum} and ${maximum}`;
  }
  if (minimum !== undefined && value < minimum) return `Must be at least ${minimum}`;
  if (maximum !== undefined && value > maximum) return `Must be at most ${maximum}`;
  return null;
}

/** Check typed or chosen text against the definition before sending it. The server stays authoritative. */
export function parseText(definition: ConfigDefinition, text: string): ParseResult {
  const allowed = hasChoices(definition) ? definition.enum ?? null : null;
  switch (definition.type) {
    case "integer": {
      const trimmed = text.trim();
      if (!/^[+-]?\d+$/.test(trimmed)) return { ok: false, error: "Enter a whole number" };
      const value = Number(trimmed);
      if (!Number.isSafeInteger(value)) return { ok: false, error: "Enter a smaller whole number" };
      const outOfRange = rangeError(definition, value);
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
