import * as fs from 'node:fs';
import * as crypto from 'node:crypto';
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
	challengeProof?: string;
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
	healthProofSecret?: string;
	healthUrl?: string;
	mcpUrl?: string;
	updatedAt?: string;
};

export type SharedObserverDiscovery = {
	baseUrl: string;
	controlToken?: string;
	healthProofSecret?: string;
	healthUrl?: string;
	mcpUrl?: string;
	updatedAtMs?: number;
};

export const observerHealthProofChallengeQuery = 'obstudioHealthChallenge';
const observerHealthProofChallengeBytes = 32;
const observerHealthProofDomain = 'obstudio-health-proof-v2\0';

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
		throw new Error('Observer URL cannot be empty.');
	}

	const parsed = new URL(trimmed);
	if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') {
		throw new Error(`Observer URL must use http or https: ${raw}`);
	}
	const authority = trimmed.slice(trimmed.indexOf('//') + 2).split(/[/?#]/, 1)[0];
	if (parsed.username !== '' || parsed.password !== '' || authority.includes('@')) {
		throw new Error('Observer URL must not include user information.');
	}
	if (parsed.hash !== '' || trimmed.includes('#')) {
		throw new Error('Observer URL must not include a fragment.');
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
	if (parsed.protocol === 'http:' && !isLoopbackObserverHost(parsed.hostname)) {
		throw new Error('Observer URL must use HTTPS unless the host is loopback.');
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
		const controlToken = typeof state.controlToken === 'string' && state.controlToken.trim().length > 0
			? state.controlToken.trim()
			: undefined;
		const healthProofSecret = typeof state.healthProofSecret === 'string'
			&& isCanonicalBase64Url(state.healthProofSecret.trim(), observerHealthProofChallengeBytes)
			? state.healthProofSecret.trim()
			: undefined;
		const healthUrl = typeof state.healthUrl === 'string' && state.healthUrl.trim().length > 0
			? normalizeSharedObserverHealthUrl(state.healthUrl)
			: undefined;
		const mcpUrl = typeof state.mcpUrl === 'string' && state.mcpUrl.trim().length > 0
			? normalizeSharedObserverMCPUrl(state.mcpUrl)
			: undefined;
		return {
			baseUrl: normalizeSharedObserverBaseUrl(state.baseUrl),
			...(controlToken !== undefined ? { controlToken } : {}),
			...(healthProofSecret !== undefined ? { healthProofSecret } : {}),
			...(healthUrl !== undefined ? { healthUrl } : {}),
			...(mcpUrl !== undefined ? { mcpUrl } : {}),
			...(Number.isFinite(updatedAtMs) ? { updatedAtMs } : {}),
		};
	} catch {
		return undefined;
	}
}

function readPrivateSharedObserverState(statePath: string): string | undefined {
	const effectiveUserId = process.geteuid?.();
	if (effectiveUserId === undefined || process.platform === 'win32') {
		// Node does not expose the Windows ACL primitives needed to prove the same
		// owner-only policy as the Observer. Keep discovery fail-closed there.
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
	let normalized: string;
	try {
		normalized = normalizeObserverBaseUrl(raw);
	} catch (error) {
		if (error instanceof Error && error.message === 'Observer URL must use HTTPS unless the host is loopback.') {
			throw new Error('A non-local shared Observer URL must use HTTPS.');
		}
		throw error;
	}
	const parsed = new URL(normalized);
	if (parsed.protocol === 'http:' && !isLocalObserverControlHost(parsed.hostname)) {
		throw new Error('A non-local shared Observer URL must use HTTPS.');
	}
	return normalized;
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
		throw new Error(`Observer ${label} URL cannot be empty.`);
	}
	const parsed = new URL(trimmed);
	if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') {
		throw new Error(`Observer ${label} URL must use http or https.`);
	}
	const authority = trimmed.slice(trimmed.indexOf('//') + 2).split(/[/?#]/, 1)[0];
	if (parsed.username !== '' || parsed.password !== '' || authority.includes('@')) {
		throw new Error(`Observer ${label} URL must not include user information.`);
	}
	if (parsed.hash !== '' || parsed.search !== '' || trimmed.includes('#')) {
		throw new Error(`Observer ${label} URL must not include a query or fragment.`);
	}
	const hostname = parsed.hostname.toLowerCase().replace(/^\[|\]$/g, '');
	if (hostname === '0.0.0.0') {
		parsed.hostname = '127.0.0.1';
	} else if (hostname === '::') {
		parsed.hostname = '[::1]';
	} else if (hostname.endsWith('.') && isLoopbackObserverHost(hostname)) {
		parsed.hostname = hostname.slice(0, -1);
	}
	if (parsed.protocol === 'http:' && !isLocalObserverControlHost(parsed.hostname)) {
		throw new Error(`A non-local Observer ${label} URL must use HTTPS.`);
	}
	parsed.pathname = parsed.pathname.replace(/\/+$/, '');
	if (!parsed.pathname.endsWith(suffix)) {
		throw new Error(`Observer ${label} URL must end with ${suffix}.`);
	}
	return parsed.toString();
}

export function createObserverHealthProofChallenge(): string {
	return crypto.randomBytes(observerHealthProofChallengeBytes).toString('base64url');
}

function observerMCPUrl(observerUrl: string): string | undefined {
	try {
		return normalizeSharedObserverMCPUrl(`${normalizeSharedObserverBaseUrl(observerUrl)}/mcp`);
	} catch {
		return undefined;
	}
}

export function verifiedSharedObserverMCPUrl(
	observerUrl: string,
	health: ObserverHealth,
	intendedControlMCPUrl?: string,
): string | undefined {
	const intendedMCPUrl = observerMCPUrl(intendedControlMCPUrl ?? observerUrl);
	const advertisedMCPUrl = health.endpoints?.mcp;
	if (
		intendedMCPUrl === undefined
		|| typeof advertisedMCPUrl !== 'string'
	) {
		return undefined;
	}
	let normalizedAdvertisedMCPUrl: string;
	try {
		normalizedAdvertisedMCPUrl = normalizeSharedObserverMCPUrl(advertisedMCPUrl);
	} catch {
		return undefined;
	}
	if (
		normalizedAdvertisedMCPUrl !== advertisedMCPUrl
		|| !sameAdvertisedObserverControlEndpoint(intendedMCPUrl, normalizedAdvertisedMCPUrl)
	) {
		return undefined;
	}
	return normalizedAdvertisedMCPUrl;
}

export function verifySharedObserverControlToken(
	observerUrl: string,
	discovered: SharedObserverDiscovery,
	challenge: string,
	health: ObserverHealth,
	rejectedToken?: string,
	intendedControlMCPUrl?: string,
): string | undefined {
	const controlToken = discovered.controlToken?.trim();
	const healthProofSecret = discovered.healthProofSecret?.trim();
	const proof = health.challengeProof;
	const advertisedMCPUrl = health.endpoints?.mcp;
	if (
		controlToken === undefined
		|| controlToken === ''
		|| healthProofSecret === undefined
		|| !isCanonicalBase64Url(healthProofSecret, observerHealthProofChallengeBytes)
		|| controlToken === rejectedToken
		|| proof === undefined
		|| typeof advertisedMCPUrl !== 'string'
		|| verifiedSharedObserverMCPUrl(observerUrl, health, intendedControlMCPUrl) === undefined
		|| !isCanonicalBase64Url(challenge, observerHealthProofChallengeBytes)
		|| !isCanonicalBase64Url(proof, 32)
	) {
		return undefined;
	}
	const controlTokenDigest = crypto.createHash('sha256').update(controlToken, 'utf8').digest();
	const expectedProof = crypto
		.createHmac('sha256', Buffer.from(healthProofSecret, 'base64url'))
		.update(observerHealthProofDomain, 'utf8')
		.update(controlTokenDigest)
		.update(Buffer.from([0]))
		.update(challenge, 'utf8')
		.update(Buffer.from([0]))
		.update(advertisedMCPUrl, 'utf8')
		.digest();
	const providedProof = Buffer.from(proof, 'base64url');
	return crypto.timingSafeEqual(expectedProof, providedProof) ? controlToken : undefined;
}

function sameAdvertisedObserverControlEndpoint(intended: string, advertised: string): boolean {
	if (intended === advertised) {
		return true;
	}
	try {
		const intendedURL = new URL(intended);
		const advertisedURL = new URL(advertised);
		if (!isLocalhostIPv4Alias(intendedURL.hostname) || !isLocalhostIPv4Alias(advertisedURL.hostname)) {
			return false;
		}
		return intendedURL.protocol === advertisedURL.protocol
			&& effectiveObserverPort(intendedURL) === effectiveObserverPort(advertisedURL)
			&& intendedURL.pathname === advertisedURL.pathname
			&& intendedURL.search === advertisedURL.search
			&& intendedURL.hash === ''
			&& advertisedURL.hash === ''
			&& intendedURL.username === ''
			&& intendedURL.password === ''
			&& advertisedURL.username === ''
			&& advertisedURL.password === '';
	} catch {
		return false;
	}
}

function isLocalhostIPv4Alias(hostname: string): boolean {
	const normalized = hostname.toLowerCase().replace(/\.$/, '');
	return normalized === 'localhost' || normalized === '127.0.0.1';
}

function effectiveObserverPort(value: URL): string {
	return value.port || (value.protocol === 'https:' ? '443' : '80');
}

function isCanonicalBase64Url(value: string, decodedLength: number): boolean {
	if (!/^[A-Za-z0-9_-]+$/.test(value)) {
		return false;
	}
	const decoded = Buffer.from(value, 'base64url');
	return decoded.length === decodedLength && decoded.toString('base64url') === value;
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
