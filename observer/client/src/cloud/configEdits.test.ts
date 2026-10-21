import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createConfigEdits, type ConfigEdits, type ConfigEditsState } from "./configEdits";

interface Deferred {
  promise: Promise<Response>;
  resolve(response: Response): void;
  reject(error: unknown): void;
}

function deferred(): Deferred {
  let resolve!: (response: Response) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<Response>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

// A minimal Response stand-in whose body resolves in one microtask, so tests
// stay in step with fake timers.
function json(status: number, body: unknown): Response {
  return { ok: status >= 200 && status < 300, status, json: async () => body } as unknown as Response;
}

const S0 = { t: { flag: false, n: 1, s: "a" } };

interface Harness {
  edits: ConfigEdits;
  gets: Deferred[];
  posts: { body: string; reply: Deferred }[];
  changes: ConfigEditsState[];
  state(): ConfigEditsState;
}

async function flush(): Promise<void> {
  for (let i = 0; i < 10; i++) await Promise.resolve();
}

async function setup(): Promise<Harness> {
  const gets: Deferred[] = [];
  const posts: { body: string; reply: Deferred }[] = [];
  const changes: ConfigEditsState[] = [];
  const edits = createConfigEdits(
    { "t.flag": "immediate", "t.n": "debounced", "t.s": "debounced" },
    {
      fetchConfig: () => {
        const d = deferred();
        gets.push(d);
        return d.promise;
      },
      postConfig: (body) => {
        const d = deferred();
        posts.push({ body, reply: d });
        return d.promise;
      },
      onChange: (state) => changes.push(state),
    },
  );
  edits.refresh();
  gets[0].resolve(json(200, S0));
  await flush();
  return { edits, gets, posts, changes, state: () => edits.getState() };
}

async function at(ms: number, now: { t: number }): Promise<void> {
  await vi.advanceTimersByTimeAsync(ms - now.t);
  now.t = ms;
}

describe("configEdits", () => {
  let now: { t: number };
  beforeEach(() => {
    vi.useFakeTimers();
    now = { t: 0 };
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("starts from the server state", async () => {
    const h = await setup();
    expect(h.state().values).toEqual({ "t.flag": false, "t.n": 1, "t.s": "a" });
    expect(h.state().server).toEqual({ "t.flag": false, "t.n": 1, "t.s": "a" });
  });

  it("sends a boolean edit at once without optimistic display", async () => {
    const h = await setup();
    h.edits.edit("t.flag", true);
    expect(h.posts).toHaveLength(1);
    expect(h.posts[0].body).toBe('{"t":{"flag":true}}');
    expect(h.state().values["t.flag"]).toBe(false);
    expect(h.state().inFlight.has("t.flag")).toBe(true);
    h.edits.edit("t.flag", false);
    expect(h.posts).toHaveLength(1);
    h.posts[0].reply.resolve(json(200, { t: { flag: true, n: 1, s: "a" } }));
    await flush();
    expect(h.state().values["t.flag"]).toBe(true);
    expect(h.state().inFlight.size).toBe(0);
  });

  it("coalesces debounced edits into one send after the last edit", async () => {
    const h = await setup();
    h.edits.edit("t.n", 2);
    await at(200, now);
    h.edits.edit("t.n", 3);
    await at(400, now);
    h.edits.edit("t.s", "b");
    expect(h.state().values["t.n"]).toBe(3);
    expect(h.state().values["t.s"]).toBe("b");
    await at(899, now);
    expect(h.posts).toHaveLength(0);
    await at(900, now);
    expect(h.posts.map((p) => p.body)).toEqual(['{"t":{"n":3,"s":"b"}}']);
    await at(5000, now);
    expect(h.posts).toHaveLength(1);
  });

  it("sends only the dirty fields", async () => {
    const h = await setup();
    h.edits.edit("t.s", "b");
    await at(500, now);
    expect(h.posts[0].body).toBe('{"t":{"s":"b"}}');
    h.posts[0].reply.resolve(json(200, { t: { flag: false, n: 1, s: "b" } }));
    await flush();
    h.edits.edit("t.n", 7);
    await at(1000, now);
    expect(h.posts[1].body).toBe('{"t":{"n":7}}');
  });

  it("flushes pending debounced edits with an immediate send", async () => {
    const h = await setup();
    h.edits.edit("t.n", 2);
    await at(100, now);
    h.edits.edit("t.flag", true);
    expect(h.posts.map((p) => p.body)).toEqual(['{"t":{"n":2,"flag":true}}']);
    await at(5000, now);
    expect(h.posts).toHaveLength(1);
  });

  it("keeps a field edited during its send dirty and shows its local value meanwhile", async () => {
    const h = await setup();
    h.edits.edit("t.n", 2);
    await at(500, now);
    expect(h.posts[0].body).toBe('{"t":{"n":2}}');
    await at(550, now);
    expect(h.state().values["t.n"]).toBe(2);
    expect(h.state().inFlight.has("t.n")).toBe(true);
    await at(600, now);
    h.edits.edit("t.n", 5);
    await at(700, now);
    h.posts[0].reply.resolve(json(200, { t: { flag: false, n: 2, s: "a" } }));
    await flush();
    expect(h.state().values["t.n"]).toBe(5);
    await at(1100, now);
    expect(h.posts[1].body).toBe('{"t":{"n":5}}');
  });

  it("keeps a pending edit across a refresh", async () => {
    const h = await setup();
    h.edits.edit("t.n", 2);
    await at(100, now);
    h.edits.refresh();
    h.gets[1].resolve(json(200, { t: { flag: true, n: 9, s: "z" } }));
    await flush();
    expect(h.state().values["t.flag"]).toBe(true);
    expect(h.state().values["t.s"]).toBe("z");
    expect(h.state().values["t.n"]).toBe(2);
    await at(500, now);
    expect(h.posts[0].body).toBe('{"t":{"n":2}}');
  });

  it("shows the server's answer and applies only the latest request", async () => {
    const a = await setup();
    a.edits.edit("t.s", "b");
    await at(500, now);
    a.posts[0].reply.resolve(json(200, { t: { flag: true, n: 1, s: "B" } }));
    await flush();
    expect(a.state().values["t.s"]).toBe("B");
    expect(a.state().values["t.flag"]).toBe(true);

    now = { t: 0 };
    vi.setSystemTime(0);
    const b = await setup();
    b.edits.edit("t.s", "c");
    await vi.advanceTimersByTimeAsync(500);
    await vi.advanceTimersByTimeAsync(100);
    b.edits.refresh();
    b.gets[1].resolve(json(200, { t: { flag: false, n: 1, s: "g" } }));
    await flush();
    b.posts[0].reply.resolve(json(200, { t: { flag: false, n: 1, s: "c" } }));
    await flush();
    expect(b.state().values["t.s"]).toBe("g");
    expect(b.state().inFlight.size).toBe(0);
  });

  it("reports a failed send and reverts fields that were not edited again", async () => {
    const h = await setup();
    h.edits.edit("t.s", "b");
    h.edits.edit("t.n", 2);
    await at(500, now);
    await at(600, now);
    h.edits.edit("t.n", 3);
    const message = 'userconfig: invalid value: t.s: "b" is not one of "a"';
    h.posts[0].reply.resolve(json(400, { error: message }));
    await flush();
    expect(h.state().error).toEqual({ message, status: 400 });
    expect(h.gets).toHaveLength(2);
    h.gets[1].resolve(json(200, S0));
    await flush();
    expect(h.state().values["t.s"]).toBe("a");
    expect(h.state().values["t.n"]).toBe(3);
    await at(1100, now);
    expect(h.posts[1].body).toBe('{"t":{"n":3}}');
    h.posts[1].reply.resolve(json(200, { t: { flag: false, n: 3, s: "a" } }));
    await flush();
    expect(h.state().error).toBeNull();
  });

  it("reports a transport failure without a message or status", async () => {
    const h = await setup();
    h.edits.edit("t.flag", true);
    h.posts[0].reply.reject(new Error("offline"));
    await flush();
    expect(h.state().error).toEqual({ message: undefined, status: undefined });
    expect(h.gets).toHaveLength(2);
  });

  it("flushes a pending edit on dispose and goes silent", async () => {
    const h = await setup();
    h.edits.edit("t.n", 2);
    await at(100, now);
    const before = h.changes.length;
    h.edits.dispose();
    expect(h.posts.map((p) => p.body)).toEqual(['{"t":{"n":2}}']);
    await at(200, now);
    h.posts[0].reply.resolve(json(200, { t: { flag: false, n: 2, s: "a" } }));
    await flush();
    await at(5000, now);
    expect(h.posts).toHaveLength(1);
    expect(h.changes.length).toBe(before);
  });

  it("does not depend on React, the host transport, or components", () => {
    const source = readFileSync(fileURLToPath(new URL("./configEdits.ts", import.meta.url)), "utf8");
    const imports = [...source.matchAll(/from\s+["']([^"']+)["']/g)].map((m) => m[1]);
    for (const spec of imports) {
      expect(spec).not.toMatch(/^react|host\/transport|\.tsx$/);
    }
  });
});
