export const splunkCloudConnectionSecretKey = 'splunkCloudConnection.v1';
export const maxCloudAccessTokenBytes = 4096;
export const maxCloudDestinationBytes = 2048;
export const maxFreeAccountFirstNameLength = 40;
export const maxFreeAccountLastNameLength = 40;
export const maxFreeAccountEmailLength = 80;

const supportedFreeAccountRegionRealms: Readonly<Record<string, string>> = Object.freeze({
	'us': 'us1',
	'Europe (Ireland)': 'eu0',
	'apac-au': 'au0',
});
export type FreeAccountSubmissionResult = {
	accountSetupPending?: boolean;
	intakeAcknowledged: boolean;
	realm: string;
	region: string;
};

export const cloudBridgeActions = [
	'connect',
	'create-free-account',
	'detect-free-account-region',
	'disconnect-cimd',
	'disconnect-o11y-oauth',
	'forget',
	'get-o11y-oauth-session',
	'initialize',
	'login-cimd',
	'login-o11y-oauth',
	'open-audit-report',
	'open-free-edition',
	'open-free-edition-terms',
	'open-ingest-token-help',
	'open-credential-storage-help',
	'open-hec-token-help',
	'open-splunk-platform-trial',
	'open-observability-cloud',
	'open-observability-metrics',
	'open-observability-traces',
	'open-splunk-search',
	'open-realm-help',
	'open-observability-cloud-demo',
	'open-observability-data-course',
	'open-observability-docs',
	'open-skill-docs',
	'register-o11y-oauth',
	'resolve-realm',
	'refresh',
	'set-enabled',
	'setup-cimd',
] as const;

export type CloudBridgeAction = typeof cloudBridgeActions[number];

export function cloudBridgeActionRequiresLifecycleSerialization(action: CloudBridgeAction): boolean {
	return action === 'connect'
		|| action === 'create-free-account'
		|| action === 'forget'
		|| action === 'initialize'
		|| action === 'refresh'
		|| action === 'set-enabled';
}

export class ObserverCloudResponseError extends Error {
	constructor(
		readonly statusCode: number,
		message: string,
		readonly code?: string,
		readonly retrySafe?: boolean,
		readonly platform?: string,
	) {
		super(message);
		this.name = 'ObserverCloudResponseError';
	}
}

export function parseObserverCloudResponseBody(statusCode: number, responseBody: string): unknown {
	if (responseBody === '') {
		return {};
	}
	try {
		return JSON.parse(responseBody) as unknown;
	} catch {
		if (statusCode < 200 || statusCode >= 300) {
			return {};
		}
		throw new Error(`Splunk Observability Studio returned an invalid response (HTTP ${statusCode}).`);
	}
}

export type ObserverCloudHTTPResponse = {
	body: unknown;
	statusCode: number;
};

export function observerCloudResponseError(
	statusCode: number,
	body: unknown,
): ObserverCloudResponseError {
	const response = typeof body === 'object' && body !== null
		? body as Record<string, unknown>
		: undefined;
	const message = typeof response?.error === 'string'
		? response.error
		: `Splunk Observability Studio request failed with HTTP ${statusCode}.`;
	return new ObserverCloudResponseError(
		statusCode,
		message,
		typeof response?.code === 'string' ? response.code : undefined,
		typeof response?.retrySafe === 'boolean' ? response.retrySafe : undefined,
		typeof response?.platform === 'string' ? response.platform : undefined,
	);
}

export function isSupportedFreeAccountRegion(value: string): boolean {
	return Object.hasOwn(supportedFreeAccountRegionRealms, value);
}

export function parseFreeAccountSubmissionResult(value: unknown): FreeAccountSubmissionResult | undefined {
	if (typeof value !== 'object' || value === null) {
		return undefined;
	}
	const response = value as Record<string, unknown>;
	const realm = typeof response.realm === 'string' ? response.realm.trim().toLowerCase() : '';
	const region = typeof response.region === 'string' ? response.region : '';
	const expectedRealm = supportedFreeAccountRegionRealms[region];
	if (
		typeof response.intakeAcknowledged !== 'boolean'
		|| (response.accountSetupPending !== undefined
			&& typeof response.accountSetupPending !== 'boolean')
		|| expectedRealm === undefined
		|| realm !== expectedRealm
	) {
		return undefined;
	}
	return {
		...(response.accountSetupPending === undefined
			? {}
			: { accountSetupPending: response.accountSetupPending }),
		intakeAcknowledged: response.intakeAcknowledged,
		realm,
		region,
	};
}

export function freeAccountSubmissionFailureIsOutcomeUnknown(error: unknown): boolean {
	if (!(error instanceof ObserverCloudResponseError)) {
		return false;
	}
	if (error.retrySafe === true) {
		return false;
	}
	if (error.code === 'outcome_unknown' || error.retrySafe === false || error.statusCode >= 500) {
		return true;
	}
	return false;
}

/**
 * Path Splunk Observability Studio serves the $otel-audit HTML report from.
 *
 * The webview asks for "the audit report", never for a URL, so the extension
 * decides what gets opened. The path is fixed here rather than passed in so a
 * compromised webview cannot turn this into an open redirect against the
 * collector's own origin.
 */
export const auditReportPath = '/api/audit/report';

/** Builds the audit report URL for a collector base URL, or undefined. */
export function auditReportUrl(baseUrl: unknown): string | undefined {
	if (typeof baseUrl !== 'string' || baseUrl.trim() === '') {
		return undefined;
	}
	let parsed: URL;
	try {
		parsed = new URL(baseUrl);
	} catch {
		return undefined;
	}
	if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') {
		return undefined;
	}

	return new URL(auditReportPath, parsed).toString();
}

/**
 * Skills whose documentation the webview may ask the extension to open. The
 * webview names a skill, never a URL — the extension owns the URL mapping so a
 * compromised webview cannot open an arbitrary page.
 */
export const skillDocsIds = [
	'otel-audit',
	'otel-instrument',
	'otel-verify',
	'splunk-configure',
	'splunk-detector-publish',
	'splunk-dashboard-publish',
] as const;

export type SkillDocsId = typeof skillDocsIds[number];

/**
 * Documentation URL per skill id. The mapping lives here, beside the id list,
 * so a new id cannot be added without a URL and so both are testable without a
 * VS Code host.
 */
const skillDocsUrls: Record<SkillDocsId, string> = {
	'otel-audit': 'https://github.com/signalfx/obstudio/blob/main/skills/otel-audit/SKILL.md',
	'otel-instrument': 'https://github.com/signalfx/obstudio/blob/main/skills/otel-instrument/SKILL.md',
	'otel-verify': 'https://github.com/signalfx/obstudio/blob/main/skills/otel-verify/SKILL.md',
	'splunk-configure': 'https://github.com/signalfx/obstudio/blob/main/skills/splunk-configure/SKILL.md',
	'splunk-detector-publish': 'https://github.com/signalfx/obstudio/blob/main/skills/splunk-detector-publish/SKILL.md',
	'splunk-dashboard-publish': 'https://github.com/signalfx/obstudio/blob/main/skills/splunk-dashboard-publish/SKILL.md',
};

/** Returns the docs URL for a skill id, or undefined when the id is unknown. */
export function skillDocsUrl(skill: unknown): string | undefined {
	return isSkillDocsId(skill) ? skillDocsUrls[skill] : undefined;
}

export type StoredSplunkCloudConnection = {
	accessToken: string;
	realm: string;
};

function cloudErrorMessage(error: unknown): string {
	if (error instanceof Error) {
		return error.message;
	}
	return String(error);
}

export function isSkillDocsId(value: unknown): value is SkillDocsId {
	return typeof value === 'string' && (skillDocsIds as readonly string[]).includes(value);
}

export function parseStoredSplunkCloudConnection(value: string | undefined): StoredSplunkCloudConnection | undefined {
	if (value === undefined) {
		return undefined;
	}
	try {
		const parsed = JSON.parse(value) as Record<string, unknown>;
		if (
			typeof parsed.accessToken !== 'string'
			|| !isValidSplunkTokenSecret(parsed.accessToken)
			|| typeof parsed.realm !== 'string'
			|| !/^[a-z]{2,12}[0-9]+$/.test(parsed.realm)
		) {
			return undefined;
		}
		return {
			accessToken: parsed.accessToken,
			realm: parsed.realm,
		};
	} catch {
		return undefined;
	}
}

export function initializeSplunkCloudStatus(options: {
	isManagedObserver: boolean;
	readStatus: () => Promise<unknown>;
	refreshManagedStatus: () => Promise<unknown>;
}): Promise<unknown> {
	return options.isManagedObserver
		? options.refreshManagedStatus()
		: options.readStatus();
}

export type RegistrationAndAuthProtocol = 'NONE' | 'CIMD' | 'O11Y_OAUTH';

export type CloudBridgeInitializationResult<TSession, TOAuthSession = TSession> = {
	cimdSession?: TSession;
	o11yOAuthSession?: TOAuthSession;
	registrationAndAuthProtocol: RegistrationAndAuthProtocol;
	status: unknown;
	warning?: string;
	warningCode?: string;
};

// A rejected status refresh whose outcome is unknown must be surfaced to the webview as
// a distinct warning code rather than as a plain failure.
function outcomeUnknownWarningCode(reason: unknown): { warningCode?: string } {
	return (reason as { code?: string } | undefined)?.code === 'outcome_unknown'
		? { warningCode: 'outcome_unknown' }
		: {};
}

export async function initializeCloudBridgeState<TSession, TOAuthSession = TSession>(options: {
	readCimdSession: () => Promise<TSession>;
	readO11yOAuthSession: () => Promise<TOAuthSession>;
	readStatus: () => Promise<unknown>;
	refreshStatus: () => Promise<unknown>;
	registrationAndAuthProtocol: RegistrationAndAuthProtocol;
}): Promise<CloudBridgeInitializationResult<TSession, TOAuthSession>> {
	if (options.registrationAndAuthProtocol === 'CIMD') {
		const [refreshedStatus, initialCimdSession] = await Promise.allSettled([
			options.refreshStatus(),
			options.readCimdSession(),
		]);
		if (refreshedStatus.status === 'fulfilled' && initialCimdSession.status === 'fulfilled') {
			return {
				cimdSession: initialCimdSession.value,
				registrationAndAuthProtocol: 'CIMD',
				status: refreshedStatus.value,
			};
		}

		const warning = cloudErrorMessage(
			refreshedStatus.status === 'rejected'
				? refreshedStatus.reason
				: initialCimdSession.status === 'rejected'
					? initialCimdSession.reason
					: new Error('Cloud initialization failed'),
		);
		const [fallbackStatus, fallbackCimdSession] = await Promise.allSettled([
			refreshedStatus.status === 'fulfilled'
				? Promise.resolve(refreshedStatus.value)
				: options.readStatus(),
			initialCimdSession.status === 'fulfilled'
				? Promise.resolve(initialCimdSession.value)
				: options.readCimdSession(),
		]);
		if (fallbackStatus.status === 'rejected') {
			throw fallbackStatus.reason;
		}
		if (fallbackCimdSession.status === 'rejected') {
			throw fallbackCimdSession.reason;
		}
		return {
			cimdSession: fallbackCimdSession.value,
			registrationAndAuthProtocol: 'CIMD',
			status: fallbackStatus.value,
			warning,
			...(refreshedStatus.status === 'rejected' ? outcomeUnknownWarningCode(refreshedStatus.reason) : {}),
		};
	}

	if (options.registrationAndAuthProtocol === 'O11Y_OAUTH') {
		// Unlike CIMD's session (held in context.secrets, read natively by the extension),
		// O11Y_OAUTH's session lives in the Go backend's own in-memory, process-wide state
		// (see o11y_oauth_login.go) -- readO11yOAuthSession just proxies a GET to it, so this
		// restores "connected" across a webview reload within the same running backend
		// process, matching CIMD's restore semantics without needing extension-side storage.
		const [refreshedStatus, initialO11yOAuthSession] = await Promise.allSettled([
			options.refreshStatus(),
			options.readO11yOAuthSession(),
		]);
		if (refreshedStatus.status === 'fulfilled' && initialO11yOAuthSession.status === 'fulfilled') {
			return {
				o11yOAuthSession: initialO11yOAuthSession.value,
				registrationAndAuthProtocol: 'O11Y_OAUTH',
				status: refreshedStatus.value,
			};
		}

		const warning = cloudErrorMessage(
			refreshedStatus.status === 'rejected'
				? refreshedStatus.reason
				: initialO11yOAuthSession.status === 'rejected'
					? initialO11yOAuthSession.reason
					: new Error('Cloud initialization failed'),
		);
		const [fallbackStatus, fallbackO11yOAuthSession] = await Promise.allSettled([
			refreshedStatus.status === 'fulfilled'
				? Promise.resolve(refreshedStatus.value)
				: options.readStatus(),
			initialO11yOAuthSession.status === 'fulfilled'
				? Promise.resolve(initialO11yOAuthSession.value)
				: options.readO11yOAuthSession(),
		]);
		if (fallbackStatus.status === 'rejected') {
			throw fallbackStatus.reason;
		}
		if (fallbackO11yOAuthSession.status === 'rejected') {
			throw fallbackO11yOAuthSession.reason;
		}
		return {
			o11yOAuthSession: fallbackO11yOAuthSession.value,
			registrationAndAuthProtocol: 'O11Y_OAUTH',
			status: fallbackStatus.value,
			warning,
			...(refreshedStatus.status === 'rejected' ? outcomeUnknownWarningCode(refreshedStatus.reason) : {}),
		};
	}

	// NONE shows no control at all, so it skips any session round trip.
	try {
		return {
			registrationAndAuthProtocol: options.registrationAndAuthProtocol,
			status: await options.refreshStatus(),
		};
	} catch (error) {
		return {
			registrationAndAuthProtocol: options.registrationAndAuthProtocol,
			warning: cloudErrorMessage(error),
			...outcomeUnknownWarningCode(error),
			status: await options.readStatus(),
		};
	}
}

// Generic, injectable polling loop extracted so it can be unit tested without a real
// VS Code host or network -- extension.ts's waitForO11yOAuthSessionOutcome is a thin
// wrapper over this with the real session reader, real delay, and a real cancellation
// flag. 'disconnected' is a terminal outcome alongside 'connected'/'error': cancelling a
// sign-in posts a disconnect request that flips the backend to 'disconnected', and the
// loop must notice that (not just the isCancelled() flag) so a disconnect that completes
// before the extension's own cancellation bookkeeping still ends the wait promptly.
export async function waitForO11yOAuthLoginOutcome<TSession extends { phase: string }>(options: {
	delay: (ms: number) => Promise<void>;
	intervalMs: number;
	isCancelled: () => boolean;
	readSession: () => Promise<TSession>;
}): Promise<TSession> {
	for (;;) {
		const session = await options.readSession();
		if (
			options.isCancelled()
			|| session.phase === 'connected'
			|| session.phase === 'error'
			|| session.phase === 'disconnected'
		) {
			return session;
		}
		await options.delay(options.intervalMs);
	}
}

function isValidSplunkTokenSecret(value: string): boolean {
	return value.length > 0
		&& Buffer.byteLength(value, 'utf8') <= maxCloudAccessTokenBytes
		&& !/[\s\u0000-\u001F\u007F]/u.test(value);
}

export function cloudStatusConnected(value: unknown): boolean {
	return typeof value === 'object'
		&& value !== null
		&& (value as Record<string, unknown>).connected === true;
}

export function cloudStatusHasConfiguration(value: unknown): boolean {
	if (cloudStatusConnected(value)) {
		return true;
	}
	if (typeof value !== 'object' || value === null) {
		return false;
	}
	const status = value as Record<string, unknown>;
	return cloudSignalConfigured(status.metrics) === true
		|| cloudSignalConfigured(status.traces) === true;
}

export function splunkSearchURLFromStatus(value: unknown): string | undefined {
	if (!value || typeof value !== 'object') { return undefined; }
	const searchURL = (value as Record<string, unknown>).searchURL;
	if (typeof searchURL !== 'string') { return undefined; }
	try {
		const url = new URL(searchURL);
		if (url.protocol !== 'https:' || url.username || url.password) { return undefined; }
		return url.href;
	} catch { return undefined; }
}

function cloudSignalConfigured(value: unknown): boolean | undefined {
	if (typeof value !== 'object' || value === null) {
		return undefined;
	}
	const configured = (value as Record<string, unknown>).configured;
	return typeof configured === 'boolean' ? configured : undefined;
}

export function cloudStatusHasNoConfiguration(value: unknown): boolean {
	if (typeof value !== 'object' || value === null) {
		return false;
	}
	const status = value as Record<string, unknown>;
	return cloudSignalConfigured(status.metrics) === false
		&& cloudSignalConfigured(status.traces) === false;
}


export function cloudStatusVersion(value: unknown): string | undefined {
	if (typeof value !== 'object' || value === null) {
		return undefined;
	}
	const status = value as Record<string, unknown>;
	const version = status.cloudVersion ?? status.version;
	return typeof version === 'string' && /^[A-Za-z0-9_-]{43}$/.test(version)
		? version
		: undefined;
}
