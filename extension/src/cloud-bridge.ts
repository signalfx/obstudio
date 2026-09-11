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
	'forget',
	'initialize',
	'login-cimd',
	'open-audit-report',
	'open-free-edition',
	'open-free-edition-terms',
	'open-ingest-token-help',
	'open-realm-help',
	'open-observability-cloud-demo',
	'open-observability-data-course',
	'open-observability-docs',
	'open-skill-docs',
	'resolve-realm',
	'set-enabled',
	'setup-cimd',
] as const;

export type CloudBridgeAction = typeof cloudBridgeActions[number];

export function cloudBridgeActionRequiresLifecycleSerialization(action: CloudBridgeAction): boolean {
	return action === 'connect'
		|| action === 'create-free-account'
		|| action === 'forget'
		|| action === 'initialize'
		|| action === 'set-enabled';
}

export class ObserverCloudResponseError extends Error {
	constructor(
		readonly statusCode: number,
		message: string,
		readonly code?: string,
		readonly retrySafe?: boolean,
	) {
		super(message);
		this.name = 'ObserverCloudResponseError';
	}
}

export class StoredSplunkCloudConnectionRejectedError extends ObserverCloudResponseError {
	constructor(error: ObserverCloudResponseError) {
		super(error.statusCode, error.message);
		this.name = 'StoredSplunkCloudConnectionRejectedError';
	}
}

export class StoredSplunkCloudConnectionVerificationUnavailableError extends ObserverCloudResponseError {
	constructor(error: ObserverCloudResponseError) {
		super(error.statusCode, error.message);
		this.name = 'StoredSplunkCloudConnectionVerificationUnavailableError';
	}
}

/**
 * A 4xx response is an authoritative rejection, so the Observer did not apply
 * the requested mutation. Transport failures and 5xx responses have an
 * uncertain outcome and require restoring the previous Observer state.
 */
export function shouldRestoreObserverAfterCloudMutationFailure(error: unknown): boolean {
	return !(error instanceof ObserverCloudResponseError
		&& error.statusCode >= 400
		&& error.statusCode < 500);
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
		throw new Error(`Observer returned an invalid response (HTTP ${statusCode}).`);
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
		: `Observer request failed with HTTP ${statusCode}.`;
	return new ObserverCloudResponseError(
		statusCode,
		message,
		typeof response?.code === 'string' ? response.code : undefined,
		typeof response?.retrySafe === 'boolean' ? response.retrySafe : undefined,
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
 * Stored credentials must pass the same connection test as newly entered
 * credentials before the Observer applies them. A transient upstream failure
 * remains distinct so the IDE can show the disconnected status and a warning
 * without disabling authenticated Cloud controls.
 */
export async function verifyStoredSplunkCloudConnection(
	verify: () => Promise<unknown>,
): Promise<unknown> {
	try {
		return await verify();
	} catch (error) {
		if (error instanceof ObserverCloudResponseError && error.statusCode === 401) {
			throw new StoredSplunkCloudConnectionRejectedError(error);
		}
		if (error instanceof ObserverCloudResponseError
			&& (error.statusCode === 502 || error.statusCode === 504)) {
			throw new StoredSplunkCloudConnectionVerificationUnavailableError(error);
		}
		throw error;
	}
}

/**
 * Path the Observer serves the $otel-audit HTML report from.
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

export type RestoreSplunkCloudConnectionOptions = {
	configure: (
		connection: StoredSplunkCloudConnection,
		expectedVersion: string | undefined,
	) => Promise<unknown>;
	readConnection: () => Promise<StoredSplunkCloudConnection | undefined>;
	readExportEnabled: () => boolean | undefined;
	refresh: () => Promise<unknown>;
	restoreStoredConnection: boolean;
	setEnabled: (enabled: boolean, expectedVersion: string | undefined) => Promise<unknown>;
};

type SplunkCloudExportPreference = {
	revision: number;
	state: 'committed' | 'pending' | 'rejected';
	value: boolean | undefined;
};

type SplunkCloudStoredConnection = {
	revision: number;
	state: 'committed' | 'pending' | 'rejected';
	value: string | undefined;
};

/** Prevent a late keychain write from replacing a newer captured credential. */
export class SplunkCloudConnectionStore {
	private latest: SplunkCloudStoredConnection | undefined;
	private revision = 0;

	async read(readPersisted: () => Promise<string | undefined>): Promise<string | undefined> {
		return this.latest === undefined || this.latest.state === 'rejected'
			? readPersisted()
			: this.latest.value;
	}

	async write(
		value: string | undefined,
		persist: (current: string | undefined) => Promise<void>,
	): Promise<void> {
		let pending: SplunkCloudStoredConnection = {
			revision: ++this.revision,
			state: 'pending',
			value,
		};
		this.latest = pending;

		while (true) {
			try {
				await persist(pending.value);
			} catch (error) {
				if (
					this.latest.revision === pending.revision
					&& this.latest.state !== 'committed'
				) {
					this.latest = { ...pending, state: 'rejected' };
				}
				throw error;
			}
			if (this.latest.revision === pending.revision) {
				this.latest = { ...pending, state: 'committed' };
				return;
			}
			if (this.latest.state === 'rejected') {
				return;
			}
			pending = this.latest;
		}
	}
}

/** Keep pending writes usable for restart without trusting a rejected write. */
export class SplunkCloudExportPreferenceStore {
	private latest: SplunkCloudExportPreference | undefined;
	private revision = 0;

	read(readPersisted: () => boolean | undefined): boolean | undefined {
		return this.latest === undefined || this.latest.state === 'rejected'
			? readPersisted()
			: this.latest.value;
	}

	async write(
		value: boolean | undefined,
		persist: (current: boolean | undefined) => Promise<void>,
	): Promise<void> {
		let pending: SplunkCloudExportPreference = {
			revision: ++this.revision,
			state: 'pending',
			value,
		};
		this.latest = pending;

		while (true) {
			try {
				await persist(pending.value);
			} catch (error) {
				if (
					this.latest.revision === pending.revision
					&& this.latest.state !== 'committed'
				) {
					this.latest = { ...pending, state: 'rejected' };
				}
				throw error;
			}
			if (this.latest.revision === pending.revision) {
				this.latest = { ...pending, state: 'committed' };
				return;
			}
			if (this.latest.state === 'rejected') {
				return;
			}
			pending = this.latest;
		}
	}
}

export type StoredSplunkCloudState = {
	connectionValue: string | undefined;
	exportEnabled: boolean | undefined;
};

/** Start both revisioned field writes before either can block. */
export async function writeSplunkCloudStatePair(options: {
	state: StoredSplunkCloudState;
	writeConnection: (value: string | undefined) => Promise<void>;
	writeExportEnabled: (value: boolean | undefined) => Promise<void>;
}): Promise<void> {
	await Promise.all([
		options.writeConnection(options.state.connectionValue),
		options.writeExportEnabled(options.state.exportEnabled),
	]);
}

export async function connectSplunkCloudWithStorage(options: {
	configureObserver: () => Promise<unknown>;
	readStoredState: () => Promise<StoredSplunkCloudState>;
	rollbackObserver: (rollbackToken: string) => Promise<void>;
	rollbackToken: string;
	restoreStoredState: (state: StoredSplunkCloudState) => Promise<void>;
	storeConnectedState: () => Promise<void>;
}): Promise<unknown> {
	const previous = await options.readStoredState();
	try {
		await options.storeConnectedState();
	} catch (storeError) {
		try {
			await options.restoreStoredState(previous);
		} catch (storageRollbackError) {
			throw new Error(
				`Could not store the cloud key securely: ${cloudErrorMessage(storeError)}. `
				+ `Secure-storage rollback also failed: ${cloudErrorMessage(storageRollbackError)}`,
			);
		}
		throw new Error(`Could not store the cloud key securely: ${cloudErrorMessage(storeError)}`);
	}

	try {
		return splitCloudRollbackCapability(await options.configureObserver()).status;
	} catch (configureError) {
		let rollbackError: unknown;
		try {
			await options.restoreStoredState(previous);
		} catch (storageRollbackError) {
			rollbackError = storageRollbackError;
		}
		if (shouldRestoreObserverAfterCloudMutationFailure(configureError)) {
			try {
				await options.rollbackObserver(options.rollbackToken);
			} catch (observerRollbackError) {
				if (!(observerRollbackError instanceof ObserverCloudResponseError
					&& observerRollbackError.statusCode === 409)) {
					rollbackError = rollbackError === undefined
						? observerRollbackError
						: new Error(
							`${cloudErrorMessage(rollbackError)}; Observer rollback also failed: `
							+ cloudErrorMessage(observerRollbackError),
						);
				}
			}
		}
		if (rollbackError !== undefined) {
			throw new Error(
				`Could not connect to Splunk Observability Cloud: ${cloudErrorMessage(configureError)}. `
				+ `Rollback also failed: ${cloudErrorMessage(rollbackError)}`,
			);
		}
		throw configureError;
	}
}

function splitCloudRollbackCapability(value: unknown): {
	rollbackToken: string | undefined;
	status: unknown;
} {
	if (typeof value !== 'object' || value === null || Array.isArray(value)) {
		return { rollbackToken: undefined, status: value };
	}
	const response = value as Record<string, unknown>;
	if (!('rollbackToken' in response)) {
		return { rollbackToken: undefined, status: value };
	}
	const { rollbackToken, ...status } = response;
	return {
		rollbackToken: typeof rollbackToken === 'string' && /^[A-Za-z0-9_-]{43}$/.test(rollbackToken)
			? rollbackToken
			: undefined,
		status,
	};
}

export async function setSplunkCloudExportEnabledWithStorage(options: {
	enabled: boolean;
	readStoredState: () => Promise<StoredSplunkCloudState>;
	rollbackObserver: (rollbackToken: string) => Promise<void>;
	rollbackToken: string;
	restoreStoredExportEnabled: (enabled: boolean | undefined) => Promise<void>;
	setObserverEnabled: (enabled: boolean) => Promise<unknown>;
	storeExportEnabled: (enabled: boolean) => Promise<void>;
}): Promise<unknown> {
	const previous = await options.readStoredState();
	try {
		await options.storeExportEnabled(options.enabled);
	} catch (storeError) {
		throw new Error(`Could not store the cloud export preference: ${cloudErrorMessage(storeError)}`);
	}

	try {
		const response = await options.setObserverEnabled(options.enabled);
		return splitCloudRollbackCapability(response).status;
	} catch (serverError) {
		let rollbackError: unknown;
		try {
			await options.restoreStoredExportEnabled(previous.exportEnabled);
		} catch (stateRollbackError) {
			rollbackError = stateRollbackError;
		}
		if (shouldRestoreObserverAfterCloudMutationFailure(serverError)) {
			try {
				await options.rollbackObserver(options.rollbackToken);
			} catch (observerRollbackError) {
				if (!(observerRollbackError instanceof ObserverCloudResponseError
					&& observerRollbackError.statusCode === 409)) {
					rollbackError = rollbackError === undefined
						? observerRollbackError
						: new Error(
							`${cloudErrorMessage(rollbackError)}; Observer rollback also failed: `
							+ cloudErrorMessage(observerRollbackError),
						);
				}
			}
		}
		if (rollbackError !== undefined) {
			throw new Error(
				`Could not update cloud export: ${cloudErrorMessage(serverError)}. `
				+ `Cloud export preference rollback also failed: ${cloudErrorMessage(rollbackError)}`,
			);
		}
		throw serverError;
	}
}

export async function forgetSplunkCloudWithStorage(options: {
	clearStoredState: () => Promise<void>;
	forgetObserver: () => Promise<unknown>;
	readStoredState: () => Promise<StoredSplunkCloudState>;
	rollbackObserver: (rollbackToken: string) => Promise<void>;
	rollbackToken: string;
	restoreStoredState: (state: StoredSplunkCloudState) => Promise<void>;
}): Promise<unknown> {
	const previous = await options.readStoredState();
	try {
		await options.clearStoredState();
	} catch (localError) {
		try {
			await options.restoreStoredState(previous);
		} catch (restoreError) {
			throw new Error(
				`Could not remove the cloud connection: ${cloudErrorMessage(localError)}. `
				+ `Secure-storage rollback also failed: ${cloudErrorMessage(restoreError)}`,
			);
		}
		throw localError;
	}

	try {
		const response = await options.forgetObserver();
		return splitCloudRollbackCapability(response).status;
	} catch (forgetError) {
		let rollbackError: unknown;
		try {
			await options.restoreStoredState(previous);
		} catch (restoreError) {
			rollbackError = restoreError;
		}
		if (shouldRestoreObserverAfterCloudMutationFailure(forgetError)) {
			try {
				await options.rollbackObserver(options.rollbackToken);
			} catch (observerRollbackError) {
				if (!(observerRollbackError instanceof ObserverCloudResponseError
					&& observerRollbackError.statusCode === 409)) {
					rollbackError = rollbackError === undefined
						? observerRollbackError
						: new Error(
							`${cloudErrorMessage(rollbackError)}; Observer rollback also failed: `
							+ cloudErrorMessage(observerRollbackError),
						);
				}
			}
		}
		if (rollbackError !== undefined) {
			throw new Error(
				`Could not remove the cloud connection: ${cloudErrorMessage(forgetError)}. `
				+ `Cloud connection rollback also failed: ${cloudErrorMessage(rollbackError)}`,
			);
		}
		throw forgetError;
	}
}

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

function isValidSplunkTokenSecret(value: string): boolean {
	return value.length > 0
		&& Buffer.byteLength(value, 'utf8') <= maxCloudAccessTokenBytes
		&& !/[\s\u0000-\u001F\u007F]/u.test(value);
}

export async function restoreSplunkCloudConnectionFromStorage(
	options: RestoreSplunkCloudConnectionOptions,
): Promise<unknown> {
	let status = await options.refresh();
	if (
		!options.restoreStoredConnection
		|| cloudStatusConnected(status)
		|| !cloudStatusHasNoConfiguration(status)
	) {
		return status;
	}

	const stored = await options.readConnection();
	if (stored === undefined) {
		return status;
	}

	status = await options.configure(stored, cloudStatusVersion(status));
	const enabled = options.readExportEnabled();
	if (enabled === undefined || cloudStatusEnabled(status) === enabled) {
		return status;
	}
	return options.setEnabled(enabled, cloudStatusVersion(status));
}

export function cloudStatusConnected(value: unknown): boolean {
	return typeof value === 'object'
		&& value !== null
		&& (value as Record<string, unknown>).connected === true;
}

export function cloudStatusHasNoConfiguration(value: unknown): boolean {
	if (typeof value !== 'object' || value === null) {
		return false;
	}
	const status = value as Record<string, unknown>;
	return cloudSignalConfigured(status.metrics) === false
		&& cloudSignalConfigured(status.traces) === false;
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

export function cloudStatusEnabled(value: unknown): boolean | undefined {
	if (typeof value !== 'object' || value === null) {
		return undefined;
	}
	const enabled = (value as Record<string, unknown>).enabled;
	return typeof enabled === 'boolean' ? enabled : undefined;
}

export function cloudStatusVersion(value: unknown): string | undefined {
	if (typeof value !== 'object' || value === null) {
		return undefined;
	}
	const version = (value as Record<string, unknown>).version;
	return typeof version === 'string' && /^[A-Za-z0-9_-]{43}$/.test(version)
		? version
		: undefined;
}

function cloudSignalConfigured(value: unknown): boolean | undefined {
	if (typeof value !== 'object' || value === null) {
		return undefined;
	}
	const configured = (value as Record<string, unknown>).configured;
	return typeof configured === 'boolean' ? configured : undefined;
}
