import * as crypto from 'node:crypto';
import * as fs from 'node:fs/promises';
import * as http from 'node:http';
import * as https from 'node:https';
import * as net from 'node:net';
import * as path from 'node:path';
import * as tls from 'node:tls';

const defaultRequestTimeoutMs = 15_000;
const authorizationTimeoutMs = 5 * 60_000;
const maxResponseBodyBytes = 64 * 1024;
const maxDevelopmentCaBundleBytes = 256 * 1024;
const pemCertificatePattern = /-----BEGIN CERTIFICATE-----[\s\S]*?-----END CERTIFICATE-----/gu;

export const sisCIMDOAuthSessionSecretStorageKey = 'observability-studio.sis-cimd.oauth.session';
export const sisCIMDOAuthRedirectUri = 'http://127.0.0.1:33418/callback';

export type SISCIMDOAuthConfiguration = {
	clientId: string;
	developmentCaBundlePath?: string;
	issuer: string;
	redirectUri: string;
	scope: string;
};

export type SISCIMDOAuthSession = {
	accessToken: string;
	clientId: string;
	connectedAt: string;
	expiresAt: string;
	idToken?: string;
	issuer: string;
	redirectUri: string;
	refreshToken?: string;
	scope: string;
	tokenType: 'Bearer';
};

export type SISCIMDRequestOptions = {
	body?: string;
	headers?: Record<string, string>;
	maxBodyBytes?: number;
	method?: 'GET' | 'POST';
	localDevelopmentCA?: string[];
	signal?: AbortSignal;
	timeoutMs?: number;
};

// Note that somee of these properties in the next few types are unknown.  We make use of validator functions
//   for these that return the property as its appropriate type AND validated for content.  
type ClientMetadata = {
	client_id?: unknown;
	grant_types?: unknown;
	redirect_uris?: unknown;
	response_types?: unknown;
	scope?: unknown;
	token_endpoint_auth_method?: unknown;
};

type DiscoveryDocument = {
	authorization_endpoint?: unknown;
	client_id_metadata_document_supported?: unknown;
	code_challenge_methods_supported?: unknown;
	grant_types_supported?: unknown;
	issuer?: unknown;
	registration_endpoint?: unknown;
	response_types_supported?: unknown;
	scopes_supported?: unknown;
	token_endpoint?: unknown;
	token_endpoint_auth_methods_supported?: unknown;
};

type ValidatedDiscovery = {
	authorizationEndpoint: string;
	tokenEndpoint: string;
};

type TokenResponse = {
	access_token?: unknown;
	expires_in?: unknown;
	id_token?: unknown;
	refresh_token?: unknown;
	scope?: unknown;
	token_type?: unknown;
};

type CallbackResult = {
	code: string;
	response: http.ServerResponse;
};

type CallbackServer = {
	close(): Promise<void>;
	result: Promise<CallbackResult>;
};

type SISCIMDResponse = {
	body: string;
	headers: http.IncomingHttpHeaders;
	statusCode: number;
};

type SISCIMDEndpoints = {
	endpoints: ValidatedDiscovery;
	localDevelopmentCA: string[] | undefined;
	normalizedConfiguration: SISCIMDOAuthConfiguration;
};

type SISCIMDAuthorizationRequest = {
	authorizationUrl: URL;
	state: string;
	verifier: string;
};

export type SISCIMDRegistrationResult = {
	authorizationUrl: string;
	cookieMaxAgeSeconds: number;
	location: string;
};

// Fetches and cross-validates the CIMD client metadata document and SIS discovery
// document, shared by both the full sign-in flow and the registration-only probe below.
async function resolveSISCIMDEndpoints(
	configuration: SISCIMDOAuthConfiguration,
	signal?: AbortSignal,
): Promise<SISCIMDEndpoints> {
	const normalizedConfiguration = normalizeConfiguration(configuration);
	const localDevelopmentCA = await loadLocalDevelopmentCA(normalizedConfiguration);
	const discoveryUrl = `${normalizedConfiguration.issuer}/.well-known/openid-configuration`;
	const tagRequestError = (url: string, request: Promise<SISCIMDResponse>): Promise<SISCIMDResponse> =>
		request.catch((error: unknown) => {
			const message = error instanceof Error ? error.message : String(error);
			const tagged = new Error(`[requesting ${url} with ${localDevelopmentCA?.length ?? 0} CA(s)] ${message}`);
			if (error instanceof Error && 'code' in error) {
				(tagged as NodeJS.ErrnoException).code = (error as NodeJS.ErrnoException).code;
			}
			throw tagged;
		});
	const [metadataResponse, discoveryResponse] = await Promise.all([
		tagRequestError(normalizedConfiguration.clientId, requestSISCIMD(normalizedConfiguration.clientId, { localDevelopmentCA, signal })),
		tagRequestError(discoveryUrl, requestSISCIMD(discoveryUrl, { localDevelopmentCA, signal })),
	]);
	const metadata = parseJSONObject(metadataResponse, 'CIMD client metadata');
	const discovery = parseJSONObject(discoveryResponse, 'SIS discovery document');
	validateClientMetadata(metadata, normalizedConfiguration);
	const endpoints = validateDiscoveryDocument(discovery, normalizedConfiguration);
	return { endpoints, localDevelopmentCA, normalizedConfiguration };
}

function buildAuthorizationRequest(
	normalizedConfiguration: SISCIMDOAuthConfiguration,
	endpoints: ValidatedDiscovery,
): SISCIMDAuthorizationRequest {
	const state = crypto.randomBytes(32).toString('base64url');
	const verifier = crypto.randomBytes(64).toString('base64url');
	const challenge = crypto.createHash('sha256').update(verifier).digest('base64url');
	const authorizationUrl = new URL(endpoints.authorizationEndpoint);
	authorizationUrl.searchParams.set('response_type', 'code');
	authorizationUrl.searchParams.set('client_id', normalizedConfiguration.clientId);
	authorizationUrl.searchParams.set('redirect_uri', normalizedConfiguration.redirectUri);
	authorizationUrl.searchParams.set('scope', normalizedConfiguration.scope);
	authorizationUrl.searchParams.set('state', state);
	authorizationUrl.searchParams.set('code_challenge', challenge);
	authorizationUrl.searchParams.set('code_challenge_method', 'S256');
	return { authorizationUrl, state, verifier };
}

// TODO(CIMD PoC): This proves SIS resolves our CIMD client and begins a federated
// authorization redirect (a 302 with a Location and a short-lived session cookie). It
// deliberately does not follow that redirect into IDP login -- that is the next step,
// once the identity-provider integration is designed. Treat this as "registration
// verified," not "signed in."
export async function registerClientWithSIS(
	configuration: SISCIMDOAuthConfiguration,
	signal?: AbortSignal,
): Promise<SISCIMDRegistrationResult> {
	throwIfAuthorizationCancelled(signal);
	const { endpoints, localDevelopmentCA, normalizedConfiguration } = await resolveSISCIMDEndpoints(
		configuration,
		signal,
	);
	throwIfAuthorizationCancelled(signal);
	const { authorizationUrl } = buildAuthorizationRequest(normalizedConfiguration, endpoints);

	const response = await requestSISCIMD(authorizationUrl.toString(), { localDevelopmentCA, signal });
	if (response.statusCode !== 302) {
		throw new Error(`SIS authorization endpoint returned HTTP ${response.statusCode} instead of a redirect.`);
	}
	const location = firstHeaderValue(response.headers.location);
	if (location === undefined || location === '') {
		throw new Error('SIS authorization endpoint did not return a Location header.');
	}
	const cookieMaxAgeSeconds = extractCookieMaxAgeSeconds(response.headers['set-cookie']);
	if (cookieMaxAgeSeconds === undefined) {
		throw new Error('SIS authorization endpoint did not return a session cookie with a Max-Age.');
	}

	return { authorizationUrl: authorizationUrl.toString(), cookieMaxAgeSeconds, location };
}

function firstHeaderValue(value: string | string[] | undefined): string | undefined {
	return Array.isArray(value) ? value[0] : value;
}

function extractCookieMaxAgeSeconds(setCookieHeaders: string[] | undefined): number | undefined {
	if (setCookieHeaders === undefined) {
		return undefined;
	}
	for (const cookie of setCookieHeaders) {
		const match = /;\s*max-age=(\d+)/iu.exec(cookie);
		if (match) {
			return Number(match[1]);
		}
	}
	return undefined;
}

export async function authorizeWithSISCIMD(
	configuration: SISCIMDOAuthConfiguration,
	openExternal: (authorizationUrl: URL) => Promise<boolean | void>,
	signal?: AbortSignal,
): Promise<SISCIMDOAuthSession> {
	throwIfAuthorizationCancelled(signal);
	const { endpoints, localDevelopmentCA, normalizedConfiguration } = await resolveSISCIMDEndpoints(
		configuration,
		signal,
	);
	throwIfAuthorizationCancelled(signal);
	const { authorizationUrl, state, verifier } = buildAuthorizationRequest(normalizedConfiguration, endpoints);

	const callbackServer = await startCallbackServer(state, normalizedConfiguration.issuer, signal);
	try {
		const opened = await openExternal(authorizationUrl);
		if (opened === false) {
			throw new Error('The SIS sign-in page could not be opened.');
		}

		const callback = await callbackServer.result;
		try {
			const session = await exchangeAuthorizationCode(
				normalizedConfiguration,
				endpoints.tokenEndpoint,
				callback.code,
				verifier,
				localDevelopmentCA,
				signal,
			);
			throwIfAuthorizationCancelled(signal);
			writeCallbackPage(callback.response, 200, 'Sign-in complete', 'You can return to Visual Studio Code.');
			return session;
		} catch (error) {
			writeCallbackPage(callback.response, 502, 'Sign-in could not be completed', 'Return to Visual Studio Code and try again.');
			throw error;
		}
	} finally {
		await callbackServer.close();
	}
}

export function validateClientID(rawClientId: string): string {
	if (
		rawClientId === ''
		|| Buffer.byteLength(rawClientId, 'utf8') > 512
		|| rawClientId !== rawClientId.trim()
		|| !rawClientId.startsWith('https://')
		|| rawClientId.includes('?')
		|| rawClientId.includes('#')
	) {
		throw new Error('SIS CIMD client ID must be an exact HTTPS URL.');
	}
	let parsed: URL;
	try {
		parsed = new URL(rawClientId);
	} catch {
		throw new Error('SIS CIMD client ID must be an exact HTTPS URL.');
	}
	if (parsed.protocol !== 'https:' || parsed.hostname === '') {
		throw new Error('SIS CIMD client ID must be an exact HTTPS URL.');
	}
	if (parsed.username !== '' || parsed.password !== '' || parsed.search !== '' || parsed.hash !== '') {
		throw new Error('SIS CIMD client ID must not contain userinfo, a query, or a fragment.');
	}
	if (parsed.pathname === '' || parsed.pathname === '/') {
		throw new Error('SIS CIMD client ID must include a non-root path.');
	}
	return rawClientId;
}

export function normalizeIssuer(rawIssuer: string): string {
	if (
		rawIssuer === ''
		|| rawIssuer !== rawIssuer.trim()
		|| rawIssuer.includes('?')
		|| rawIssuer.includes('#')
	) {
		throw new Error('SIS issuer is required and must not contain surrounding whitespace.');
	}
	let parsed: URL;
	try {
		parsed = new URL(rawIssuer);
	} catch {
		throw new Error('SIS issuer must be an absolute URL.');
	}
	if (parsed.username !== '' || parsed.password !== '' || parsed.search !== '' || parsed.hash !== '') {
		throw new Error('SIS issuer must not contain userinfo, a query, or a fragment.');
	}
	if (parsed.protocol === 'http:') {
		if (!isLoopbackHost(parsed.hostname)) {
			throw new Error('SIS issuer may use HTTP only for loopback development hosts.');
		}
	} else if (parsed.protocol !== 'https:') {
		throw new Error('SIS issuer must use HTTPS.');
	}
	if (parsed.pathname === '/') {
		parsed.pathname = '';
	} else {
		parsed.pathname = parsed.pathname.replace(/\/+$/u, '');
	}
	return parsed.toString().replace(/\/$/u, '');
}

export function parseSISCIMDOAuthSession(raw: unknown): SISCIMDOAuthSession | undefined {
	let value = raw;
	if (typeof raw === 'string') {
		try {
			value = JSON.parse(raw);
		} catch {
			return undefined;
		}
	}
	if (!isRecord(value)) {
		return undefined;
	}

	const accessToken = nonemptyString(value.accessToken);
	const clientId = nonemptyString(value.clientId);
	const connectedAt = validDateString(value.connectedAt);
	const issuer = nonemptyString(value.issuer);
	const redirectUri = nonemptyString(value.redirectUri);
	const scope = stringValue(value.scope);
	const tokenType = nonemptyString(value.tokenType);
	if (
		accessToken === undefined
		|| clientId === undefined
		|| connectedAt === undefined
		|| issuer === undefined
		|| redirectUri === undefined
		|| scope === undefined
		|| tokenType?.toLowerCase() !== 'bearer'
	) {
		return undefined;
	}

	let normalizedIssuer: string;
	try {
		validateClientID(clientId);
		normalizedIssuer = normalizeIssuer(issuer);
	} catch {
		return undefined;
	}
	if (redirectUri !== sisCIMDOAuthRedirectUri) {
		return undefined;
	}

	const expiresAt = validDateString(value.expiresAt);
	const idToken = optionalNonemptyString(value.idToken);
	const refreshToken = optionalNonemptyString(value.refreshToken);
	if (expiresAt === undefined || idToken === null || refreshToken === null) {
		return undefined;
	}

	return {
		accessToken,
		clientId,
		connectedAt,
		expiresAt,
		idToken,
		issuer: normalizedIssuer,
		redirectUri,
		refreshToken,
		scope: normalizeScope(scope),
		tokenType: 'Bearer',
	};
}

export function sisCIMDOAuthSessionMatchesConfiguration(
	session: SISCIMDOAuthSession,
	configuration: SISCIMDOAuthConfiguration,
	now: Date = new Date(),
): boolean {
	let normalized: SISCIMDOAuthConfiguration;
	const parsedSession = parseSISCIMDOAuthSession(session);
	if (parsedSession === undefined || Number.isNaN(now.getTime())) {
		return false;
	}
	try {
		normalized = normalizeConfiguration(configuration);
	} catch {
		return false;
	}
	if (
		parsedSession.clientId !== normalized.clientId
		|| parsedSession.issuer !== normalized.issuer
		|| parsedSession.redirectUri !== normalized.redirectUri
	) {
		return false;
	}
	if (new Date(parsedSession.expiresAt).getTime() <= now.getTime()) {
		return false;
	}
	return scopeSetsEqual(parsedSession.scope, normalized.scope);
}

export type SISCIMDSessionPhase = 'disconnected' | 'pending' | 'connected' | 'error';

export type SISCIMDSessionStatus = {
	connectedAt?: string;
	error?: string;
	expiresAt?: string;
	issuer?: string;
	phase: SISCIMDSessionPhase;
	scope?: string;
};

// Narrow, structural subset of vscode.SecretStorage -- keeping this module free of a
// `vscode` import is what lets it (and this session-storage round trip) be exercised by
// a plain Node test, unlike extension.ts, which cannot be imported outside the extension
// host.
export interface SISCIMDSessionSecretStorage {
	delete(key: string): PromiseLike<void>;
	get(key: string): PromiseLike<string | undefined>;
	store(key: string, value: string): PromiseLike<void>;
}

export async function loadStoredSISCIMDOAuthSession(
	secrets: SISCIMDSessionSecretStorage,
	configuration: SISCIMDOAuthConfiguration,
): Promise<SISCIMDOAuthSession | undefined> {
	const stored = await secrets.get(sisCIMDOAuthSessionSecretStorageKey);
	if (stored === undefined) {
		return undefined;
	}
	try {
		const session = parseSISCIMDOAuthSession(stored);
		return session !== undefined && sisCIMDOAuthSessionMatchesConfiguration(session, configuration)
			? session
			: undefined;
	} catch {
		return undefined;
	}
}

// Mirrors sisCIMDSessionStatus in observer/internal/api/sis_cimd_login.go: redacted,
// non-secret session status shared with CloudTab.tsx over the bridge, the same shape
// Observer's own /api/splunk/cimd/session returns for the no-bridge path. The stored
// session's accessToken/idToken/refreshToken are deliberately never read here.
export async function computeSISCIMDSessionStatus(
	secrets: SISCIMDSessionSecretStorage,
	configuration: SISCIMDOAuthConfiguration,
	signInPending: boolean,
): Promise<SISCIMDSessionStatus> {
	const session = await loadStoredSISCIMDOAuthSession(secrets, configuration);
	if (session === undefined) {
		return { phase: signInPending ? 'pending' : 'disconnected' };
	}
	return {
		connectedAt: session.connectedAt,
		expiresAt: session.expiresAt,
		issuer: session.issuer,
		phase: 'connected',
		scope: session.scope,
	};
}

export async function storeSISCIMDOAuthSession(
	secrets: SISCIMDSessionSecretStorage,
	session: SISCIMDOAuthSession,
): Promise<void> {
	await secrets.store(sisCIMDOAuthSessionSecretStorageKey, JSON.stringify(session));
}

export async function deleteSISCIMDOAuthSession(secrets: SISCIMDSessionSecretStorage): Promise<void> {
	await secrets.delete(sisCIMDOAuthSessionSecretStorageKey);
}

export function requestSISCIMD(rawUrl: string, options: SISCIMDRequestOptions = {}): Promise<SISCIMDResponse> {
	return new Promise((resolve, reject) => {
		if (options.signal?.aborted === true) {
			reject(authorizationCancelledError());
			return;
		}
		let target: URL;
		try {
			target = new URL(rawUrl);
		} catch {
			reject(new Error('SIS OAuth request URL is invalid.'));
			return;
		}
		if (target.protocol !== 'https:' && !(target.protocol === 'http:' && isLoopbackHost(target.hostname))) {
			reject(new Error('SIS OAuth requests require HTTPS, except on loopback development hosts.'));
			return;
		}

		const method = options.method ?? 'GET';
		const client = target.protocol === 'https:' ? https : http;
		const localDevelopmentCA = target.protocol === 'https:' && isLoopbackHost(target.hostname)
			? options.localDevelopmentCA
			: undefined;
		const request = client.request(target, {
			agent: localDevelopmentCA === undefined ? undefined : false,
			ca: localDevelopmentCA,
			headers: options.headers,
			method,
			signal: options.signal,
		}, (response) => {
			const chunks: Buffer[] = [];
			let byteCount = 0;
			let responseFinished = false;
			response.on('data', (chunk: Buffer | string) => {
				const buffer = Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk);
				byteCount += buffer.byteLength;
				if (byteCount > (options.maxBodyBytes ?? maxResponseBodyBytes)) {
					responseFinished = true;
					const error = new Error('SIS OAuth response exceeded the 64 KiB limit.');
					response.destroy(error);
					request.destroy(error);
					return;
				}
				chunks.push(buffer);
			});
			response.once('error', (error) => {
				if (!responseFinished) {
					responseFinished = true;
					clearTimeout(timeout);
					reject(options.signal?.aborted === true ? authorizationCancelledError() : error);
				}
			});
			response.once('end', () => {
				if (responseFinished) {
					return;
				}
				responseFinished = true;
				clearTimeout(timeout);
				resolve({
					body: Buffer.concat(chunks).toString('utf8'),
					headers: response.headers,
					statusCode: response.statusCode ?? 0,
				});
			});
		});
		const timeout = setTimeout(() => {
			request.destroy(new Error('Timed out waiting for SIS OAuth.'));
		}, options.timeoutMs ?? defaultRequestTimeoutMs);
		request.once('error', (error) => {
			clearTimeout(timeout);
			reject(options.signal?.aborted === true ? authorizationCancelledError() : error);
		});
		request.end(options.body);
	});
}

function normalizeConfiguration(configuration: SISCIMDOAuthConfiguration): SISCIMDOAuthConfiguration {
	const clientId = validateClientID(configuration.clientId);
	const issuer = normalizeIssuer(configuration.issuer);
	const developmentCaBundlePath = configuration.developmentCaBundlePath?.trim() || undefined;
	if (configuration.redirectUri !== sisCIMDOAuthRedirectUri) {
		throw new Error(`SIS CIMD redirect URI must be exactly ${sisCIMDOAuthRedirectUri}.`);
	}
	const scope = normalizeScope(configuration.scope);
	if (scope === '') {
		throw new Error('At least one SIS OAuth scope is required.');
	}
	return { clientId, developmentCaBundlePath, issuer, redirectUri: configuration.redirectUri, scope };
}

async function loadLocalDevelopmentCA(
	configuration: SISCIMDOAuthConfiguration,
): Promise<string[] | undefined> {
	const bundlePath = configuration.developmentCaBundlePath;
	if (bundlePath === undefined) {
		return undefined;
	}

	const clientHost = new URL(configuration.clientId).hostname;
	const issuerHost = new URL(configuration.issuer).hostname;
	if (!isLoopbackHost(clientHost) || !isLoopbackHost(issuerHost)) {
		throw new Error(
			'The SIS development CA bundle may be used only when both the issuer and client ID use loopback hosts.',
		);
	}
	if (!path.isAbsolute(bundlePath)) {
		throw new Error('The SIS development CA bundle path must be absolute.');
	}

	let bundle: string;
	try {
		bundle = await readBoundedPEMFile(bundlePath);
	} catch (error) {
		const message = error instanceof Error ? error.message : String(error);
		throw new Error(`Could not read the SIS development CA bundle: ${message}`);
	}
	const certificates = bundle.match(pemCertificatePattern) ?? [];
	if (certificates.length === 0 || bundle.replace(pemCertificatePattern, '').trim() !== '') {
		throw new Error('The SIS development CA bundle is not valid PEM certificate data.');
	}
	try {
		for (const certificate of certificates) {
			const parsed = new crypto.X509Certificate(certificate);
			// A proper CA certificate is always accepted. A self-signed leaf is also accepted --
			// SIS's own dev-mode server (sis-core's loadOrCreateDevTLSCert) only ever generates a
			// bare self-signed cert with no CA basic constraint, so requiring CA:TRUE here would
			// make this feature unusable against a stock local SIS dev server. A leaf certificate
			// issued by a *different* certificate (i.e. not self-signed) is still rejected --
			// verify(), not string comparison, so a forged issuer/subject match can't pass.
			const isSelfSigned = parsed.subject === parsed.issuer && parsed.verify(parsed.publicKey);
			if (!parsed.ca && !isSelfSigned) {
				throw new Error('The SIS development CA bundle must contain only CA or self-signed certificates.');
			}
		}
	} catch (error) {
		if (error instanceof Error && error.message.includes('must contain only CA or self-signed certificates')) {
			throw error;
		}
		throw new Error('The SIS development CA bundle is not valid PEM certificate data.');
	}

	const standardTrustedRoots = typeof tls.getCACertificates === 'function'
		? tls.getCACertificates('default')
		: tls.rootCertificates;
	return [...standardTrustedRoots, ...certificates];
}

async function readBoundedPEMFile(bundlePath: string): Promise<string> {
	const handle = await fs.open(bundlePath, 'r');
	try {
		const stat = await handle.stat();
		if (!stat.isFile()) {
			throw new Error('path does not identify a regular file');
		}
		if (stat.size > maxDevelopmentCaBundleBytes) {
			throw new Error(`file exceeds the ${maxDevelopmentCaBundleBytes}-byte limit`);
		}

		const contents = Buffer.alloc(maxDevelopmentCaBundleBytes + 1);
		let totalBytes = 0;
		while (totalBytes < contents.byteLength) {
			const { bytesRead } = await handle.read(
				contents,
				totalBytes,
				contents.byteLength - totalBytes,
				null,
			);
			if (bytesRead === 0) {
				break;
			}
			totalBytes += bytesRead;
		}
		if (totalBytes > maxDevelopmentCaBundleBytes) {
			throw new Error(`file exceeds the ${maxDevelopmentCaBundleBytes}-byte limit`);
		}
		const bundle = contents.subarray(0, totalBytes).toString('utf8');
		if (bundle.trim() === '') {
			throw new Error('file is empty');
		}
		return bundle;
	} finally {
		await handle.close();
	}
}

function validateClientMetadata(value: Record<string, unknown>, configuration: SISCIMDOAuthConfiguration): void {
	const metadata = value as ClientMetadata;
	if (metadata.client_id !== configuration.clientId) {
		throw new Error('CIMD client metadata client_id did not exactly match its URL.');
	}
	const redirectUris = requiredStringArray(metadata.redirect_uris, 'CIMD redirect_uris');
	for (const redirectUri of redirectUris) {
		validateMetadataRedirectUri(redirectUri);
	}
	if (!redirectUris.includes(configuration.redirectUri)) {
		throw new Error('CIMD client metadata does not declare the fixed loopback callback.');
	}
	if (
		metadata.token_endpoint_auth_method !== undefined
		&& metadata.token_endpoint_auth_method !== 'none'
	) {
		throw new Error('CIMD clients must use token_endpoint_auth_method "none".');
	}
	if (metadata.grant_types !== undefined) {
		const grantTypes = requiredStringArray(metadata.grant_types, 'CIMD grant_types');
		if (!grantTypes.includes('authorization_code')) {
			throw new Error('CIMD client metadata must allow the authorization_code grant.');
		}
	}
	if (metadata.response_types !== undefined) {
		const responseTypes = requiredStringArray(metadata.response_types, 'CIMD response_types');
		if (!responseTypes.includes('code')) {
			throw new Error('CIMD client metadata must allow the code response type.');
		}
	}
	if (typeof metadata.scope !== 'string') {
		throw new Error('CIMD client metadata scope must be a string.');
	}
	const declaredScopes = scopeSet(metadata.scope);
	for (const requestedScope of scopeSet(configuration.scope)) {
		if (!declaredScopes.has(requestedScope)) {
			throw new Error(`CIMD client metadata does not declare requested scope "${requestedScope}".`);
		}
	}
}

function validateMetadataRedirectUri(rawRedirectUri: string): void {
	let redirectUri: URL;
	try {
		redirectUri = new URL(rawRedirectUri);
	} catch {
		throw new Error(`CIMD client metadata redirect URI "${rawRedirectUri}" is invalid.`);
	}
	if (redirectUri.username !== '' || redirectUri.password !== '') {
		throw new Error('CIMD client metadata redirect URIs must not contain userinfo.');
	}
	if (rawRedirectUri.startsWith('https://') && redirectUri.protocol === 'https:') {
		return;
	}
	if (
		rawRedirectUri.startsWith('http://')
		&& redirectUri.protocol === 'http:'
		&& isSISMetadataLoopbackHost(redirectUri.hostname)
	) {
		return;
	}
	throw new Error('CIMD client metadata redirect URIs must use HTTPS or plain loopback HTTP.');
}

function validateDiscoveryDocument(
	value: Record<string, unknown>,
	configuration: SISCIMDOAuthConfiguration,
): ValidatedDiscovery {
	const discovery = value as DiscoveryDocument;
	if (discovery.issuer !== configuration.issuer) {
		throw new Error('SIS discovery issuer did not exactly match the configured issuer.');
	}
	if (discovery.client_id_metadata_document_supported !== true) {
		throw new Error('SIS discovery does not advertise CIMD support.');
	}
	if (Object.prototype.hasOwnProperty.call(discovery, 'registration_endpoint')) {
		throw new Error('SIS discovery unexpectedly advertises dynamic client registration.');
	}
	requireArrayMember(discovery.token_endpoint_auth_methods_supported, 'none', 'token endpoint auth method');
	requireArrayMember(discovery.grant_types_supported, 'authorization_code', 'grant type');
	requireArrayMember(discovery.response_types_supported, 'code', 'response type');
	requireArrayMember(discovery.code_challenge_methods_supported, 'S256', 'PKCE method');
	const supportedScopes = new Set(requiredStringArray(discovery.scopes_supported, 'SIS scopes_supported'));
	for (const requestedScope of scopeSet(configuration.scope)) {
		if (!supportedScopes.has(requestedScope)) {
			throw new Error(`SIS discovery does not support requested scope "${requestedScope}".`);
		}
	}

	return {
		authorizationEndpoint: validateOAuthEndpoint(discovery.authorization_endpoint, 'authorization_endpoint'),
		tokenEndpoint: validateOAuthEndpoint(discovery.token_endpoint, 'token_endpoint'),
	};
}

function validateOAuthEndpoint(value: unknown, field: string): string {
	if (typeof value !== 'string' || value === '') {
		throw new Error(`SIS discovery ${field} is missing.`);
	}
	let endpoint: URL;
	try {
		endpoint = new URL(value);
	} catch {
		throw new Error(`SIS discovery ${field} is invalid.`);
	}
	if (endpoint.username !== '' || endpoint.password !== '' || endpoint.hash !== '') {
		throw new Error(`SIS discovery ${field} is invalid.`);
	}
	if (endpoint.protocol === 'http:') {
		if (!isLoopbackHost(endpoint.hostname)) {
			throw new Error(`SIS discovery ${field} must use HTTPS.`);
		}
	} else if (endpoint.protocol !== 'https:') {
		throw new Error(`SIS discovery ${field} must use HTTPS.`);
	}
	return endpoint.toString();
}

function requireArrayMember(value: unknown, member: string, label: string): void {
	const values = requiredStringArray(value, `SIS ${label}s`);
	if (!values.includes(member)) {
		throw new Error(`SIS discovery does not support ${label} "${member}".`);
	}
}

function requiredStringArray(value: unknown, field: string): string[] {
	if (!Array.isArray(value) || value.length === 0 || !value.every((item) => typeof item === 'string')) {
		throw new Error(`${field} must be a non-empty string array.`);
	}
	return value;
}

function parseJSONObject(response: SISCIMDResponse, label: string): Record<string, unknown> {
	if (response.statusCode < 200 || response.statusCode >= 300) {
		throw new Error(`${label} request failed with HTTP ${response.statusCode}.`);
	}
	let value: unknown;
	try {
		value = JSON.parse(response.body);
	} catch {
		throw new Error(`${label} was not valid JSON.`);
	}
	if (!isRecord(value)) {
		throw new Error(`${label} must be a JSON object.`);
	}
	return value;
}

async function exchangeAuthorizationCode(
	configuration: SISCIMDOAuthConfiguration,
	tokenEndpoint: string,
	code: string,
	verifier: string,
	localDevelopmentCA?: string[],
	signal?: AbortSignal,
): Promise<SISCIMDOAuthSession> {
	const form = new URLSearchParams();
	form.set('grant_type', 'authorization_code');
	form.set('code', code);
	form.set('code_verifier', verifier);
	form.set('redirect_uri', configuration.redirectUri);
	form.set('client_id', configuration.clientId);
	const body = form.toString();
	const response = await requestSISCIMD(tokenEndpoint, {
		body,
		headers: {
			Accept: 'application/json',
			'Content-Length': String(Buffer.byteLength(body)),
			'Content-Type': 'application/x-www-form-urlencoded',
		},
		localDevelopmentCA,
		method: 'POST',
		signal,
	});
	const token = parseJSONObject(response, 'SIS token endpoint response') as TokenResponse;
	const accessToken = nonemptyString(token.access_token);
	const tokenType = nonemptyString(token.token_type);
	if (accessToken === undefined || tokenType?.toLowerCase() !== 'bearer') {
		throw new Error('SIS token endpoint returned an invalid bearer token response.');
	}

	const scope = token.scope === undefined ? configuration.scope : nonemptyString(token.scope);
	if (scope === undefined) {
		throw new Error('SIS token endpoint returned an invalid scope.');
	}
	const grantedScopes = scopeSet(scope);
	const requestedScopes = scopeSet(configuration.scope);
	for (const requestedScope of requestedScopes) {
		if (!grantedScopes.has(requestedScope)) {
			throw new Error(`SIS token response omitted requested scope "${requestedScope}".`);
		}
	}
	for (const grantedScope of grantedScopes) {
		if (!requestedScopes.has(grantedScope)) {
			throw new Error(`SIS token response included unrequested scope "${grantedScope}".`);
		}
	}

	const connectedAt = new Date();
	if (typeof token.expires_in !== 'number' || !Number.isFinite(token.expires_in) || token.expires_in <= 0) {
		throw new Error('SIS token endpoint returned an invalid expires_in value.');
	}
	const expiresAt = new Date(connectedAt.getTime() + token.expires_in * 1000).toISOString();

	const idToken = optionalNonemptyString(token.id_token);
	const refreshToken = optionalNonemptyString(token.refresh_token);
	if (idToken === null || refreshToken === null) {
		throw new Error('SIS token endpoint returned an invalid token value.');
	}
	return {
		accessToken,
		clientId: configuration.clientId,
		connectedAt: connectedAt.toISOString(),
		expiresAt,
		idToken,
		issuer: configuration.issuer,
		redirectUri: configuration.redirectUri,
		refreshToken,
		scope: normalizeScope(scope),
		tokenType: 'Bearer',
	};
}

async function startCallbackServer(
	expectedState: string,
	expectedIssuer: string,
	signal?: AbortSignal,
): Promise<CallbackServer> {
	let settleResult: ((value: CallbackResult) => void) | undefined;
	let settleError: ((reason: Error) => void) | undefined;
	let settled = false;
	let authorizationTimer: NodeJS.Timeout;
	const result = new Promise<CallbackResult>((resolve, reject) => {
		settleResult = resolve;
		settleError = reject;
	});
	void result.catch(() => undefined);

	const fail = (error: Error): void => {
		if (settled) {
			return;
		}
		settled = true;
		clearTimeout(authorizationTimer);
		settleError?.(error);
	};
	const server = http.createServer((request, response) => {
		setCallbackHeaders(response);
		if (request.method !== 'GET') {
			writeCallbackPage(response, 405, 'Unsupported request', 'Return to Visual Studio Code and try again.');
			return;
		}
		const callbackUrl = new URL(request.url ?? '/', sisCIMDOAuthRedirectUri);
		if (callbackUrl.pathname !== '/callback') {
			writeCallbackPage(response, 404, 'Not found', 'This local callback only accepts the SIS sign-in response.');
			return;
		}
		if (settled) {
			writeCallbackPage(response, 409, 'Sign-in response already received', 'You can close this page.');
			return;
		}
		if (callbackUrl.searchParams.get('state') !== expectedState) {
			// Reject only this request, without settling the flow: port
			// sisCIMDOAuthRedirectUri's port is fixed and well-known, so any unrelated
			// local process or a page the user has open elsewhere can hit it without ever
			// knowing expectedState. Calling fail() here would let a single such request
			// reliably deny sign-in before the real SIS redirect arrives.
			writeCallbackPage(response, 400, 'Sign-in could not be verified', 'Return to Visual Studio Code and try again.');
			return;
		}
		const oauthError = callbackUrl.searchParams.get('error');
		if (oauthError !== null) {
			writeCallbackPage(response, 400, 'Sign-in was not completed', 'Return to Visual Studio Code and try again.');
			const safeError = /^[A-Za-z0-9._-]{1,64}$/u.test(oauthError) ? oauthError : 'unknown_error';
			fail(new Error(`SIS authorization failed (${safeError}).`));
			return;
		}
		const callbackIssuer = callbackUrl.searchParams.get('iss');
		if (callbackIssuer !== null && callbackIssuer !== expectedIssuer) {
			writeCallbackPage(response, 400, 'Sign-in could not be verified', 'Return to Visual Studio Code and try again.');
			fail(new Error('SIS OAuth callback issuer did not match.'));
			return;
		}
		const code = callbackUrl.searchParams.get('code');
		if (code === null || code === '') {
			writeCallbackPage(response, 400, 'Sign-in response was incomplete', 'Return to Visual Studio Code and try again.');
			fail(new Error('SIS OAuth callback did not include an authorization code.'));
			return;
		}

		settled = true;
		clearTimeout(authorizationTimer);
		settleResult?.({ code, response });
	});
	server.headersTimeout = 5_000;
	server.requestTimeout = 5_000;
	server.keepAliveTimeout = 1_000;

	await new Promise<void>((resolve, reject) => {
		const onError = (error: Error): void => {
			server.off('listening', onListening);
			reject(new Error(`Could not start the SIS OAuth callback server: ${error.message}`));
		};
		const onListening = (): void => {
			server.off('error', onError);
			resolve();
		};
		server.once('error', onError);
		server.once('listening', onListening);
		server.listen(33418, '127.0.0.1');
	});
	server.on('error', (error) => fail(new Error(`SIS OAuth callback server failed: ${error.message}`)));
	authorizationTimer = setTimeout(() => fail(new Error('Timed out waiting for SIS authorization.')), authorizationTimeoutMs);
	const onAbort = (): void => fail(new Error('SIS sign-in was cancelled.'));
	signal?.addEventListener('abort', onAbort, { once: true });
	if (signal?.aborted === true) {
		onAbort();
	}

	return {
		close: async () => {
			signal?.removeEventListener('abort', onAbort);
			clearTimeout(authorizationTimer);
			if (!settled) {
				settled = true;
				settleError?.(new Error('SIS OAuth callback server closed before authorization completed.'));
			}
			await closeServer(server);
		},
		result,
	};
}

function throwIfAuthorizationCancelled(signal?: AbortSignal): void {
	if (signal?.aborted === true) {
		throw authorizationCancelledError();
	}
}

function authorizationCancelledError(): Error {
	return new Error('SIS sign-in was cancelled.');
}

function closeServer(server: http.Server): Promise<void> {
	return new Promise((resolve) => {
		let finished = false;
		const finish = (): void => {
			if (finished) {
				return;
			}
			finished = true;
			clearTimeout(forceClose);
			resolve();
		};
		const forceClose = setTimeout(() => {
			server.closeAllConnections();
			finish();
		}, 1_000);
		server.close(finish);
		server.closeIdleConnections();
	});
}

function setCallbackHeaders(response: http.ServerResponse): void {
	response.setHeader('Cache-Control', 'no-store');
	response.setHeader('Content-Security-Policy', "default-src 'none'; frame-ancestors 'none'; sandbox");
	response.setHeader('Referrer-Policy', 'no-referrer');
	response.setHeader('X-Content-Type-Options', 'nosniff');
}

function writeCallbackPage(response: http.ServerResponse, statusCode: number, title: string, message: string): void {
	if (response.writableEnded) {
		return;
	}
	setCallbackHeaders(response);
	response.statusCode = statusCode;
	response.setHeader('Content-Type', 'text/html; charset=utf-8');
	response.end(`<!doctype html><html><head><meta charset="utf-8"><title>${escapeHTML(title)}</title></head><body><h1>${escapeHTML(title)}</h1><p>${escapeHTML(message)}</p></body></html>`);
}

function escapeHTML(value: string): string {
	return value.replace(/[&<>"']/gu, (character) => ({
		'&': '&amp;',
		'"': '&quot;',
		"'": '&#39;',
		'<': '&lt;',
		'>': '&gt;',
	})[character] ?? character);
}

function normalizeScope(rawScope: string): string {
	return Array.from(scopeSet(rawScope)).join(' ');
}

function scopeSet(rawScope: string): Set<string> {
	return new Set(rawScope.trim().split(/\s+/u).filter(Boolean));
}

function scopeSetsEqual(left: string, right: string): boolean {
	const leftScopes = scopeSet(left);
	const rightScopes = scopeSet(right);
	return leftScopes.size === rightScopes.size
		&& Array.from(leftScopes).every((scope) => rightScopes.has(scope));
}

function isLoopbackHost(hostname: string): boolean {
	const normalizedHostname = hostname.startsWith('[') && hostname.endsWith(']')
		? hostname.slice(1, -1)
		: hostname;
	if (normalizedHostname.toLowerCase() === 'localhost') {
		return true;
	}
	const address = net.isIP(normalizedHostname) === 0 ? undefined : normalizedHostname;
	return address === '127.0.0.1' || address === '::1';
}

function isSISMetadataLoopbackHost(hostname: string): boolean {
	return hostname.toLowerCase() === 'localhost' || hostname === '127.0.0.1';
}

function isRecord(value: unknown): value is Record<string, unknown> {
	return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function stringValue(value: unknown): string | undefined {
	return typeof value === 'string' ? value : undefined;
}

function nonemptyString(value: unknown): string | undefined {
	return typeof value === 'string' && value.trim() !== '' ? value : undefined;
}

function optionalNonemptyString(value: unknown): string | undefined | null {
	return value === undefined ? undefined : nonemptyString(value) ?? null;
}

function validDateString(value: unknown): string | undefined {
	if (typeof value !== 'string' || value === '' || Number.isNaN(new Date(value).getTime())) {
		return undefined;
	}
	return value;
}