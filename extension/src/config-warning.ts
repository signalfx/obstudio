import * as os from 'node:os';
import * as path from 'node:path';
import type * as vscode from 'vscode';
import { isLoopbackObserverHost } from './backend';

export const CONFIG_WARNING_FINGERPRINT_KEY = 'obstudio.configWarning.fingerprint';
export const CONFIG_WATCH_DEBOUNCE_MS = 500;
export const OPEN_CONFIG_ACTION = 'Open config.yaml';

export type ConfigStatusResponse = {
	body: string;
	status: number;
};

export type ConfigWatcher = {
	dispose(): void;
	onEvent(listener: () => void): void;
};

export type ConfigDocumentSelection = {
	character: number;
	line: number;
};

export type ConfigWarningDeps = {
	clearTimeout(handle: unknown): void;
	createWatcher(dir: string): ConfigWatcher;
	currentBaseUrl(): string | undefined;
	fetchStatus(baseUrl: string): Promise<ConfigStatusResponse>;
	isFocused(): boolean;
	memento: Pick<vscode.Memento, 'get' | 'update'>;
	openDocument(filePath: string, opts: { selection?: ConfigDocumentSelection }): Thenable<unknown>;
	setTimeout(callback: () => void, ms: number): unknown;
	showWarning(message: string, action: string): Thenable<string | undefined>;
};

type ConfigStatusDiagnostic = {
	kind: string;
	line: number;
};

type ConfigStatus = {
	diagnostics: ConfigStatusDiagnostic[];
	fingerprint: string;
	message: string;
	path: string;
	warn: boolean;
};

export function defaultConfigPath(): string {
	return path.join(os.homedir(), '.obstudio', 'config.yaml');
}

export function isLoopbackObserverUrl(url: string): boolean {
	let parsed: URL;
	try {
		parsed = new URL(url);
	} catch {
		return false;
	}
	return isLoopbackObserverHost(parsed.hostname);
}

// An older observer answers 404, 405 or its SPA page here; anything that is not a
// well-formed status must leave the stored fingerprint alone.
function parseUsableStatus(response: ConfigStatusResponse): ConfigStatus | undefined {
	if (response.status !== 200) {
		return undefined;
	}
	let value: unknown;
	try {
		value = JSON.parse(response.body);
	} catch {
		return undefined;
	}
	if (typeof value !== 'object' || value === null) {
		return undefined;
	}
	const record = value as Record<string, unknown>;
	if (typeof record.warn !== 'boolean'
		|| typeof record.fingerprint !== 'string'
		|| typeof record.message !== 'string'
		|| typeof record.path !== 'string'
		|| !Array.isArray(record.diagnostics)) {
		return undefined;
	}
	const diagnostics = record.diagnostics.flatMap((entry: unknown): ConfigStatusDiagnostic[] => {
		if (typeof entry !== 'object' || entry === null) {
			return [];
		}
		const { kind, line } = entry as Record<string, unknown>;
		return typeof kind === 'string' && typeof line === 'number' ? [{ kind, line }] : [];
	});
	return {
		diagnostics,
		fingerprint: record.fingerprint,
		message: record.message,
		path: record.path,
		warn: record.warn,
	};
}

export class ConfigWarningController implements vscode.Disposable {
	private configPath = defaultConfigPath();
	private debounceHandle: unknown;
	private disposed = false;
	private evaluation: Promise<void> = Promise.resolve();
	private pending = false;
	private watcher: ConfigWatcher | undefined;

	constructor(private readonly deps: ConfigWarningDeps) {
		this.watch(path.dirname(this.configPath));
	}

	onObserverRunning(): void {
		this.request();
	}

	onWindowFocusChanged(focused: boolean): void {
		// Re-fetch rather than replay: the file may have been fixed while unfocused.
		if (focused && this.pending) {
			this.request();
		}
	}

	dispose(): void {
		this.disposed = true;
		this.clearDebounce();
		this.watcher?.dispose();
		this.watcher = undefined;
	}

	private watch(dir: string): void {
		const watcher = this.deps.createWatcher(dir);
		watcher.onEvent(() => this.onWatcherEvent());
		this.watcher = watcher;
	}

	private onWatcherEvent(): void {
		if (this.disposed) {
			return;
		}
		this.clearDebounce();
		this.debounceHandle = this.deps.setTimeout(() => {
			this.debounceHandle = undefined;
			this.request();
		}, CONFIG_WATCH_DEBOUNCE_MS);
	}

	private clearDebounce(): void {
		if (this.debounceHandle !== undefined) {
			this.deps.clearTimeout(this.debounceHandle);
			this.debounceHandle = undefined;
		}
	}

	private request(): void {
		if (this.disposed) {
			return;
		}
		const baseUrl = this.deps.currentBaseUrl();
		if (baseUrl === undefined || !isLoopbackObserverUrl(baseUrl)) {
			return;
		}
		let response: Promise<ConfigStatusResponse>;
		try {
			response = this.deps.fetchStatus(baseUrl);
		} catch {
			return;
		}
		void response.then(parseUsableStatus, () => undefined).then((status) => {
			if (status === undefined) {
				return;
			}
			// One chain, appended in completion order, so two in-flight responses
			// cannot both read the old fingerprint and both toast.
			this.evaluation = this.evaluation
				.then(() => this.evaluate(status))
				.catch(() => undefined);
		});
	}

	private async evaluate(status: ConfigStatus): Promise<void> {
		if (this.disposed) {
			return;
		}
		if (status.path !== this.configPath) {
			this.watcher?.dispose();
			this.watch(path.dirname(status.path));
			this.configPath = status.path;
		}
		if (!status.warn) {
			await this.deps.memento.update(CONFIG_WARNING_FINGERPRINT_KEY, undefined);
			this.pending = false;
			return;
		}
		if (status.fingerprint === this.deps.memento.get<string>(CONFIG_WARNING_FINGERPRINT_KEY)) {
			this.pending = false;
			return;
		}
		if (!this.deps.isFocused()) {
			this.pending = true;
			return;
		}
		await this.deps.memento.update(CONFIG_WARNING_FINGERPRINT_KEY, status.fingerprint);
		this.pending = false;
		void this.showWarning(status);
	}

	private async showWarning(status: ConfigStatus): Promise<void> {
		try {
			const choice = await this.deps.showWarning(status.message, OPEN_CONFIG_ACTION);
			if (choice !== OPEN_CONFIG_ACTION) {
				return;
			}
			const target = status.diagnostics.find((diagnostic) => diagnostic.kind === 'invalid' && diagnostic.line > 0);
			await this.deps.openDocument(
				status.path,
				target === undefined ? {} : { selection: { character: 0, line: target.line - 1 } },
			);
		} catch {
			// The file may be gone by the time the user picks the action.
		}
	}
}
