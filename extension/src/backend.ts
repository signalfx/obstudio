import * as fs from 'node:fs';
import { isIP } from 'node:net';
import * as path from 'node:path';

export type ObserverBackend = {
	args: string[];
	command: string;
	cwd: string;
	env: Record<string, string>;
	label: string;
};

export type ObserverHealth = {
	apiVersion?: string;
	endpoints?: Record<string, string>;
	kind?: string;
	mode?: string;
	owner?: string;
	startedAt?: string;
	version?: string;
};

type SharedObserverState = {
	baseUrl?: string;
	healthUrl?: string;
	mcpUrl?: string;
	pid?: number;
	updatedAt?: string;
};

export type SharedObserverDiscovery = {
	baseUrl: string;
	healthUrl?: string;
	mcpUrl?: string;
	pid?: number;
	updatedAtMs?: number;
};

export function isLoopbackObserverHost(hostname: string): boolean {
	let normalized = hostname.trim().toLowerCase();
	if (normalized.startsWith('[') && normalized.endsWith(']')) {
		normalized = normalized.slice(1, -1);
	}
	if (normalized.endsWith('.') && !normalized.endsWith('..')) {
		normalized = normalized.slice(0, -1);
	}
	if (normalized === 'localhost' || normalized === '::1') {
		return true;
	}
	if (isIP(normalized) !== 4) {
		return false;
	}
	return Number(normalized.split('.')[0]) === 127;
}

export function normalizeObserverBaseUrl(raw: string): string {
	const trimmed = raw.trim();
	if (trimmed.length === 0) {
		throw new Error('Splunk Observability Studio URL cannot be empty.');
	}

	const parsed = new URL(trimmed);
	if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') {
		throw new Error(`Splunk Observability Studio URL must use http or https: ${raw}`);
	}
	const authority = trimmed.slice(trimmed.indexOf('//') + 2).split(/[/?#]/, 1)[0];
	if (parsed.username !== '' || parsed.password !== '' || authority.includes('@')) {
		throw new Error('Splunk Observability Studio URL must not include user information.');
	}
	if (parsed.hash !== '' || trimmed.includes('#')) {
		throw new Error('Splunk Observability Studio URL must not include a fragment.');
	}
	const hostname = parsed.hostname.toLowerCase().replace(/^\[|\]$/g, '');
	if (hostname === '0.0.0.0') {
		// Wildcard addresses are valid listener addresses, not destinations.
		// Connect to the same local listener through an explicit loopback host.
		parsed.hostname = '127.0.0.1';
	} else if (hostname === '::') {
		parsed.hostname = '[::1]';
	} else if (hostname.endsWith('.') && isLoopbackObserverHost(hostname)) {
		parsed.hostname = hostname.slice(0, -1);
	}
	if (!isLoopbackObserverHost(parsed.hostname)) {
		throw new Error('Splunk Observability Studio URL host must be loopback.');
	}

	if (parsed.pathname.endsWith('/mcp')) {
		parsed.pathname = parsed.pathname.slice(0, -4) || '/';
	}

	parsed.search = '';
	return parsed.toString().replace(/\/$/, '');
}

export function buildObserverValidatorSummaryUrl(baseUrl: string): string {
	return `${normalizeObserverBaseUrl(baseUrl)}/api/query/validation/summary`;
}

export function buildObserverHealthUrl(baseUrl: string): string {
	return `${normalizeObserverBaseUrl(baseUrl)}/api/health`;
}

export function observerPortFromUrl(baseUrl: string): number | undefined {
	const parsed = new URL(normalizeObserverBaseUrl(baseUrl));
	if (parsed.port.length > 0) {
		return Number(parsed.port);
	}
	if (parsed.protocol === 'http:') {
		return 80;
	}
	if (parsed.protocol === 'https:') {
		return 443;
	}
	return undefined;
}

export function readSharedObserverDiscovery(
	homeDir: string,
	statePathOverride?: string,
): SharedObserverDiscovery | undefined {
	const statePath = statePathOverride?.trim() || path.join(homeDir, '.obstudio', 'shared-observer.json');
	try {
		const stateContents = readPrivateSharedObserverState(statePath);
		if (stateContents === undefined) {
			return undefined;
		}
		const state = JSON.parse(stateContents) as SharedObserverState;
		if (typeof state.baseUrl !== 'string' || state.baseUrl.trim().length === 0) {
			return undefined;
		}
		const updatedAtMs = typeof state.updatedAt === 'string' ? Date.parse(state.updatedAt) : Number.NaN;
		const healthUrl = typeof state.healthUrl === 'string' && state.healthUrl.trim().length > 0
			? normalizeSharedObserverHealthUrl(state.healthUrl)
			: undefined;
		const mcpUrl = typeof state.mcpUrl === 'string' && state.mcpUrl.trim().length > 0
			? normalizeSharedObserverMCPUrl(state.mcpUrl)
			: undefined;
		const pid = typeof state.pid === 'number' && Number.isSafeInteger(state.pid) && state.pid > 0
			? state.pid
			: undefined;
		return {
			baseUrl: normalizeSharedObserverBaseUrl(state.baseUrl),
			...(healthUrl !== undefined ? { healthUrl } : {}),
			...(mcpUrl !== undefined ? { mcpUrl } : {}),
			...(pid !== undefined ? { pid } : {}),
			...(Number.isFinite(updatedAtMs) ? { updatedAtMs } : {}),
		};
	} catch {
		return undefined;
	}
}

function readPrivateSharedObserverState(statePath: string): string | undefined {
	const effectiveUserId = process.geteuid?.();
	if (process.platform === 'win32') {
		// The shared state contains only validated loopback endpoints and a PID, not
		// credentials. Windows profile ACLs protect the directory, and callers must
		// independently verify the listener PID and Splunk Observability Studio executable before stopping
		// it. Still reject links and file-replacement races here.
		const linkedBefore = fs.lstatSync(statePath);
		if (linkedBefore.isSymbolicLink() || !linkedBefore.isFile()) {
			return undefined;
		}
		const descriptor = fs.openSync(statePath, fs.constants.O_RDONLY);
		try {
			const opened = fs.fstatSync(descriptor);
			const linkedAfter = fs.lstatSync(statePath);
			if (
				!opened.isFile()
				|| linkedAfter.isSymbolicLink()
				|| !linkedAfter.isFile()
				|| linkedAfter.dev !== opened.dev
				|| linkedAfter.ino !== opened.ino
				|| linkedAfter.dev !== linkedBefore.dev
				|| linkedAfter.ino !== linkedBefore.ino
			) {
				return undefined;
			}
			return fs.readFileSync(descriptor, 'utf8');
		} finally {
			fs.closeSync(descriptor);
		}
	}
	if (effectiveUserId === undefined) {
		return undefined;
	}
	const parentPath = path.dirname(statePath);
	const parentBefore = fs.lstatSync(parentPath);
	if (
		parentBefore.isSymbolicLink()
		|| !parentBefore.isDirectory()
		|| parentBefore.uid !== effectiveUserId
		|| (parentBefore.mode & 0o022) !== 0
	) {
		return undefined;
	}

	const descriptor = fs.openSync(statePath, fs.constants.O_RDONLY | fs.constants.O_NOFOLLOW);
	try {
		const opened = fs.fstatSync(descriptor);
		const linked = fs.lstatSync(statePath);
		const parentAfter = fs.lstatSync(parentPath);
		if (
			!opened.isFile()
			|| opened.uid !== effectiveUserId
			|| (opened.mode & 0o777) !== 0o600
			|| linked.isSymbolicLink()
			|| !linked.isFile()
			|| linked.dev !== opened.dev
			|| linked.ino !== opened.ino
			|| parentAfter.dev !== parentBefore.dev
			|| parentAfter.ino !== parentBefore.ino
		) {
			return undefined;
		}
		return fs.readFileSync(descriptor, 'utf8');
	} finally {
		fs.closeSync(descriptor);
	}
}

export function normalizeSharedObserverBaseUrl(raw: string): string {
	return normalizeObserverBaseUrl(raw);
}

export function normalizeSharedObserverHealthUrl(raw: string): string {
	return normalizeSharedObserverEndpointUrl(raw, '/api/health', 'health');
}

export function normalizeSharedObserverMCPUrl(raw: string): string {
	return normalizeSharedObserverEndpointUrl(raw, '/mcp', 'MCP');
}

function normalizeSharedObserverEndpointUrl(raw: string, suffix: string, label: string): string {
	const trimmed = raw.trim();
	if (trimmed.length === 0) {
		throw new Error(`Splunk Observability Studio ${label} URL cannot be empty.`);
	}
	const parsed = new URL(trimmed);
	if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') {
		throw new Error(`Splunk Observability Studio ${label} URL must use http or https.`);
	}
	const authority = trimmed.slice(trimmed.indexOf('//') + 2).split(/[/?#]/, 1)[0];
	if (parsed.username !== '' || parsed.password !== '' || authority.includes('@')) {
		throw new Error(`Splunk Observability Studio ${label} URL must not include user information.`);
	}
	if (parsed.hash !== '' || parsed.search !== '' || trimmed.includes('#')) {
		throw new Error(`Splunk Observability Studio ${label} URL must not include a query or fragment.`);
	}
	const hostname = parsed.hostname.toLowerCase().replace(/^\[|\]$/g, '');
	if (hostname === '0.0.0.0') {
		parsed.hostname = '127.0.0.1';
	} else if (hostname === '::') {
		parsed.hostname = '[::1]';
	} else if (hostname.endsWith('.') && isLoopbackObserverHost(hostname)) {
		parsed.hostname = hostname.slice(0, -1);
	}
	if (!isLoopbackObserverHost(parsed.hostname)) {
		throw new Error(`Splunk Observability Studio ${label} URL host must be loopback.`);
	}
	parsed.pathname = parsed.pathname.replace(/\/+$/, '');
	if (!parsed.pathname.endsWith(suffix)) {
		throw new Error(`Splunk Observability Studio ${label} URL must end with ${suffix}.`);
	}
	return parsed.toString();
}

export function resolveBackend(extensionPath: string): ObserverBackend {
	const candidates = process.platform === 'win32'
		? ['obstudio.exe', 'obstudio']
		: ['obstudio', 'obstudio.exe'];

	for (const candidate of candidates) {
		const binary = path.join(extensionPath, 'dist', 'observer', candidate);
		if (!fs.existsSync(binary)) {
			continue;
		}

		const env: Record<string, string> = {};
		const weaverCandidates = path.extname(binary) === '.exe'
			? ['weaver.exe', 'weaver']
			: ['weaver', 'weaver.exe'];
		for (const weaverCandidate of weaverCandidates) {
			const weaver = path.join(path.dirname(binary), weaverCandidate);
			if (!fs.existsSync(weaver)) {
				continue;
			}
			env.WEAVER_PATH = weaver;
			break;
		}
		return {
			args: [],
			command: binary,
			cwd: path.dirname(binary),
			env,
			label: 'Splunk Observability Studio',
		};
	}

	throw new Error(
		`Splunk Observability Studio binary not found in ${path.join(extensionPath, 'dist', 'observer')}. Run 'npm run compile' in the extension directory.`,
	);
}
