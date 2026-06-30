import * as crypto from 'node:crypto';
import * as fs from 'node:fs/promises';
import * as http from 'node:http';
import * as https from 'node:https';
import * as net from 'node:net';
import * as os from 'node:os';
import * as path from 'node:path';
import type * as vscode from 'vscode';

const maxResponseBodyBytes = 64 * 1024;

export const o11yOAuthSecretStorageKey = 'observability-studio.o11y.oauth.connection';
export const o11yOAuthForgetMarkerPath = path.join(os.homedir(), '.obstudio', 'splunk-export-forgotten.json');

export type O11yOAuthConnection = {
	accessToken: string;
	connectedAt: string;
	endpoint?: string;
	expiresAt?: string;
	issuer?: string;
	orgId?: string;
	orgName?: string;
	realm?: string;
	scope?: string;
	tokenId?: string;
	tokenName?: string;
	tokenType: string;
};

export type O11yOAuthForgetMarker = {
	connectionFingerprint: string;
	forgottenAt: Date;
};

export type ObserverSplunkExportOptions = {
	baseUrl: string;
	connection: O11yOAuthConnection;
	controlToken: string;
	enabled?: boolean;
	timeoutSeconds?: number;
};

export type ObserverSplunkForgetOptions = {
	baseUrl: string;
	controlToken: string;
};

type ObserverSplunkExportStatusResponse = {
	metrics?: {
		accessTokenConfigured?: unknown;
	};
	traces?: {
		accessTokenConfigured?: unknown;
	};
};

export async function storeO11yOAuthConnection(
	context: vscode.ExtensionContext,
	connection: O11yOAuthConnection,
): Promise<void> {
	await context.secrets.store(o11yOAuthSecretStorageKey, JSON.stringify(connection));
}

export async function clearO11yOAuthConnection(context: vscode.ExtensionContext): Promise<void> {
	await context.secrets.delete(o11yOAuthSecretStorageKey);
}

export async function loadO11yOAuthConnection(context: vscode.ExtensionContext): Promise<O11yOAuthConnection | undefined> {
	const raw = await context.secrets.get(o11yOAuthSecretStorageKey);
	if (raw === undefined) {
		return undefined;
	}

	let parsed: unknown;
	try {
		parsed = JSON.parse(raw);
	} catch {
		return undefined;
	}
	return parseO11yOAuthConnection(parsed);
}

export function parseO11yOAuthConnection(value: unknown): O11yOAuthConnection | undefined {
	if (typeof value !== 'object' || value === null) {
		return undefined;
	}
	const record = value as Record<string, unknown>;
	const accessToken = stringValue(record.accessToken);
	let issuer = stringValue(record.issuer);
	if (accessToken === undefined || issuer === undefined) {
		return undefined;
	}
	try {
		issuer = normalizeO11yOAuthIssuerUrl(issuer);
	} catch {
		return undefined;
	}
	const tokenType = stringValue(record.tokenType) ?? 'Bearer';
	if (tokenType.toLowerCase() !== 'bearer') {
		return undefined;
	}
	const endpoint = stringValue(record.endpoint);
	const realm = stringValue(record.realm);
	if ((endpoint === undefined && realm === undefined) || !isTrustedO11yIngestEndpoint(endpoint, realm)) {
		return undefined;
	}
	return {
		accessToken,
		connectedAt: stringValue(record.connectedAt) ?? new Date(0).toISOString(),
		endpoint,
		expiresAt: stringValue(record.expiresAt),
		issuer,
		orgId: stringValue(record.orgId),
		orgName: stringValue(record.orgName),
		realm,
		scope: stringValue(record.scope),
		tokenId: stringValue(record.tokenId),
		tokenName: stringValue(record.tokenName),
		tokenType: 'Bearer',
	};
}

export async function readO11yOAuthForgetMarker(markerPath = o11yOAuthForgetMarkerPath): Promise<string | undefined> {
	try {
		return await fs.readFile(markerPath, 'utf8');
	} catch (error) {
		if (typeof error === 'object' && error !== null && (error as { code?: unknown }).code === 'ENOENT') {
			return undefined;
		}
		throw error;
	}
}

export function parseO11yOAuthForgetMarker(raw: string): O11yOAuthForgetMarker | undefined {
	let parsed: unknown;
	try {
		parsed = JSON.parse(raw);
	} catch {
		return undefined;
	}
	if (typeof parsed !== 'object' || parsed === null) {
		return undefined;
	}
	const record = parsed as Record<string, unknown>;
	const forgottenAt = stringValue(record.forgottenAt);
	const connectionFingerprint = stringValue(record.connectionFingerprint);
	if (forgottenAt === undefined || connectionFingerprint === undefined) {
		return undefined;
	}
	const date = new Date(forgottenAt);
	return Number.isNaN(date.getTime()) ? undefined : { connectionFingerprint, forgottenAt: date };
}

export function shouldForgetStoredO11yOAuthConnection(
	connection: O11yOAuthConnection,
	marker: O11yOAuthForgetMarker | undefined,
): boolean {
	if (marker === undefined) {
		return false;
	}
	const connectedAt = new Date(connection.connectedAt);
	if (Number.isNaN(connectedAt.getTime())) {
		return marker.connectionFingerprint === o11yOAuthConnectionFingerprint(connection);
	}
	return marker.connectionFingerprint === o11yOAuthConnectionFingerprint(connection)
		&& marker.forgottenAt.getTime() > connectedAt.getTime();
}

export function o11yOAuthConnectionFingerprint(connection: O11yOAuthConnection): string {
	const issuer = connection.issuer === undefined ? '' : normalizeO11yOAuthIssuerUrl(connection.issuer);
	return crypto.createHash('sha256')
		.update(`${issuer}\0${connection.accessToken.trim()}`)
		.digest('base64url');
}

export function isO11yOAuthConnectionUsable(
	connection: O11yOAuthConnection,
	requiredScope: string,
	now = new Date(),
	expirySkewMs = 60_000,
): boolean {
	if (
		connection.accessToken.trim() === ''
		|| connection.issuer?.trim() === ''
		|| connection.issuer === undefined
	) {
		return false;
	}
	try {
		normalizeO11yOAuthIssuerUrl(connection.issuer);
	} catch {
		return false;
	}
	if (connection.expiresAt !== undefined) {
		const expiresAt = new Date(connection.expiresAt);
		if (Number.isNaN(expiresAt.getTime()) || expiresAt.getTime() <= now.getTime() + expirySkewMs) {
			return false;
		}
	}

	const requiredScopes = normalizeScopeSet(requiredScope);
	if (requiredScopes.size === 0) {
		return true;
	}
	const grantedScopes = normalizeScopeSet(connection.scope ?? '');
	return Array.from(requiredScopes).every((scope) => grantedScopes.has(scope));
}

export async function configureObserverSplunkExport(options: ObserverSplunkExportOptions): Promise<void> {
	const baseUrl = normalizeLoopbackObserverBaseUrl(options.baseUrl);
	const endpoint = new URL('/api/splunk/export', baseUrl).toString();
	const response = await postJSON(endpoint, {
		accessToken: options.connection.accessToken,
		enabled: options.enabled ?? false,
		endpoint: options.connection.endpoint,
		issuer: options.connection.issuer,
		realm: options.connection.realm,
		timeoutSeconds: options.timeoutSeconds ?? 5,
	}, options.controlToken);
	if ((response.statusCode ?? 0) < 200 || (response.statusCode ?? 0) >= 300) {
		throw new Error(`Observer export configuration returned HTTP ${response.statusCode ?? 0}: ${response.body}`);
	}
}

export async function forgetObserverSplunkExport(options: ObserverSplunkForgetOptions): Promise<void> {
	const baseUrl = normalizeLoopbackObserverBaseUrl(options.baseUrl);
	const endpoint = new URL('/api/splunk/export/forget', baseUrl).toString();
	const response = await postJSON(endpoint, {}, options.controlToken);
	if ((response.statusCode ?? 0) < 200 || (response.statusCode ?? 0) >= 300) {
		throw new Error(`Observer export forget returned HTTP ${response.statusCode ?? 0}: ${response.body}`);
	}
}

export async function observerSplunkExportHasAccessToken(baseUrl: string): Promise<boolean> {
	const normalizedBaseUrl = normalizeLoopbackObserverBaseUrl(baseUrl);
	const endpoint = new URL('/api/splunk/export', normalizedBaseUrl).toString();
	const response = await getJSON(endpoint);
	if ((response.statusCode ?? 0) < 200 || (response.statusCode ?? 0) >= 300) {
		throw new Error(`Observer export status returned HTTP ${response.statusCode ?? 0}: ${response.body}`);
	}

	let parsed: unknown;
	try {
		parsed = JSON.parse(response.body);
	} catch {
		throw new Error('Observer export status returned invalid JSON.');
	}
	if (typeof parsed !== 'object' || parsed === null) {
		throw new Error('Observer export status returned an invalid response.');
	}
	const status = parsed as ObserverSplunkExportStatusResponse;
	const signalStatuses = [status.metrics, status.traces].filter((item): item is { accessTokenConfigured?: unknown } => Boolean(item));
	return signalStatuses.length > 0 && signalStatuses.every((item) => item.accessTokenConfigured === true);
}

export function normalizeO11yOAuthIssuerUrl(rawUrl: string): string {
	if (rawUrl.trim() === '') {
		throw new Error('Splunk Observability Cloud OAuth issuer URL is required.');
	}
	const parsed = new URL(rawUrl.trim());
	if (parsed.username || parsed.password) {
		throw new Error('issuerUrl must not contain credentials.');
	}
	if (parsed.protocol === 'http:') {
		if (!isLoopbackHost(parsed.hostname)) {
			throw new Error('issuerUrl may use http only for loopback development hosts.');
		}
	} else if (parsed.protocol !== 'https:') {
		throw new Error('issuerUrl must use https.');
	} else if (!isTrustedO11yIssuerHost(parsed.hostname)) {
		throw new Error('issuerUrl must use a registered Splunk Observability Cloud host.');
	}
	return parsed.origin;
}

function isTrustedO11yIssuerHost(hostname: string): boolean {
	const normalized = hostname.toLowerCase();
	return /^app\.[a-z]{2,12}[0-9]+\.observability\.splunkcloud\.com$/.test(normalized)
		|| /^app\.[a-z]{2,12}[0-9]+\.signalfx\.com$/.test(normalized)
		|| normalized === 'mon.observability.splunkcloud.com'
		|| normalized === 'mon.signalfx.com';
}

function isTrustedO11yIngestEndpoint(endpoint: string | undefined, realm: string | undefined): boolean {
	if (endpoint === undefined) {
		return realm !== undefined;
	}
	if (realm === undefined) {
		return false;
	}
	let parsed: URL;
	try {
		parsed = new URL(endpoint);
	} catch {
		return false;
	}
	const expectedRealm = realm.toLowerCase();
	const hostname = parsed.hostname.toLowerCase();
	return parsed.protocol === 'https:'
		&& parsed.username === ''
		&& parsed.password === ''
		&& parsed.port === ''
		&& parsed.search === ''
		&& parsed.hash === ''
		&& (parsed.pathname === '' || parsed.pathname === '/')
		&& (
			hostname === `ingest.${expectedRealm}.signalfx.com`
			|| hostname === `ingest.${expectedRealm}.observability.splunkcloud.com`
			|| (expectedRealm === 'mon0' && hostname === 'mon-ingest.signalfx.com')
		);
}

function normalizeLoopbackObserverBaseUrl(rawUrl: string): string {
	const parsed = new URL(rawUrl.trim());
	if (parsed.protocol !== 'https:' && parsed.protocol !== 'http:') {
		throw new Error('Observer URL must use http or https.');
	}
	if (!isLoopbackHost(parsed.hostname)) {
		throw new Error('Observer export configuration is only sent to a loopback observer.');
	}
	if (parsed.pathname.endsWith('/mcp')) {
		parsed.pathname = parsed.pathname.slice(0, -4) || '/';
	}
	parsed.search = '';
	parsed.hash = '';
	return parsed.toString().replace(/\/$/, '');
}

function isLoopbackHost(hostname: string): boolean {
	if (hostname.toLowerCase() === 'localhost') {
		return true;
	}
	const address = net.isIP(hostname) === 0 ? undefined : hostname;
	return address === '127.0.0.1' || address === '::1';
}

function normalizeScopeSet(raw: string): Set<string> {
	return new Set(raw.trim().split(/\s+/u).filter(Boolean).map((scope) => scope.toLowerCase()));
}

function stringValue(value: unknown): string | undefined {
	return typeof value === 'string' && value.trim() !== '' ? value.trim() : undefined;
}

function postJSON(rawUrl: string, payload: Record<string, unknown>, controlToken: string): Promise<{ body: string; statusCode?: number }> {
	const body = JSON.stringify(payload);
	return requestBody(rawUrl, 'POST', body, {
		Authorization: `Bearer ${controlToken}`,
		'Content-Length': String(Buffer.byteLength(body)),
		'Content-Type': 'application/json',
	});
}

function getJSON(rawUrl: string): Promise<{ body: string; statusCode?: number }> {
	return requestBody(rawUrl, 'GET', undefined, { Accept: 'application/json' });
}

function requestBody(
	rawUrl: string,
	method: 'GET' | 'POST',
	body: string | undefined,
	headers: Record<string, string>,
): Promise<{ body: string; statusCode?: number }> {
	return new Promise((resolve, reject) => {
		const target = new URL(rawUrl);
		const client = target.protocol === 'https:' ? https : http;
		const request = client.request(target, { headers, method }, (response) => {
			let totalBytes = 0;
			const chunks: Buffer[] = [];
			response.on('data', (chunk: Buffer) => {
				totalBytes += chunk.byteLength;
				if (totalBytes > maxResponseBodyBytes) {
					request.destroy(new Error('Observer response was too large.'));
					return;
				}
				chunks.push(chunk);
			});
			response.on('end', () => {
				resolve({ body: Buffer.concat(chunks).toString('utf8'), statusCode: response.statusCode });
			});
		});
		request.setTimeout(15_000, () => request.destroy(new Error('Timed out waiting for Observer.')));
		request.once('error', reject);
		request.end(body);
	});
}
