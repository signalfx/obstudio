import * as assert from 'node:assert/strict';
import * as fs from 'node:fs';
import * as os from 'node:os';
import * as path from 'node:path';
import test from 'node:test';
import {
	CONFIG_WARNING_FINGERPRINT_KEY,
	ConfigWarningController,
	OPEN_CONFIG_ACTION,
	isLoopbackObserverUrl,
	type ConfigDocumentSelection,
	type ConfigStatusResponse,
} from '../config-warning';

const base = 'http://127.0.0.1:17900';
const homeConfigPath = path.join(os.homedir(), '.obstudio', 'config.yaml');

type StatusBody = {
	diagnostics: Array<{ key: string; kind: string; line: number; message?: string }>;
	fingerprint: string;
	message: string;
	path: string;
	warn: boolean;
};

function statusBody(overrides: Partial<StatusBody>): StatusBody {
	return {
		diagnostics: [],
		fingerprint: '',
		message: '',
		path: homeConfigPath,
		warn: false,
		...overrides,
	};
}

const W1 = statusBody({
	diagnostics: [{ key: 'telemetry.enabled', kind: 'invalid', line: 11 }],
	fingerprint: 'f1',
	message: 'Using fail-safe settings for telemetry.enabled (false): one',
	warn: true,
});
const W2 = statusBody({
	diagnostics: [{ key: 'telemetry', kind: 'invalid', line: 10 }],
	fingerprint: 'f2',
	message: 'Using fail-safe settings for telemetry.enabled (false): two',
	warn: true,
});
const OK = statusBody({});

function ok(body: unknown): ConfigStatusResponse {
	return { body: JSON.stringify(body), status: 200 };
}

type Deferred<T> = { promise: Promise<T>; reject(error: unknown): void; resolve(value: T): void };

function deferred<T>(): Deferred<T> {
	let resolve!: (value: T) => void;
	let reject!: (error: unknown) => void;
	const promise = new Promise<T>((res, rej) => {
		resolve = res;
		reject = rej;
	});
	return { promise, reject, resolve };
}

type Call =
	| { kind: 'update'; key: string; value: unknown }
	| { kind: 'show'; action: string; message: string };

class Harness {
	readonly calls: Call[] = [];
	readonly fetches: string[] = [];
	readonly opened: Array<{ filePath: string; opts: { selection?: ConfigDocumentSelection } }> = [];
	readonly store = new Map<string, unknown>();
	readonly watchers: Array<{ dir: string; disposed: boolean; listeners: Array<() => void> }> = [];
	baseUrl: string | undefined = base;
	focused = true;
	now = 0;
	responses: Array<() => Promise<ConfigStatusResponse>> = [];
	showResult: () => Thenable<string | undefined> = () => Promise.resolve(undefined);
	openResult: () => Thenable<unknown> = () => Promise.resolve(undefined);
	private nextTimer = 1;
	private readonly timers = new Map<number, { at: number; callback: () => void }>();
	readonly controller: ConfigWarningController;

	constructor(initialFingerprint?: string) {
		if (initialFingerprint !== undefined) {
			this.store.set(CONFIG_WARNING_FINGERPRINT_KEY, initialFingerprint);
		}
		this.controller = new ConfigWarningController({
			clearTimeout: (handle) => {
				this.timers.delete(handle as number);
			},
			createWatcher: (dir) => {
				const watcher = { dir, disposed: false, listeners: [] as Array<() => void> };
				this.watchers.push(watcher);
				return {
					dispose: () => {
						watcher.disposed = true;
					},
					onEvent: (listener) => {
						watcher.listeners.push(listener);
					},
				};
			},
			currentBaseUrl: () => this.baseUrl,
			fetchStatus: (url) => {
				this.fetches.push(url);
				const next = this.responses.shift();
				assert.ok(next, 'unexpected fetchStatus call');
				return next();
			},
			isFocused: () => this.focused,
			memento: {
				get: <T>(key: string) => this.store.get(key) as T | undefined,
				update: (key: string, value: unknown) => {
					this.calls.push({ key, kind: 'update', value });
					// The write lands a turn later, so an unserialized second
					// evaluation would still read the old fingerprint.
					return new Promise<void>((resolve) => setImmediate(() => {
						if (value === undefined) {
							this.store.delete(key);
						} else {
							this.store.set(key, value);
						}
						resolve();
					}));
				},
			} as ConstructorParameters<typeof ConfigWarningController>[0]['memento'],
			openDocument: (filePath, opts) => {
				this.opened.push({ filePath, opts });
				return this.openResult();
			},
			setTimeout: (callback, ms) => {
				const id = this.nextTimer++;
				this.timers.set(id, { at: this.now + ms, callback });
				return id;
			},
			showWarning: (message, action) => {
				this.calls.push({ action, kind: 'show', message });
				return this.showResult();
			},
		});
	}

	respond(...bodies: Array<ConfigStatusResponse | (() => Promise<ConfigStatusResponse>)>): void {
		for (const body of bodies) {
			this.responses.push(typeof body === 'function' ? body : () => Promise.resolve(body));
		}
	}

	get toasts(): Array<{ message: string }> {
		return this.calls.filter((call): call is Extract<Call, { kind: 'show' }> => call.kind === 'show');
	}

	get watcher() {
		return this.watchers[this.watchers.length - 1];
	}

	fireWatcher(): void {
		for (const listener of this.watcher.listeners) {
			listener();
		}
	}

	advance(ms: number): void {
		this.now += ms;
		for (const [id, timer] of [...this.timers].sort((a, b) => a[1].at - b[1].at)) {
			if (timer.at <= this.now) {
				this.timers.delete(id);
				timer.callback();
			}
		}
	}

	async watcherEventAndDebounce(): Promise<void> {
		this.fireWatcher();
		this.advance(500);
		await settle();
	}
}

async function settle(): Promise<void> {
	for (let i = 0; i < 10; i++) {
		await new Promise<void>((resolve) => setImmediate(resolve));
	}
}

test('toast-on-new-fingerprint: one request, fingerprint stored before the toast', async () => {
	const h = new Harness();
	h.respond(ok(W1));
	h.controller.onObserverRunning();
	await settle();

	assert.deepEqual(h.fetches, [base]);
	assert.deepEqual(h.calls, [
		{ key: CONFIG_WARNING_FINGERPRINT_KEY, kind: 'update', value: 'f1' },
		{ action: OPEN_CONFIG_ACTION, kind: 'show', message: W1.message },
	]);
	assert.equal(h.toasts.length, 1);
});

test('toast-dedupe: a stored fingerprint is not shown again, a new one is', async () => {
	const h = new Harness('f1');
	h.respond(ok(W1), ok(W1), ok(W2));
	h.controller.onObserverRunning();
	await settle();
	await h.watcherEventAndDebounce();
	assert.equal(h.toasts.length, 0, 'no toast for a repeated fingerprint');

	await h.watcherEventAndDebounce();
	assert.deepEqual(h.toasts.map((toast) => toast.message), [W2.message]);
	assert.equal(h.store.get(CONFIG_WARNING_FINGERPRINT_KEY), 'f2');
});

test('toast-rearm-after-ok: an ok status clears the fingerprint so the same breakage toasts again', async () => {
	const h = new Harness('f1');
	h.respond(ok(OK), ok(W1));
	h.controller.onObserverRunning();
	await settle();
	assert.equal(h.store.get(CONFIG_WARNING_FINGERPRINT_KEY), undefined);
	assert.equal(h.toasts.length, 0);

	h.controller.onObserverRunning();
	await settle();
	assert.equal(h.toasts.length, 1);
});

test('toast-pending-focus: an unfocused warning waits for focus and re-fetches', async () => {
	const h = new Harness();
	h.focused = false;
	h.respond(ok(W1));
	h.controller.onObserverRunning();
	await settle();
	assert.equal(h.toasts.length, 0, 'deferred while unfocused');
	assert.equal(h.calls.length, 0, 'no memento write while unfocused');

	h.focused = true;
	h.respond(ok(W1));
	h.controller.onWindowFocusChanged(true);
	await settle();
	assert.equal(h.fetches.length, 2, 'focus re-fetches');
	assert.equal(h.toasts.length, 1);

	h.controller.onWindowFocusChanged(true);
	await settle();
	assert.equal(h.fetches.length, 2, 'nothing pending, no request');
});

test('toast-pending-focus: fixed while unfocused shows nothing and clears the fingerprint', async () => {
	const h = new Harness('f0');
	h.focused = false;
	h.respond(ok(W1));
	h.controller.onObserverRunning();
	await settle();

	h.focused = true;
	h.respond(ok(OK));
	h.controller.onWindowFocusChanged(true);
	await settle();
	assert.equal(h.toasts.length, 0);
	assert.equal(h.store.get(CONFIG_WARNING_FINGERPRINT_KEY), undefined);

	h.controller.onWindowFocusChanged(true);
	await settle();
	assert.equal(h.fetches.length, 2, 'the ok response cleared pending');
});

test('toast-pending-focus: focus with nothing pending makes no request', async () => {
	const h = new Harness();
	h.controller.onWindowFocusChanged(true);
	await settle();
	assert.equal(h.fetches.length, 0);
});

test('watcher-debounce: one request 500 ms after the last of a burst of events', async () => {
	const h = new Harness();
	assert.equal(h.watchers.length, 1);
	assert.equal(h.watcher.dir, path.join(os.homedir(), '.obstudio'), 'initial watcher dir');

	h.respond(ok(statusBody({ path: '/x/.obstudio/config.yaml' })));
	for (let i = 0; i < 5; i++) {
		h.fireWatcher();
		h.advance(100);
	}
	h.advance(399);
	await settle();
	assert.equal(h.fetches.length, 0, 'none at 499 ms');

	h.advance(1);
	await settle();
	assert.equal(h.fetches.length, 1, 'one at 500 ms');

	assert.equal(h.watchers.length, 2);
	assert.equal(h.watchers[0].disposed, true, 'old watcher disposed on retarget');
	assert.equal(h.watchers[1].dir, '/x/.obstudio');
	assert.equal(h.watchers[1].disposed, false);
});

test('serialized-evaluation: two in-flight responses with the same new fingerprint toast once', async () => {
	const h = new Harness();
	const first = deferred<ConfigStatusResponse>();
	const second = deferred<ConfigStatusResponse>();
	h.respond(() => first.promise, () => second.promise);
	h.controller.onObserverRunning();
	h.controller.onObserverRunning();
	first.resolve(ok(W1));
	second.resolve(ok(W1));
	await settle();
	assert.equal(h.fetches.length, 2);
	assert.equal(h.toasts.length, 1);
});

test('action-opens-line: the action opens the file at the first invalid line', async () => {
	const h = new Harness();
	h.showResult = () => Promise.resolve(OPEN_CONFIG_ACTION);
	h.respond(ok({
		...W1,
		diagnostics: [
			{ key: 'zz', kind: 'unknown_key', line: 3 },
			{ key: 'telemetry.enabled', kind: 'absent', line: 0 },
			{ key: 'telemetry.enabled', kind: 'invalid', line: 7 },
		],
	}));
	h.controller.onObserverRunning();
	await settle();
	assert.deepEqual(h.opened, [{ filePath: W1.path, opts: { selection: { character: 0, line: 6 } } }]);
});

test('action-opens-line: an unparseable status opens the file with no selection', async () => {
	const h = new Harness();
	h.showResult = () => Promise.resolve(OPEN_CONFIG_ACTION);
	h.respond(ok({ ...W1, diagnostics: [] }));
	h.controller.onObserverRunning();
	await settle();
	assert.deepEqual(h.opened, [{ filePath: W1.path, opts: {} }]);
});

test('action-opens-line: dismissing the toast opens nothing', async () => {
	const h = new Harness();
	h.respond(ok(W1));
	h.controller.onObserverRunning();
	await settle();
	assert.equal(h.toasts.length, 1);
	assert.equal(h.opened.length, 0);
});

test('action-opens-line: a rejected open is caught', async () => {
	const unhandled: unknown[] = [];
	const onUnhandled = (reason: unknown) => unhandled.push(reason);
	process.on('unhandledRejection', onUnhandled);
	try {
		const h = new Harness();
		h.showResult = () => Promise.resolve(OPEN_CONFIG_ACTION);
		h.openResult = () => Promise.reject(new Error('file deleted'));
		h.respond(ok(W1));
		h.controller.onObserverRunning();
		await settle();
		assert.equal(h.opened.length, 1);
		assert.deepEqual(unhandled, []);
	} finally {
		process.off('unhandledRejection', onUnhandled);
	}
});

test('scope-guard: loopback URLs only', () => {
	for (const url of ['http://127.0.0.1:17900', 'http://localhost:17900', 'http://127.8.9.10:1', 'http://[::1]:17900']) {
		assert.equal(isLoopbackObserverUrl(url), true, url);
	}
	for (const url of ['http://10.0.0.5:17900', 'https://observer.example.com', 'http://0.0.0.0:17900', 'not a url']) {
		assert.equal(isLoopbackObserverUrl(url), false, url);
	}
});

test('scope-guard: a remote observer gets no request and no toast', async () => {
	const h = new Harness();
	h.baseUrl = 'https://observer.example.com';
	h.controller.onObserverRunning();
	await settle();
	assert.equal(h.fetches.length, 0);
	assert.equal(h.toasts.length, 0);
});

test('scope-guard: no request while the observer is not running', async () => {
	const h = new Harness();
	h.baseUrl = undefined;
	await h.watcherEventAndDebounce();
	assert.equal(h.fetches.length, 0);
});

test('fetch-failure-noop: failures and unusable bodies change nothing', async () => {
	const h = new Harness('f1');
	h.focused = false;
	h.respond(ok(W2));
	h.controller.onObserverRunning();
	await settle();

	h.focused = true;
	const failures: Array<() => Promise<ConfigStatusResponse>> = [
		() => Promise.reject(new Error('connection refused')),
		// A well-formed ok body on a non-200 must still be ignored.
		() => Promise.resolve({ body: JSON.stringify(OK), status: 404 }),
		() => Promise.resolve({ body: '<!doctype html><html><body><div id="root"></div></body></html>', status: 200 }),
		() => Promise.resolve(ok({ foo: 1 })),
	];
	for (const failure of failures) {
		h.respond(failure);
		// Focus re-fetches only while pending, so each request here also proves pending survived.
		h.controller.onWindowFocusChanged(true);
		await settle();
		assert.equal(h.store.get(CONFIG_WARNING_FINGERPRINT_KEY), 'f1');
		assert.equal(h.toasts.length, 0);
	}
	assert.equal(h.fetches.length, 1 + failures.length);
	assert.equal(h.calls.length, 0);
});

test('dispose: stops the watcher and cancels an armed debounce', async () => {
	const h = new Harness();
	h.fireWatcher();
	h.controller.dispose();
	h.advance(1000);
	await settle();
	assert.equal(h.watcher.disposed, true);
	assert.equal(h.fetches.length, 0);
});

function localImports(file: string): string[] {
	const source = fs.readFileSync(file, 'utf8');
	return [...source.matchAll(/^\s*import\s[^;]*?from\s+'([^']+)'/gm)].map((match) => match[1]);
}

test('privacy-imports: the config warning never reaches the telemetry module', () => {
	const srcDir = path.resolve(__dirname, '..', '..', 'src');
	const seen = new Set<string>();
	const queue = [path.join(srcDir, 'config-warning.ts')];
	while (queue.length > 0) {
		const file = queue.pop() as string;
		if (seen.has(file)) {
			continue;
		}
		seen.add(file);
		for (const specifier of localImports(file)) {
			assert.notEqual(specifier, './observer-webview-telemetry', `${path.basename(file)} imports telemetry`);
			if (specifier.startsWith('./')) {
				queue.push(path.join(path.dirname(file), `${specifier}.ts`));
			}
		}
	}
	assert.ok(seen.has(path.join(srcDir, 'backend.ts')), 'import scan followed local imports');
	assert.doesNotMatch(fs.readFileSync(path.join(srcDir, 'config-warning.ts'), 'utf8'), /[Tt]elemetry\w*\s*\(/);
});
