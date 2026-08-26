export const splunkCloudConnectionSecretKey = 'splunkCloudConnection.v1';

export type CloudBridgeAction =
	| 'connect'
	| 'forget'
	| 'initialize'
	| 'open-free-edition'
	| 'open-ingest-token-help'
	| 'open-skill-docs'
	| 'set-enabled';

/**
 * Skills whose documentation the webview may ask the extension to open. The
 * webview names a skill, never a URL — the extension owns the URL mapping so a
 * compromised webview cannot open an arbitrary page.
 */
export const skillDocsIds = ['otel-audit', 'otel-instrument', 'otel-verify'] as const;

export type SkillDocsId = typeof skillDocsIds[number];

export type CloudBridgeRequest = {
	action: CloudBridgeAction;
	bridgeToken: string;
	payload?: {
		accessToken?: string;
		enabled?: boolean;
		realm?: string;
		skill?: SkillDocsId;
	};
	requestId: string;
	type: 'obstudio.cloud.request';
};

export type CloudBridgeReady = {
	bridgeToken: string;
	type: 'obstudio.cloud.ready';
};

export type StoredSplunkCloudConnection = {
	accessToken: string;
	realm: string;
};

export type RestoreSplunkCloudConnectionOptions = {
	configure: (connection: StoredSplunkCloudConnection) => Promise<unknown>;
	readConnection: () => Promise<StoredSplunkCloudConnection | undefined>;
	readExportEnabled: () => boolean | undefined;
	refresh: () => Promise<unknown>;
	setEnabled: (enabled: boolean) => Promise<unknown>;
};

export function isCloudBridgeRequest(value: unknown): value is CloudBridgeRequest {
	if (typeof value !== 'object' || value === null) {
		return false;
	}
	const request = value as Record<string, unknown>;
	if (
		request.type !== 'obstudio.cloud.request'
		|| typeof request.bridgeToken !== 'string'
		|| !/^[A-Za-z0-9_-]{24,128}$/.test(request.bridgeToken)
		|| typeof request.requestId !== 'string'
		|| !/^[A-Za-z0-9_-]{8,128}$/.test(request.requestId)
		|| !isCloudBridgeAction(request.action)
	) {
		return false;
	}
	if (request.payload === undefined) {
		return true;
	}
	if (typeof request.payload !== 'object' || request.payload === null) {
		return false;
	}
	const payload = request.payload as Record<string, unknown>;
	return Object.keys(payload).every((key) => ['accessToken', 'enabled', 'realm', 'skill'].includes(key))
		&& (payload.accessToken === undefined
			|| (typeof payload.accessToken === 'string' && payload.accessToken.length <= 4096))
		&& (payload.enabled === undefined || typeof payload.enabled === 'boolean')
		&& (payload.realm === undefined
			|| (typeof payload.realm === 'string' && payload.realm.length <= 32))
		&& (payload.skill === undefined || isSkillDocsId(payload.skill));
}

export function isSkillDocsId(value: unknown): value is SkillDocsId {
	return typeof value === 'string' && (skillDocsIds as readonly string[]).includes(value);
}

export function isCloudBridgeReady(value: unknown): value is CloudBridgeReady {
	if (typeof value !== 'object' || value === null) {
		return false;
	}
	const ready = value as Record<string, unknown>;
	return ready.type === 'obstudio.cloud.ready'
		&& typeof ready.bridgeToken === 'string'
		&& /^[A-Za-z0-9_-]{24,128}$/.test(ready.bridgeToken);
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

function isValidSplunkTokenSecret(value: string): boolean {
	return value.length >= 16
		&& value.length <= 4096
		&& !/[\s\u0000-\u001F\u007F]/u.test(value);
}

export async function restoreSplunkCloudConnectionFromStorage(
	options: RestoreSplunkCloudConnectionOptions,
): Promise<unknown> {
	let status = await options.refresh();
	if (cloudStatusConnected(status) || !cloudStatusHasNoConfiguration(status)) {
		return status;
	}

	const stored = await options.readConnection();
	if (stored === undefined) {
		return status;
	}

	status = await options.configure(stored);
	const enabled = options.readExportEnabled();
	if (enabled === undefined || cloudStatusEnabled(status) === enabled) {
		return status;
	}
	return options.setEnabled(enabled);
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

export function cloudStatusEnabled(value: unknown): boolean | undefined {
	if (typeof value !== 'object' || value === null) {
		return undefined;
	}
	const enabled = (value as Record<string, unknown>).enabled;
	return typeof enabled === 'boolean' ? enabled : undefined;
}

function cloudSignalConfigured(value: unknown): boolean | undefined {
	if (typeof value !== 'object' || value === null) {
		return undefined;
	}
	const configured = (value as Record<string, unknown>).configured;
	return typeof configured === 'boolean' ? configured : undefined;
}

function isCloudBridgeAction(value: unknown): value is CloudBridgeAction {
	return value === 'connect'
		|| value === 'forget'
		|| value === 'initialize'
		|| value === 'open-free-edition'
		|| value === 'open-ingest-token-help'
		|| value === 'open-skill-docs'
		|| value === 'set-enabled';
}
