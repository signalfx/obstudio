/** How long debounced fields wait after the last edit before they are sent. */
export const DEBOUNCE_MS = 500;

export type FieldValue = boolean | number | string;
export type FieldKind = "immediate" | "debounced";

export interface ConfigEditsDeps {
  /** GET /api/config. */
  fetchConfig(): Promise<Response>;
  /** POST /api/config with a merge body. */
  postConfig(body: string): Promise<Response>;
  onChange(state: ConfigEditsState): void;
}

export interface ConfigEditsState {
  /** What each field displays. */
  values: Readonly<Record<string, FieldValue>>;
  /** The last applied server state, or null before the first one. */
  server: Readonly<Record<string, FieldValue>> | null;
  /** Paths carried by a send that has not settled. */
  inFlight: ReadonlySet<string>;
  error: { message?: string; status?: number } | null;
  loadFailed: boolean;
}

export interface ConfigEdits {
  edit(path: string, value: FieldValue): void;
  refresh(): void;
  dispose(): void;
  getState(): ConfigEditsState;
}

function isFieldValue(value: unknown): value is FieldValue {
  return typeof value === "boolean" || typeof value === "number" || typeof value === "string";
}

function flatten(body: unknown, paths: readonly string[]): Record<string, FieldValue> {
  const out: Record<string, FieldValue> = {};
  for (const path of paths) {
    let node: unknown = body;
    for (const segment of path.split(".")) {
      node = node !== null && typeof node === "object" ? (node as Record<string, unknown>)[segment] : undefined;
    }
    if (isFieldValue(node)) out[path] = node;
  }
  return out;
}

function nest(entries: ReadonlyMap<string, FieldValue>): Record<string, unknown> {
  const root: Record<string, unknown> = {};
  for (const [path, value] of entries) {
    const segments = path.split(".");
    let node = root;
    for (const segment of segments.slice(0, -1)) {
      if (node[segment] === undefined || typeof node[segment] !== "object") node[segment] = {};
      node = node[segment] as Record<string, unknown>;
    }
    node[segments[segments.length - 1]] = value;
  }
  return root;
}

async function errorMessage(response: Response): Promise<string | undefined> {
  try {
    const body: unknown = await response.json();
    const message = body !== null && typeof body === "object" ? (body as { error?: unknown }).error : undefined;
    return typeof message === "string" && message !== "" ? message : undefined;
  } catch {
    return undefined;
  }
}

/**
 * Tracks edits to config fields and sends them to the observer. Immediate
 * fields are sent at once and display only the server value; debounced
 * fields display their local value until the server state that follows their
 * send is applied. Only the newest request's response is applied.
 */
export function createConfigEdits(
  fields: Readonly<Record<string, FieldKind>>,
  deps: ConfigEditsDeps,
): ConfigEdits {
  const paths = Object.keys(fields);
  let server: Record<string, FieldValue> | null = null;
  const local = new Map<string, FieldValue>();
  const dirty = new Map<string, FieldValue>();
  const inFlight = new Map<string, number>();
  let error: ConfigEditsState["error"] = null;
  let loadFailed = false;
  let latest = 0;
  let timer: ReturnType<typeof setTimeout> | undefined;
  let disposed = false;

  function holdsLocal(path: string): boolean {
    return fields[path] === "debounced" && (dirty.has(path) || inFlight.has(path));
  }

  function getState(): ConfigEditsState {
    const values: Record<string, FieldValue> = {};
    for (const path of paths) {
      const value = holdsLocal(path) ? local.get(path) : server?.[path];
      if (value !== undefined) values[path] = value;
    }
    return { values, server, inFlight: new Set(inFlight.keys()), error, loadFailed };
  }

  function emit(): void {
    if (!disposed) deps.onChange(getState());
  }

  function settle(sent: readonly string[]): void {
    for (const path of sent) {
      const n = (inFlight.get(path) ?? 1) - 1;
      if (n > 0) inFlight.set(path, n);
      else inFlight.delete(path);
    }
  }

  function applyServer(body: unknown): void {
    server = flatten(body, paths);
    for (const path of paths) {
      if (!holdsLocal(path)) local.delete(path);
    }
  }

  function send(): void {
    if (timer !== undefined) {
      clearTimeout(timer);
      timer = undefined;
    }
    if (dirty.size === 0) return;
    const sent = [...dirty.keys()];
    const body = JSON.stringify(nest(dirty));
    dirty.clear();
    for (const path of sent) inFlight.set(path, (inFlight.get(path) ?? 0) + 1);
    const id = ++latest;
    emit();

    const fail = (message: string | undefined, status: number | undefined): void => {
      if (disposed) return;
      settle(sent);
      error = { message, status };
      emit();
      refresh();
    };
    deps.postConfig(body).then(async (response) => {
      if (disposed) return;
      if (!response.ok) {
        fail(await errorMessage(response), response.status);
        return;
      }
      let parsed: unknown;
      try {
        parsed = await response.json();
      } catch {
        fail(undefined, response.status);
        return;
      }
      if (disposed) return;
      settle(sent);
      if (id === latest) {
        applyServer(parsed);
        error = null;
      }
      emit();
    }, () => fail(undefined, undefined));
  }

  function refresh(): void {
    if (disposed) return;
    const id = ++latest;
    const failed = (): void => {
      if (disposed || id !== latest) return;
      loadFailed = true;
      emit();
    };
    deps.fetchConfig().then(async (response) => {
      if (disposed || id !== latest) return;
      if (!response.ok) {
        failed();
        return;
      }
      let parsed: unknown;
      try {
        parsed = await response.json();
      } catch {
        failed();
        return;
      }
      if (disposed || id !== latest) return;
      applyServer(parsed);
      loadFailed = false;
      emit();
    }, failed);
  }

  function edit(path: string, value: FieldValue): void {
    if (disposed || fields[path] === undefined) return;
    if (fields[path] === "immediate") {
      if (inFlight.has(path)) return;
      dirty.set(path, value);
      send();
      return;
    }
    local.set(path, value);
    dirty.set(path, value);
    if (timer !== undefined) clearTimeout(timer);
    timer = setTimeout(send, DEBOUNCE_MS);
    emit();
  }

  function dispose(): void {
    if (disposed) return;
    disposed = true;
    if (timer !== undefined) {
      clearTimeout(timer);
      timer = undefined;
    }
    // Flush rather than drop an edit the user already made.
    send();
  }

  return { edit, refresh, dispose, getState };
}
