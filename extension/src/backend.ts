import * as fs from 'node:fs';
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
	controlToken?: string;
	updatedAt?: string;
};

export type SharedObserverDiscovery = {
	baseUrl: string;
	controlToken?: string;
	updatedAtMs?: number;
};

export function normalizeObserverBaseUrl(raw: string): string {
	const trimmed = raw.trim();
	if (trimmed.length === 0) {
		throw new Error('Observer URL cannot be empty.');
	}

	const parsed = new URL(trimmed);
	if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') {
		throw new Error(`Observer URL must use http or https: ${raw}`);
	}

	if (parsed.pathname.endsWith('/mcp')) {
		parsed.pathname = parsed.pathname.slice(0, -4) || '/';
	}
	const hostname = parsed.hostname.toLowerCase().replace(/^\[|\]$/g, '');
	if (hostname === '0.0.0.0') {
		// Wildcard addresses are valid listener addresses, not destinations.
		// Connect to the same local listener through an explicit loopback host.
		parsed.hostname = '127.0.0.1';
	} else if (hostname === '::') {
		parsed.hostname = '[::1]';
	}

	parsed.search = '';
	parsed.hash = '';
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
		const state = JSON.parse(fs.readFileSync(statePath, 'utf8')) as SharedObserverState;
		if (typeof state.baseUrl !== 'string' || state.baseUrl.trim().length === 0) {
			return undefined;
		}
		const updatedAtMs = typeof state.updatedAt === 'string' ? Date.parse(state.updatedAt) : Number.NaN;
		const controlToken = typeof state.controlToken === 'string' && state.controlToken.trim().length > 0
			? state.controlToken.trim()
			: undefined;
		return {
			baseUrl: normalizeSharedObserverBaseUrl(state.baseUrl),
			...(controlToken !== undefined ? { controlToken } : {}),
			...(Number.isFinite(updatedAtMs) ? { updatedAtMs } : {}),
		};
	} catch {
		return undefined;
	}
}

function sameObserverControlEndpoint(left: string, right: string): boolean {
	return canonicalObserverControlEndpoint(left) === canonicalObserverControlEndpoint(right);
}

export function isLocalObserverControlHost(rawHostname: string): boolean {
	const hostname = rawHostname.toLowerCase().replace(/^\[|\]$/g, '');
	const ipv4Octets = hostname.split('.');
	const ipv4Loopback = ipv4Octets.length === 4
		&& ipv4Octets[0] === '127'
		&& ipv4Octets.every((octet) => /^\d{1,3}$/.test(octet) && Number(octet) <= 255);
	return hostname === 'localhost'
		|| hostname === '::1'
		|| ipv4Loopback;
}

export function normalizeSharedObserverBaseUrl(raw: string): string {
	const normalized = normalizeObserverBaseUrl(raw);
	const parsed = new URL(normalized);
	if (parsed.protocol === 'http:' && !isLocalObserverControlHost(parsed.hostname)) {
		throw new Error('A non-local shared Observer URL must use HTTPS.');
	}
	return normalized;
}

function canonicalObserverControlEndpoint(raw: string): string {
	const parsed = new URL(normalizeObserverBaseUrl(raw));
	const hostname = parsed.hostname.toLowerCase().replace(/^\[|\]$/g, '');
	if (
		hostname === 'localhost'
		|| hostname === '127.0.0.1'
		|| hostname === '0.0.0.0'
	) {
		parsed.hostname = '127.0.0.1';
	} else if (hostname === '::1' || hostname === '::') {
		parsed.hostname = '[::1]';
	}
	return parsed.toString().replace(/\/$/, '');
}

export function resolveSharedObserverControlToken(
	observerUrl: string,
	homeDir: string,
	inheritedToken: string | undefined,
	statePathOverride?: string,
	rejectedToken?: string,
): string | undefined {
	const discovered = readSharedObserverDiscovery(homeDir, statePathOverride);
	if (
		discovered?.controlToken !== undefined
		&& sameObserverControlEndpoint(discovered.baseUrl, observerUrl)
		&& discovered.controlToken !== rejectedToken
	) {
		return discovered.controlToken;
	}
	const normalizedInheritedToken = inheritedToken?.trim();
	return normalizedInheritedToken === '' || normalizedInheritedToken === rejectedToken
		? undefined
		: normalizedInheritedToken;
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
			label: 'observer',
		};
	}

	throw new Error(
		`observer binary not found in ${path.join(extensionPath, 'dist', 'observer')}. Run 'npm run compile' in the extension directory.`,
	);
}
