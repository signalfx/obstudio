import * as assert from 'node:assert/strict';
import * as fs from 'node:fs';
import * as os from 'node:os';
import * as path from 'node:path';
import { PassThrough } from 'node:stream';
import test from 'node:test';
import WebSocket from 'ws';
import {
	caseInsensitiveHeaderValue,
	codexObstudioHasNoAuthorization,
	createAgentIntegrationConfigFingerprint,
	getCodexObstudioAuthorization,
	getCodexObstudioSection,
	getCodexObstudioUrl,
	hasNoAuthorizationHeader,
	shouldRefreshOwnedAgentIntegrationConfig,
} from '../agent-integration-config';
import {
	buildObserverHealthUrl,
	buildObserverValidatorSummaryUrl,
	findOtherExtensionManagedObserver,
	isLoopbackObserverHost,
	normalizeObserverBaseUrl,
	normalizeSharedObserverBaseUrl,
	normalizeSharedObserverHealthUrl,
	normalizeSharedObserverMCPUrl,
	observerPortFromUrl,
	readSharedObserverDiscovery,
	resolveBackend,
} from '../backend';
import {
	auditReportPath,
	auditReportUrl,
	cloudBridgeActionRequiresLifecycleSerialization,
	connectSplunkCloudWithStorage,
	freeAccountSubmissionFailureIsOutcomeUnknown,
	forgetSplunkCloudWithStorage,
	initializeSplunkCloudStatus,
	isSkillDocsId,
	isSupportedFreeAccountRegion,
	ObserverCloudResponseError,
	observerCloudResponseError,
	parseFreeAccountSubmissionResult,
	parseObserverCloudResponseBody,
	skillDocsIds,
	skillDocsUrl,
	parseStoredSplunkCloudConnection,
	restoreSplunkCloudConnectionFromStorage,
	setSplunkCloudExportEnabledWithStorage,
	SplunkCloudConnectionStore,
	SplunkCloudExportPreferenceStore,
	StoredSplunkCloudConnectionRejectedError,
	StoredSplunkCloudConnectionVerificationUnavailableError,
	shouldRestoreObserverAfterCloudMutationFailure,
	verifyStoredSplunkCloudConnection,
	writeSplunkCloudStatePair,
} from '../cloud-bridge';
import {
	collectObserverHostHTTPResponse,
	isAllowedObserverHostHTTPPath,
	isObserverHostCancelEnvelope,
	isObserverHostRequestEnvelope,
	isObserverHostTelemetryEnvelope,
	maxLocalObserverHostResponseBytes,
	maxRemoteObserverHostResponseBytes,
	observerHostResponseByteLimit,
} from '../observer-webview-host';
import { ObserverWebviewTelemetry, webSocketURL } from '../observer-webview-telemetry';

const extensionRoot = path.resolve(__dirname, '..', '..');
const {
	buildClientAssets,
	getBuildPaths,
	observerBuildArgs,
	observerBuildVersion,
	resetObserverOutputDirs,
} = require('../../build-observer.js') as {
	buildClientAssets: (
		paths: ReturnType<typeof getBuildPaths>,
		run?: (file: string, args: string[], options: { cwd: string; stdio: string }) => unknown,
	) => void;
	getBuildPaths: (extensionRoot?: string, env?: NodeJS.ProcessEnv) => {
		clientAssetsDir: string;
		repoRoot: string;
		observerRoot: string;
		observerOutDir: string;
		observerOutBinary: string;
		target: {
			binaryName: string;
			goarch: string;
			goos: string;
		};
		webviewOutDir: string;
	};
	observerBuildArgs: (
		paths: ReturnType<typeof getBuildPaths>,
		env?: NodeJS.ProcessEnv,
	) => string[];
	observerBuildVersion: (env?: NodeJS.ProcessEnv) => string;
	resetObserverOutputDirs: (paths: ReturnType<typeof getBuildPaths>) => void;
};
function hostWeaverBinaryName(): string {
	return process.platform === 'win32' ? 'weaver.exe' : 'weaver';
}

function withTempExtensionRoot(run: (extensionRoot: string) => void) {
	const extensionRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'obstudio-extension-'));

	try {
		run(extensionRoot);
	} finally {
		fs.rmSync(extensionRoot, { force: true, recursive: true });
	}
}

function writePrivateSharedObserverState(statePath: string, state: Record<string, unknown>): void {
	fs.writeFileSync(statePath, JSON.stringify(state), { mode: 0o600 });
	fs.chmodSync(statePath, 0o600);
}

test('IDE host transport accepts only bounded known cloud requests', () => {
	const expectedVersion = 'V'.repeat(43);
	const cloudRequest = (action: string, payload?: Record<string, unknown>) => ({
		request: { action, kind: 'cloud', payload },
		requestId: 'request-123',
		type: 'obstudio.host.request',
	});
	assert.equal(isObserverHostRequestEnvelope(cloudRequest('connect', {
		accessToken: 'token_1234567890123456',
		expectedVersion,
		realm: 'us0',
	})), true);
	assert.equal(isObserverHostRequestEnvelope(cloudRequest('connect', {
		accessToken: 'é'.repeat(2048),
		expectedVersion,
		realm: 'us0',
	})), true);
	assert.equal(isObserverHostRequestEnvelope(cloudRequest('connect', {
		accessToken: 'é'.repeat(2049),
		expectedVersion,
		realm: 'us0',
	})), false);
	assert.equal(isObserverHostRequestEnvelope(cloudRequest('connect', {
		accessToken: 'token_1234567890123456',
		realm: 'us0',
	})), true);
	assert.equal(isObserverHostRequestEnvelope(cloudRequest('connect', {
		accessToken: 'token_1234567890123456',
		expectedVersion: 'not-a-version',
		realm: 'us0',
	})), false);
	assert.equal(isObserverHostRequestEnvelope(cloudRequest('set-enabled', {
		enabled: true,
		expectedVersion,
	})), true);
	assert.equal(isObserverHostRequestEnvelope(cloudRequest('set-enabled', {
		enabled: true,
	})), true);
	assert.equal(isObserverHostRequestEnvelope(cloudRequest('forget', { expectedVersion })), true);
	assert.equal(isObserverHostRequestEnvelope(cloudRequest('forget')), true);
	assert.equal(isObserverHostRequestEnvelope(cloudRequest('resolve-realm', {
		destination: 'https://pov-rexel-webshop.observability.splunkcloud.com/#/signin',
	})), true);
	assert.equal(isObserverHostRequestEnvelope(cloudRequest('resolve-realm', {
		destination: 'é'.repeat(1024),
	})), true);
	assert.equal(isObserverHostRequestEnvelope(cloudRequest('resolve-realm', {
		destination: 'é'.repeat(1025),
	})), false);
	assert.equal(isObserverHostRequestEnvelope(cloudRequest('resolve-realm', {
		destination: '   ',
	})), false);
	assert.equal(isObserverHostRequestEnvelope(cloudRequest('resolve-realm', {
		accessToken: 'must-not-pass',
		destination: 'https://ingest.eu0.observability.splunkcloud.com',
	})), false);
	assert.equal(isObserverHostRequestEnvelope(cloudRequest('open-free-edition')), true);
	assert.equal(isObserverHostRequestEnvelope(cloudRequest('open-free-edition-terms')), true);
	assert.equal(isObserverHostRequestEnvelope(cloudRequest('open-ingest-token-help')), true);
	assert.equal(isObserverHostRequestEnvelope(cloudRequest('open-realm-help')), true);
	assert.equal(isObserverHostRequestEnvelope(cloudRequest('open-realm-help', {
		destination: 'https://example.test',
	})), false);
	assert.equal(isObserverHostRequestEnvelope(cloudRequest('open-observability-cloud-demo')), true);
	assert.equal(isObserverHostRequestEnvelope(cloudRequest('open-observability-data-course')), true);
	assert.equal(isObserverHostRequestEnvelope(cloudRequest('open-observability-docs')), true);
	assert.equal(isObserverHostRequestEnvelope(cloudRequest('detect-free-account-region')), true);
	assert.equal(isObserverHostRequestEnvelope(cloudRequest('detect-free-account-region', {
		region: 'Europe (Ireland)',
	})), false);
	assert.equal(isObserverHostRequestEnvelope(cloudRequest('create-free-account', {
		email: 'person@example.com',
		firstName: 'Example',
		lastName: 'Person',
		region: 'Europe (Ireland)',
		termsAccepted: true,
	})), true);
	for (const invalidPayload of [
		{
			email: 'person@example.com',
			firstName: 'Example',
			lastName: 'Person',
			region: 'eu0',
			termsAccepted: true,
		},
		{
			email: 'person@example.com',
			firstName: 'Example',
			lastName: 'Person',
			region: 'us',
			termsAccepted: false,
		},
		{
			email: 'person@example.com',
			firstName: 'Example',
			lastName: 'Person',
			publicIp: '203.0.113.10',
			region: 'us',
			termsAccepted: true,
		},
		{
			email: `${'e'.repeat(69)}@example.com`,
			firstName: 'Example',
			lastName: 'Person',
			region: 'us',
			termsAccepted: true,
		},
	]) {
		assert.equal(isObserverHostRequestEnvelope(cloudRequest('create-free-account', invalidPayload)), false);
	}
	assert.equal(isObserverHostRequestEnvelope(cloudRequest('unsupported')), false);
	assert.equal(isObserverHostRequestEnvelope(cloudRequest('open-skill-docs', {
		skill: 'otel-instrument',
	})), true);
	// Only known skill ids pass; the webview can never name a URL.
	assert.equal(isObserverHostRequestEnvelope(cloudRequest('open-skill-docs', {
		skill: 'https://evil.example.com',
	})), false);
	assert.equal(isObserverHostRequestEnvelope(cloudRequest('open-skill-docs', {
		skill: '../../etc/passwd',
	})), false);
	// Every advertised skill id must pass validation, including the Splunk
	// Observability Cloud skills surfaced on the Overview tab.
	for (const skill of skillDocsIds) {
		assert.equal(isObserverHostRequestEnvelope(cloudRequest('open-skill-docs', { skill })), true,
			`skill id ${skill} should validate`);
	}
	assert.equal(isObserverHostRequestEnvelope({ ...cloudRequest('connect'), requestId: 'short' }), false);
	assert.equal(isObserverHostRequestEnvelope(cloudRequest('connect', {
		unexpectedField: 'must-not-pass',
	})), false);
});

test('free account region contract matches the public Splunk form values', () => {
	for (const region of [
		'us',
		'Europe (Ireland)',
		'apac-au',
	]) {
		assert.equal(isSupportedFreeAccountRegion(region), true, region);
	}
	for (const removedRegion of [
		'Europe (Frankfurt)',
		'Europe (London)',
		'apac-jp',
		'Asia Pacific (Singapore)',
	]) {
		assert.equal(isSupportedFreeAccountRegion(removedRegion), false, removedRegion);
	}
	for (const realm of ['us0', 'us1', 'eu0', 'eu1', 'eu2', 'au0', 'jp0', 'sg0']) {
		assert.equal(isSupportedFreeAccountRegion(realm), false, realm);
	}
});

test('Observer cloud errors expose only allowlisted signup metadata', () => {
	const error = observerCloudResponseError(502, {
		code: 'outcome_unknown',
		error: 'The signup outcome is unknown.',
		retrySafe: false,
		secret: 'must-not-pass',
	});
	assert.equal(error.message, 'The signup outcome is unknown.');
	assert.equal(error.code, 'outcome_unknown');
	assert.equal(error.retrySafe, false);
	assert.equal('secret' in error, false);
});

test('Free Edition proxy 5xx responses are treated as unknown submission outcomes', () => {
	assert.equal(
		freeAccountSubmissionFailureIsOutcomeUnknown(new ObserverCloudResponseError(502, 'Bad Gateway')),
		true,
	);
	assert.equal(
		freeAccountSubmissionFailureIsOutcomeUnknown(new ObserverCloudResponseError(
			503,
			'Observer control unavailable',
			'observer_control_unavailable',
			true,
		)),
		false,
	);
	assert.equal(
		freeAccountSubmissionFailureIsOutcomeUnknown(new ObserverCloudResponseError(
			502,
			'Bad Gateway',
			'bad_gateway',
		)),
		true,
	);
	assert.equal(
		freeAccountSubmissionFailureIsOutcomeUnknown(new ObserverCloudResponseError(
			500,
			'Retryable before submission',
			'future_pre_submit_error',
			true,
		)),
		false,
	);
	assert.equal(
		freeAccountSubmissionFailureIsOutcomeUnknown(new ObserverCloudResponseError(
			409,
			'Outcome unknown',
			'outcome_unknown',
			false,
		)),
		true,
	);
	assert.equal(
		freeAccountSubmissionFailureIsOutcomeUnknown(new ObserverCloudResponseError(422, 'Invalid request')),
		false,
	);
	assert.equal(freeAccountSubmissionFailureIsOutcomeUnknown(new Error('network failure')), false);
});

test('Free Edition success requires a complete acknowledged Observer result', () => {
	for (const [region, realm] of [
		['us', 'us1'],
		['Europe (Ireland)', 'eu0'],
		['apac-au', 'au0'],
	] as const) {
		assert.deepEqual(parseFreeAccountSubmissionResult({
			intakeAcknowledged: true,
			realm: realm.toUpperCase(),
			region,
		}), {
			intakeAcknowledged: true,
			realm,
			region,
		});
	}
	assert.deepEqual(parseFreeAccountSubmissionResult({
		intakeAcknowledged: false,
		realm: 'us1',
		region: 'us',
	}), {
		intakeAcknowledged: false,
		realm: 'us1',
		region: 'us',
	});
	assert.deepEqual(parseFreeAccountSubmissionResult({
		accountSetupPending: true,
		intakeAcknowledged: true,
		realm: 'eu0',
		region: 'Europe (Ireland)',
	}), {
		accountSetupPending: true,
		intakeAcknowledged: true,
		realm: 'eu0',
		region: 'Europe (Ireland)',
	});
	for (const invalid of [
		{},
		{ accountSetupPending: 'true', intakeAcknowledged: true, realm: 'us1', region: 'us' },
		{ intakeAcknowledged: true, realm: 'us1', region: 'us0' },
		{ intakeAcknowledged: true, realm: '../us1', region: 'us' },
		{ intakeAcknowledged: true, realm: 'us-', region: 'us' },
		{ intakeAcknowledged: true, realm: 'us1', region: 'Europe (Ireland)' },
	]) {
		assert.equal(parseFreeAccountSubmissionResult(invalid), undefined);
	}
});

test('agent integration configuration rejects every Authorization header', () => {
	assert.equal(
		caseInsensitiveHeaderValue({ authorization: 'Bearer stale-token' }, 'Authorization'),
		'Bearer stale-token',
	);
	assert.equal(hasNoAuthorizationHeader(undefined), true);
	assert.equal(hasNoAuthorizationHeader({}), true);
	assert.equal(hasNoAuthorizationHeader({ Authorization: 'Bearer stale-token' }), false);
	assert.equal(hasNoAuthorizationHeader({
		Authorization: 'Bearer one',
		authorization: 'Bearer two',
	}), false);

	const noAuthorization = getCodexObstudioSection([
		'[mcp_servers.obstudio]',
		'url = "http://127.0.0.1:3000/mcp"',
	].join('\n'));
	assert.notEqual(noAuthorization, undefined);
	assert.equal(codexObstudioHasNoAuthorization(noAuthorization ?? ''), true);
	assert.equal(getCodexObstudioAuthorization(noAuthorization ?? ''), undefined);

	for (const authorization of [
		'http_headers = { Authorization = "Bearer stale-token" }',
		'[mcp_servers.obstudio.http_headers]\nAuthorization = "Bearer stale-token"',
	]) {
		const section = getCodexObstudioSection([
			'[mcp_servers.obstudio]',
			'url = "http://127.0.0.1:3000/mcp"',
			authorization,
		].join('\n'));
		assert.notEqual(section, undefined);
		assert.equal(codexObstudioHasNoAuthorization(section ?? ''), false);
	}
});

test('agent integration fingerprints refresh only an unchanged extension-owned endpoint', () => {
	const desiredMcpUrl = 'http://127.0.0.1:3000/mcp';
	const original = {
		fingerprintMaterial: JSON.stringify({
			headers: { Authorization: 'Bearer prior-control-token' },
			type: 'http',
			url: desiredMcpUrl,
		}),
		mcpUrl: desiredMcpUrl,
	};
	const fingerprint = createAgentIntegrationConfigFingerprint(original);

	assert.equal(JSON.stringify(fingerprint).includes('prior-control-token'), false);
	assert.equal(shouldRefreshOwnedAgentIntegrationConfig(fingerprint, original, desiredMcpUrl), true);
	assert.equal(shouldRefreshOwnedAgentIntegrationConfig(fingerprint, {
		...original,
		fingerprintMaterial: original.fingerprintMaterial.replace('prior-control-token', 'user-control-token'),
	}, desiredMcpUrl), false);
	assert.equal(shouldRefreshOwnedAgentIntegrationConfig(fingerprint, {
		...original,
		fingerprintMaterial: original.fingerprintMaterial.replace('"type":"http"', '"disabled":true,"type":"http"'),
	}, desiredMcpUrl), false);
	assert.equal(shouldRefreshOwnedAgentIntegrationConfig(fingerprint, {
		...original,
		mcpUrl: 'http://127.0.0.1:4000/mcp',
	}, desiredMcpUrl), false);
	assert.equal(shouldRefreshOwnedAgentIntegrationConfig(fingerprint, original, 'http://127.0.0.1:4000/mcp'), false);
	assert.equal(shouldRefreshOwnedAgentIntegrationConfig(undefined, original, desiredMcpUrl), false);
	assert.equal(shouldRefreshOwnedAgentIntegrationConfig({
		...fingerprint,
		configurationDigest: 'not-a-digest',
	}, original, desiredMcpUrl), false);
});

test('Codex TOML parsing treats array tables as distinct scope boundaries', () => {
	const adjacentArray = getCodexObstudioSection([
		'[mcp_servers.obstudio]',
		'url = "http://127.0.0.1:3000/mcp"',
		'[[profiles.entries]]',
		'url = "https://wrong.example.test/mcp"',
	].join('\n'));
	assert.equal(adjacentArray, [
		'[mcp_servers.obstudio]',
		'url = "http://127.0.0.1:3000/mcp"',
	].join('\n'));
	assert.equal(getCodexObstudioUrl(adjacentArray ?? ''), 'http://127.0.0.1:3000/mcp');

	const nestedArray = getCodexObstudioSection([
		'[mcp_servers.obstudio]',
		'url = "http://127.0.0.1:3000/mcp"',
		'[[mcp_servers.obstudio.metadata]]',
		'url = "https://array.example.test/mcp"',
		'http_headers = { Authorization = "Bearer wrong-token" }',
		'[mcp_servers.obstudio.http_headers]',
		'Authorization = "Bearer current-token"',
		'[mcp_servers.other]',
		'url = "https://other.example.test/mcp"',
	].join('\n'));
	assert.notEqual(nestedArray, undefined);
	assert.match(nestedArray ?? '', /\[\[mcp_servers\.obstudio\.metadata\]\]/);
	assert.doesNotMatch(nestedArray ?? '', /other\.example\.test/);
	assert.equal(getCodexObstudioUrl(nestedArray ?? ''), 'http://127.0.0.1:3000/mcp');
	assert.equal(getCodexObstudioAuthorization(nestedArray ?? ''), 'Bearer current-token');
	assert.equal(codexObstudioHasNoAuthorization(nestedArray ?? ''), false);
});

test('Observer-mutating Cloud actions serialize with lifecycle transitions', () => {
	for (const action of ['connect', 'create-free-account', 'forget', 'initialize', 'set-enabled'] as const) {
		assert.equal(cloudBridgeActionRequiresLifecycleSerialization(action), true, action);
	}
	for (const action of [
		'open-audit-report',
		'open-free-edition',
		'open-ingest-token-help',
		'open-realm-help',
		'open-skill-docs',
		'resolve-realm',
	] as const) {
		assert.equal(cloudBridgeActionRequiresLifecycleSerialization(action), false, action);
	}

	const extensionSourcePath = path.join(extensionRoot, 'src', 'extension.ts');
	const source = fs.readFileSync(extensionSourcePath, 'utf-8');
	assert.match(
		source,
		/const queuedStop = observerCloudLifecycleOperations\.run\([\s\S]*?return observerStopOperation\.run\(\(\) => queuedStop\)/,
	);
	assert.match(
		source,
		/cloudBridgeActionRequiresLifecycleSerialization\(request\.action\)[\s\S]*?observerCloudLifecycleOperations\.run\([\s\S]*?performCloudBridgeActionExclusive/,
	);
});

test('Free Edition actions use the generic IDE host transport and fixed Observer routes', () => {
	const extensionSourcePath = path.join(extensionRoot, 'src', 'extension.ts');
	const source = fs.readFileSync(extensionSourcePath, 'utf-8');
	const hostSource = fs.readFileSync(
		path.join(extensionRoot, 'src', 'observer-webview-host.ts'),
		'utf-8',
	);

	assert.match(
		source,
		/case 'detect-free-account-region':[\s\S]*?requestObserverFreeAccountJSON\(\s*'\/api\/splunk\/free-account\/region',\s*undefined,/,
	);
	assert.match(
		source,
		/case 'resolve-realm':[\s\S]*?postObserverCloudJSON\(\s*'\/api\/splunk\/export\/realm',\s*\{ destination \}/,
	);
	assert.match(
		source,
		/case 'resolve-realm':[\s\S]*?return \{[\s\S]*?realm: splunkRealmFromResponse/,
	);
	assert.match(
		source,
		/const splunkRealmHelpUrl = 'https:\/\/help\.splunk\.com\/en\/splunk-observability-cloud\/administer\/org-reference-info\/view-your-realm-api-endpoints-and-organization'/,
	);
	assert.match(
		source,
		/const splunkIngestTokenHelpUrl = 'https:\/\/help\.splunk\.com\/en\/splunk-observability-cloud\/administer\/authentication-and-security\/authentication-tokens\/org-access-tokens'/,
	);
	assert.match(
		source,
		/case 'open-realm-help':[\s\S]*?openCloudExternalUrl\(splunkRealmHelpUrl\)/,
	);
	assert.match(
		source,
		/case 'open-ingest-token-help':[\s\S]*?openCloudExternalUrl\(splunkIngestTokenHelpUrl\)/,
	);
	assert.match(
		source,
		/case 'create-free-account':[\s\S]*?requestObserverFreeAccountJSON\(\s*'\/api\/splunk\/free-account',[\s\S]*?email: payload\.email,[\s\S]*?firstName: payload\.firstName,[\s\S]*?lastName: payload\.lastName,[\s\S]*?region: payload\.region,[\s\S]*?termsAccepted: true,/,
	);
	assert.match(
		source,
		/const freeAccount = parseFreeAccountSubmissionResult\([\s\S]*?freeAccount === undefined[\s\S]*?'outcome_unknown'[\s\S]*?!freeAccount\.intakeAcknowledged[\s\S]*?'signup_not_acknowledged'/,
	);
	assert.match(
		source,
		/postObserverHostResponse\([\s\S]*?cloudBridgeErrorMetadata\(error\)[\s\S]*?type: 'obstudio\.host\.response'/,
	);
	assert.match(
		source,
		/isFreeAccountSignupRequest\(message\.request\)[\s\S]*?showInformationMessage\([\s\S]*?within 10 minutes/,
	);
	assert.match(
		source,
		/delivered = await postObserverHostResponse\([\s\S]*?\.catch\(\(\) => false\)[\s\S]*?!delivered[\s\S]*?freeAccountSignup/,
	);
	assert.match(
		source,
		/metadata\.code === 'outcome_unknown' \|\| metadata\.retrySafe === false[\s\S]*?showWarningMessage/,
	);
	assert.match(hostSource, /case 'create-free-account':[\s\S]*?value\.termsAccepted === true/);
	assert.doesNotMatch(source, /obstudio\.cloud\.(?:bridge|ready|request|response)/);
	assert.doesNotMatch(hostSource, /publicIp|clientIpLookupAttempted|opendns/i);
});

test('observer cloud response parsing preserves non-JSON route errors for compatibility fallback', () => {
	assert.deepEqual(parseObserverCloudResponseBody(404, '404 page not found\n'), {});
	assert.deepEqual(parseObserverCloudResponseBody(401, '{"error":"unauthorized"}'), { error: 'unauthorized' });
	assert.throws(
		() => parseObserverCloudResponseBody(200, 'not JSON'),
		/invalid response \(HTTP 200\)/,
	);
});

test('Observer rollback is skipped after authoritative cloud mutation rejections', () => {
	for (const statusCode of [400, 401, 404, 409]) {
		assert.equal(
			shouldRestoreObserverAfterCloudMutationFailure(
				new ObserverCloudResponseError(statusCode, 'request rejected'),
			),
			false,
		);
	}
	assert.equal(
		shouldRestoreObserverAfterCloudMutationFailure(
			new ObserverCloudResponseError(500, 'uncertain server failure'),
		),
		true,
	);
	assert.equal(shouldRestoreObserverAfterCloudMutationFailure(new Error('connection reset')), true);
});

test('stored cloud restore never applies credentials after transient verification failures', async () => {
	for (const statusCode of [502, 504]) {
		const calls: string[] = [];
		await assert.rejects(
			() => verifyStoredSplunkCloudConnection(async () => {
				calls.push('verify');
				throw new ObserverCloudResponseError(statusCode, 'Splunk temporarily unavailable');
			}),
			(error: unknown) => error instanceof StoredSplunkCloudConnectionVerificationUnavailableError,
		);
		assert.deepEqual(calls, ['verify']);
	}

	for (const error of [
		new ObserverCloudResponseError(400, 'invalid stored connection'),
		new ObserverCloudResponseError(500, 'Observer apply failed'),
		new Error('Observer transport failed'),
	]) {
		await assert.rejects(
			() => verifyStoredSplunkCloudConnection(async () => { throw error; }),
		);
	}

	await assert.rejects(
		() => verifyStoredSplunkCloudConnection(
			async () => { throw new ObserverCloudResponseError(401, 'Splunk token rejected'); },
		),
		(error: unknown) => error instanceof StoredSplunkCloudConnectionRejectedError,
	);
});

test('IDE host transport restricts HTTP paths, cancellation, and telemetry commands', () => {
	assert.equal(maxLocalObserverHostResponseBytes, 64 * 1024 * 1024);
	assert.equal(maxRemoteObserverHostResponseBytes, 16 * 1024 * 1024);
	assert.equal(
		observerHostResponseByteLimit(new URL('http://127.0.0.1:3001')),
		maxLocalObserverHostResponseBytes,
	);
	assert.equal(
		observerHostResponseByteLimit(new URL('http://[::1]:3001')),
		maxLocalObserverHostResponseBytes,
	);
	assert.equal(
		observerHostResponseByteLimit(new URL('https://observer.example.test:3001')),
		maxRemoteObserverHostResponseBytes,
	);
	for (const path of [
		'/api/health',
		'/api/query/traces?service=checkout',
		'/api/query/traces/0123456789abcdef0123456789abcdef',
		'/api/splunk/export',
	]) {
		assert.equal(isAllowedObserverHostHTTPPath('GET', path), true, path);
	}
	assert.equal(isAllowedObserverHostHTTPPath('POST', '/api/validation/run'), true);
	for (const path of [
		'https://evil.example/api/health',
		'//evil.example/api/health',
		'/api/splunk/export/forget',
		'/api/health#fragment',
		'/api/unknown',
	]) {
		assert.equal(isAllowedObserverHostHTTPPath('GET', path), false, path);
	}
	assert.equal(isObserverHostCancelEnvelope({
		requestId: 'request-123',
		type: 'obstudio.host.cancel',
	}), true);
	assert.equal(isObserverHostCancelEnvelope({ requestId: 'short', type: 'obstudio.host.cancel' }), false);
	for (const command of ['pause', 'resume', 'subscribe', 'unsubscribe']) {
		assert.equal(isObserverHostTelemetryEnvelope({
			command,
			type: 'obstudio.host.telemetry',
		}), true);
	}
	assert.equal(isObserverHostTelemetryEnvelope({
		command: 'connect',
		type: 'obstudio.host.telemetry',
	}), false);
	for (const cimdAction of ['setup-cimd', 'login-cimd', 'disconnect-cimd']) {
		assert.equal(isObserverHostRequestEnvelope({
			request: { action: cimdAction, kind: 'cloud', payload: { expectedVersion: 'V'.repeat(43) } },
			requestId: 'request-123',
			type: 'obstudio.host.request',
		}), true, cimdAction);
		assert.equal(isObserverHostRequestEnvelope({
			request: { action: cimdAction, kind: 'cloud' },
			requestId: 'request-123',
			type: 'obstudio.host.request',
		}), true, `${cimdAction} must allow retry without an available state version`);
		assert.equal(isObserverHostRequestEnvelope({
			request: {
				action: cimdAction,
				kind: 'cloud',
				payload: { expectedVersion: 'V'.repeat(43), realm: 'us0' },
			},
			requestId: 'request-123',
			type: 'obstudio.host.request',
		}), false, `${cimdAction} must not accept a realm payload`);
	}
});

test('IDE host response collection rejects truncated and aborted responses', async () => {
	for (const event of ['close', 'aborted'] as const) {
		const response = new PassThrough();
		Object.assign(response, {
			complete: false,
			headers: { 'content-type': 'application/json' },
			statusCode: 200,
			statusMessage: 'OK',
		});
		const pending = collectObserverHostHTTPResponse(
			response as unknown as import('node:http').IncomingMessage,
			{ destroy() {} },
			maxLocalObserverHostResponseBytes,
		);
		response.write('{"partial":');
		response.emit(event);

		await assert.rejects(pending, /before completion/);
		assert.doesNotThrow(() => response.emit('error', new Error('late response error')));
	}
});

test('IDE host response collection handles stream errors and enforces its byte limit', async () => {
	const responseError = new PassThrough();
	Object.assign(responseError, { complete: false, headers: {} });
	const errored = collectObserverHostHTTPResponse(
		responseError as unknown as import('node:http').IncomingMessage,
		{ destroy() {} },
		16,
	);
	responseError.emit('error', new Error('response reset'));
	await assert.rejects(errored, /response reset/);

	const oversizedResponse = new PassThrough();
	Object.assign(oversizedResponse, { complete: false, headers: {} });
	let destroyError: Error | undefined;
	const oversized = collectObserverHostHTTPResponse(
		oversizedResponse as unknown as import('node:http').IncomingMessage,
		{ destroy(error?: Error) { destroyError = error; } },
		4,
	);
	oversizedResponse.write('12345');
	await assert.rejects(oversized, /exceeded/);
	assert.match(destroyError?.message ?? '', /exceeded/);
});

test('IDE telemetry opens its WebSocket immediately and forwards live updates', () => {
	const posted: unknown[] = [];
	const socket = new FakeObserverWebSocket();
	let requestedUrl = '';
	let requestedPayloadLimit: number | undefined;

	const telemetry = new ObserverWebviewTelemetry(
		'http://127.0.0.1:3000',
		async (message) => {
			posted.push(message);
			return true;
		},
		() => undefined,
		(url, options) => {
			requestedUrl = url;
			requestedPayloadLimit = options.maxPayload;
			return socket as unknown as WebSocket;
		},
	);
	telemetry.handle('subscribe');
	assert.equal(requestedUrl, 'ws://127.0.0.1:3000/api/ws');
	assert.equal(requestedPayloadLimit, maxLocalObserverHostResponseBytes);
	assert.equal(socket.sent.length, 0);
	socket.readyState = WebSocket.OPEN;
	socket.emit('open');
	assert.deepEqual(socket.sent, ['{"type":"subscribe"}']);

	socket.emit('message', Buffer.from(JSON.stringify({ type: 'connected' })), false);
	socket.emit('message', Buffer.from(JSON.stringify({
		data: [{ traceId: 'abc' }],
		signal: 'traces',
		type: 'update',
	})), false);
	socket.emit('message', Buffer.from('{not-json'), false);
	assert.deepEqual(posted, [
		{
			message: { type: 'connected' },
			type: 'obstudio.host.telemetry-message',
		},
		{
			message: { data: [{ traceId: 'abc' }], signal: 'traces', type: 'update' },
			type: 'obstudio.host.telemetry-message',
		},
	]);

	telemetry.handle('pause');
	telemetry.handle('resume');
	assert.deepEqual(socket.sent, [
		'{"type":"subscribe"}',
		'{"type":"pause"}',
		'{"type":"resume"}',
	]);
	telemetry.dispose();
	assert.equal(socket.closed, true);
});

test('IDE telemetry uses the same local and remote payload limits as HTTP snapshots', () => {
	for (const [baseURL, expectedLimit] of [
		['http://127.0.0.1:3000', maxLocalObserverHostResponseBytes],
		['https://observer.example.test', maxRemoteObserverHostResponseBytes],
	] as const) {
		const socket = new FakeObserverWebSocket();
		let payloadLimit: number | undefined;
		const telemetry = new ObserverWebviewTelemetry(
			baseURL,
			() => Promise.resolve(true),
			() => undefined,
			(_url, options) => {
				payloadLimit = options.maxPayload;
				return socket as unknown as WebSocket;
			},
		);

		telemetry.handle('subscribe');
		assert.equal(payloadLimit, expectedLimit);
		telemetry.dispose();
	}
});

test('IDE telemetry maps Observer HTTP URLs to WebSocket URLs', () => {
	assert.equal(webSocketURL('http://127.0.0.1:3000'), 'ws://127.0.0.1:3000/api/ws');
	assert.equal(webSocketURL('https://observer.example.test/base'), 'wss://observer.example.test/base/api/ws');
	assert.throws(() => webSocketURL('file:///tmp/observer'), /HTTP or HTTPS/);
});

test('stored cloud connections require a valid realm and opaque token', () => {
	assert.deepEqual(
		parseStoredSplunkCloudConnection(JSON.stringify({
			accessToken: 'token_1234567890123456',
			realm: 'us0',
		})),
		{
			accessToken: 'token_1234567890123456',
			realm: 'us0',
		},
	);
	assert.deepEqual(parseStoredSplunkCloudConnection(JSON.stringify({
		accessToken: 'too-short',
		realm: 'us0',
	})), {
		accessToken: 'too-short',
		realm: 'us0',
	});
	assert.equal(parseStoredSplunkCloudConnection(JSON.stringify({
		accessToken: '',
		realm: 'us0',
	})), undefined);
	assert.deepEqual(
		parseStoredSplunkCloudConnection(JSON.stringify({
			accessToken: 'opaque.token+/=123456789',
			realm: 'us0',
		})),
		{
			accessToken: 'opaque.token+/=123456789',
			realm: 'us0',
		},
	);
	assert.equal(parseStoredSplunkCloudConnection(JSON.stringify({
		accessToken: 'token with spaces 1234',
		realm: 'us0',
	})), undefined);
	assert.equal(parseStoredSplunkCloudConnection(JSON.stringify({
		accessToken: 'token_1234567890123456',
		realm: 'https://attacker.example',
	})), undefined);
	assert.deepEqual(parseStoredSplunkCloudConnection(JSON.stringify({
		accessToken: 'é'.repeat(2048),
		realm: 'us0',
	})), {
		accessToken: 'é'.repeat(2048),
		realm: 'us0',
	});
	assert.equal(parseStoredSplunkCloudConnection(JSON.stringify({
		accessToken: 'é'.repeat(2049),
		realm: 'us0',
	})), undefined);
	assert.equal(parseStoredSplunkCloudConnection('not-json'), undefined);
});

test('resolveBackend returns observer binary when it exists', () => {
	withTempExtensionRoot((extensionRoot) => {
		const binary = path.join(extensionRoot, 'dist', 'observer', 'obstudio');
		const weaver = path.join(extensionRoot, 'dist', 'observer', hostWeaverBinaryName());

		fs.mkdirSync(path.dirname(binary), { recursive: true });
		fs.writeFileSync(binary, '#!/bin/sh\n');
		fs.writeFileSync(weaver, '#!/bin/sh\n');

		const backend = resolveBackend(extensionRoot);

		assert.equal(backend.command, binary);
		assert.deepEqual(backend.args, []);
		assert.equal(backend.cwd, path.dirname(binary));
		assert.equal(backend.env.WEAVER_PATH, weaver);
		assert.equal(backend.label, 'observer');
	});
});

test('resolveBackend picks a Windows weaver.exe runtime when present', () => {
	withTempExtensionRoot((extensionRoot) => {
		const binary = path.join(extensionRoot, 'dist', 'observer', 'obstudio.exe');
		const weaver = path.join(extensionRoot, 'dist', 'observer', 'weaver.exe');

		fs.mkdirSync(path.dirname(binary), { recursive: true });
		fs.writeFileSync(binary, 'MZ');
		fs.writeFileSync(weaver, 'MZ');

		const backend = resolveBackend(extensionRoot);

		assert.equal(backend.command, binary);
		assert.equal(backend.env.WEAVER_PATH, weaver);
	});
});

test('build output layout reserves the bundled weaver runtime path', () => {
	withTempExtensionRoot((extensionRoot) => {
		const paths = getBuildPaths(extensionRoot);
		const expected = path.join(paths.observerOutDir, hostWeaverBinaryName());

		assert.equal(expected.startsWith(paths.observerOutDir), true);
	});
});

test('build output layout uses an .exe suffix for Windows targets', () => {
	withTempExtensionRoot((extensionRoot) => {
		const paths = getBuildPaths(extensionRoot, {
			OBSTUDIO_GOARCH: 'amd64',
			OBSTUDIO_GOOS: 'windows',
		});

		assert.equal(path.basename(paths.observerOutBinary), 'obstudio.exe');
		assert.equal(paths.target.goos, 'windows');
		assert.equal(paths.target.goarch, 'amd64');
	});
});

test('release Observer builds embed the exact VSIX version', () => {
	withTempExtensionRoot((extensionRoot) => {
		const paths = getBuildPaths(extensionRoot);
		assert.deepEqual(
			observerBuildArgs(paths, { OBSTUDIO_OBSERVER_VERSION: '1.2.3' }),
			[
				'build',
				'-ldflags',
				'-X main.version=1.2.3',
				'-o',
				paths.observerOutBinary,
				'./cmd/obstudio',
			],
		);
	});
});

test('extension Observer builds default to the extension manifest version', () => {
	const packageVersion = JSON.parse(
		fs.readFileSync(path.join(extensionRoot, 'package.json'), 'utf8'),
	) as { version: string };
	assert.equal(observerBuildVersion({}), packageVersion.version);
	assert.throws(
		() => observerBuildVersion({ OBSTUDIO_OBSERVER_VERSION: '1.2.3 -X unsafe=value' }),
		/Invalid Observer build version/,
	);
});

test('package metadata declares an extension icon that exists', () => {
	const packageJSONPath = path.join(extensionRoot, 'package.json');
	const packageJSON = JSON.parse(fs.readFileSync(packageJSONPath, 'utf-8')) as { icon?: string };

	assert.equal(typeof packageJSON.icon, 'string');
	assert.ok(packageJSON.icon);
	assert.equal(fs.existsSync(path.join(extensionRoot, packageJSON.icon!)), true);
});

test('package metadata keeps the VS Code minimum aligned with the API types', () => {
	const packageJSONPath = path.join(extensionRoot, 'package.json');
	const packageJSON = JSON.parse(fs.readFileSync(packageJSONPath, 'utf-8')) as {
		devDependencies?: Record<string, string>;
		engines?: { vscode?: string };
	};

	assert.equal(packageJSON.engines?.vscode, '^1.82.0');
	assert.equal(packageJSON.devDependencies?.['@types/vscode'], '1.82.0');
});

test('package metadata does not replace native paste with a global keybinding', () => {
	const packageJSONPath = path.join(extensionRoot, 'package.json');
	const packageJSON = JSON.parse(fs.readFileSync(packageJSONPath, 'utf-8')) as {
		contributes?: {
			keybindings?: Array<{ command?: string; key?: string; mac?: string; when?: string }>;
		};
	};
	const pasteBinding = packageJSON.contributes?.keybindings?.find(
		(binding) => binding.command === 'observability-studio.internal.pasteIntoObserver',
	);

	assert.equal(pasteBinding, undefined);
});

test('package metadata includes the extension-host WebSocket runtime', () => {
	const packageJSON = JSON.parse(
		fs.readFileSync(path.join(extensionRoot, 'package.json'), 'utf-8'),
	) as { dependencies?: Record<string, string> };
	assert.equal(packageJSON.dependencies?.ws, '8.21.0');
});

test('package metadata declares marketplace categories, tags, and resource links', () => {
	const packageJSONPath = path.join(extensionRoot, 'package.json');
	const packageJSON = JSON.parse(fs.readFileSync(packageJSONPath, 'utf-8')) as {
		bugs?: { url?: string };
		categories?: string[];
		galleryBanner?: { color?: string; theme?: string };
		homepage?: string;
		keywords?: string[];
		repository?: { directory?: string; type?: string; url?: string };
	};

	assert.deepEqual(packageJSON.categories, ['Visualization', 'Other']);
	assert.deepEqual(packageJSON.galleryBanner, { color: '#111827', theme: 'dark' });
	assert.equal(packageJSON.homepage, 'https://github.com/signalfx/obstudio/tree/main/extension');
	assert.equal(packageJSON.bugs?.url, 'https://github.com/signalfx/obstudio/issues');
	assert.deepEqual(packageJSON.repository, {
		directory: 'extension',
		type: 'git',
		url: 'git+https://github.com/signalfx/obstudio.git',
	});
	assert.ok(Array.isArray(packageJSON.keywords));
	assert.ok(packageJSON.keywords!.includes('opentelemetry'));
	assert.ok(packageJSON.keywords!.includes('observability'));
	assert.ok(packageJSON.keywords!.includes('validation'));
	assert.ok(packageJSON.keywords!.includes('debugger'));
	assert.ok(packageJSON.keywords!.includes('debugging'));
	assert.ok(packageJSON.keywords!.includes('devtools'));
	assert.ok(packageJSON.keywords!.includes('developer-tools'));
	assert.ok(packageJSON.keywords!.includes('code-analysis'));
	assert.ok(packageJSON.keywords!.includes('mcp'));
	assert.ok(packageJSON.keywords!.includes('codex'));
	assert.ok(packageJSON.keywords!.includes('devin'));
	assert.ok(packageJSON.keywords!.includes('copilot'));
	assert.ok(packageJSON.keywords!.includes('kiro'));
	assert.ok(packageJSON.keywords!.includes('windsurf'));
	assert.ok(packageJSON.keywords!.length <= 30, `expected <= 30 keywords, got ${packageJSON.keywords!.length}`);
});

test('bundled observer icon uses a high-resolution PNG source', () => {
	const iconPath = path.join(extensionRoot, 'assets', 'observer-icon.png');
	const buffer = fs.readFileSync(iconPath);

	assert.equal(buffer.subarray(0, 8).toString('hex'), '89504e470d0a1a0a');
	const width = buffer.readUInt32BE(16);
	const height = buffer.readUInt32BE(20);

	assert.ok(width >= 512, `expected observer icon width >= 512, got ${width}`);
	assert.ok(height >= 512, `expected observer icon height >= 512, got ${height}`);
});

test('observer webview panel uses the bundled observer icon', () => {
	const extensionSourcePath = path.join(extensionRoot, 'src', 'extension.ts');
	const source = fs.readFileSync(extensionSourcePath, 'utf-8');

	assert.match(source, /panel\.iconPath\s*=\s*\{\s*light:\s*iconUri,\s*dark:\s*iconUri,\s*\}/s);
	assert.match(source, /applyObserverPanelPresentation\(observerPanel,\s*context\)/);
	assert.match(source, /observer-icon\.png/);
});

test('managed observer startup restores cloud export without opening the Cloud tab', () => {
	const extensionSourcePath = path.join(extensionRoot, 'src', 'extension.ts');
	const source = fs.readFileSync(extensionSourcePath, 'utf-8');

	assert.match(
		source,
		/const startupCompleted = await observerCloudLifecycleOperations\.run\(async \(\) => \{[\s\S]*?completeObserverStart\(observerLifecycleState,\s*runId,\s*observerPort\)[\s\S]*?await restoreManagedObserverCloudConnection\(context\);[\s\S]*?return true;[\s\S]*?if \(!startupCompleted\)[\s\S]*?syncObserverUi\(\);/,
	);
});

test('extension treats shared Observer cloud initialization as read-only', () => {
	const extensionSourcePath = path.join(extensionRoot, 'src', 'extension.ts');
	const source = fs.readFileSync(extensionSourcePath, 'utf-8');

	assert.match(
		source,
		/const\s+usesSharedObserver\s*=\s*observerUsesSharedServer;[\s\S]*?refresh:\s*\(\)\s*=>\s*initializeSplunkCloudStatus\(\{[\s\S]*?isManagedObserver:\s*!usesSharedObserver,[\s\S]*?readStatus:\s*\(\)\s*=>\s*getObserverCloudJSON\('\/api\/splunk\/export'\),[\s\S]*?refreshManagedStatus:\s*\(\)\s*=>\s*refreshObserverCloudStatus\(\)/,
	);
});

test('cloud export preference survives managed observer restarts', async () => {
	const stored = {
		accessToken: 'token_1234567890123456',
		realm: 'us0',
	};
	const refreshed = cloudStatus(false, false, false, 'R'.repeat(43));
	const configured = cloudStatus(true, false, true, 'C'.repeat(43));
	const enabled = cloudStatus(true, true, true, 'E'.repeat(43));
	const calls: Array<[string, unknown?]> = [];

	const result = await restoreSplunkCloudConnectionFromStorage({
		configure: async (connection, expectedVersion) => {
			calls.push(['configure', { connection, expectedVersion }]);
			return configured;
		},
		readConnection: async () => {
			calls.push(['readConnection']);
			return stored;
		},
		readExportEnabled: () => {
			calls.push(['readExportEnabled']);
			return true;
		},
		refresh: async () => {
			calls.push(['refresh']);
			return refreshed;
		},
		restoreStoredConnection: true,
		setEnabled: async (value, expectedVersion) => {
			calls.push(['setEnabled', { expectedVersion, value }]);
			return enabled;
		},
	});

	assert.equal(result, enabled);
	assert.deepEqual(calls, [
		['refresh'],
		['readConnection'],
		['configure', { connection: stored, expectedVersion: 'R'.repeat(43) }],
		['readExportEnabled'],
		['setEnabled', { expectedVersion: 'C'.repeat(43), value: true }],
	]);
});

test('transient stored verification failure leaves the managed Observer disconnected', async () => {
	const disconnected = cloudStatus(false, false, false);
	let setEnabledCalled = false;

	await assert.rejects(
		() => restoreSplunkCloudConnectionFromStorage({
			configure: () => verifyStoredSplunkCloudConnection(async () => {
				throw new ObserverCloudResponseError(502, 'Splunk temporarily unavailable');
			}),
			readConnection: async () => ({
				accessToken: 'stored_token_123456789',
				realm: 'us1',
			}),
			readExportEnabled: () => true,
			refresh: async () => disconnected,
			restoreStoredConnection: true,
			setEnabled: async () => {
				setEnabledCalled = true;
				return cloudStatus(true, true, true);
			},
		}),
		(error: unknown) => error instanceof StoredSplunkCloudConnectionVerificationUnavailableError,
	);
	assert.equal(setEnabledCalled, false);
});

test('cloud export restore skips local storage when observer is already configured', async () => {
	const refreshed = cloudStatus(true, false, true);
	let readConnection = false;

	const result = await restoreSplunkCloudConnectionFromStorage({
		configure: async () => {
			throw new Error('configure should not be called');
		},
		readConnection: async () => {
			readConnection = true;
			return undefined;
		},
		readExportEnabled: () => {
			throw new Error('readExportEnabled should not be called');
		},
		refresh: async () => refreshed,
		restoreStoredConnection: true,
		setEnabled: async () => {
			throw new Error('setEnabled should not be called');
		},
	});

	assert.equal(result, refreshed);
	assert.equal(readConnection, false);
});

test('shared Observer initialization never restores this profile\'s stored cloud connection', async () => {
	const refreshed = cloudStatus(false, false, false);
	let readConnection = false;

	const result = await restoreSplunkCloudConnectionFromStorage({
		configure: async () => {
			throw new Error('shared Observer should not be configured automatically');
		},
		readConnection: async () => {
			readConnection = true;
			return { accessToken: 'private_profile_token', realm: 'us1' };
		},
		readExportEnabled: () => {
			throw new Error('shared Observer preference should not be read');
		},
		refresh: async () => refreshed,
		restoreStoredConnection: false,
		setEnabled: async () => {
			throw new Error('shared Observer preference should not be applied');
		},
	});

	assert.equal(result, refreshed);
	assert.equal(readConnection, false);
});

test('shared Observer initialization reads cloud status without mutating its configuration', async () => {
	const calls: string[] = [];
	const status = cloudStatus(true, true, true);

	const result = await initializeSplunkCloudStatus({
		isManagedObserver: false,
		readStatus: async () => {
			calls.push('read');
			return status;
		},
		refreshManagedStatus: async () => {
			calls.push('refresh');
			throw new Error('shared Observer configuration must not be refreshed');
		},
	});

	assert.equal(result, status);
	assert.deepEqual(calls, ['read']);
});

test('managed Observer initialization refreshes its owned cloud configuration', async () => {
	const calls: string[] = [];
	const status = cloudStatus(true, false, true);

	const result = await initializeSplunkCloudStatus({
		isManagedObserver: true,
		readStatus: async () => {
			calls.push('read');
			throw new Error('managed Observer should refresh its owned configuration');
		},
		refreshManagedStatus: async () => {
			calls.push('refresh');
			return status;
		},
	});

	assert.equal(result, status);
	assert.deepEqual(calls, ['refresh']);
});

test('late cloud preference writes repair the newest value before settling', async () => {
	const store = new SplunkCloudExportPreferenceStore();
	let persisted: boolean | undefined;
	let releaseFirst: (() => void) | undefined;
	let markFirstStarted: (() => void) | undefined;
	const firstStarted = new Promise<void>((resolve) => {
		markFirstStarted = resolve;
	});
	const writes: Array<boolean | undefined> = [];
	const first = store.write(true, async (value) => {
		writes.push(value);
		if (writes.length === 1) {
			markFirstStarted?.();
			await new Promise<void>((resolve) => {
				releaseFirst = resolve;
			});
		}
		persisted = value;
	});

	await firstStarted;
	assert.equal(store.read(() => false), true);
	await store.write(false, async (value) => {
		writes.push(value);
		persisted = value;
	});
	assert.equal(persisted, false);

	releaseFirst?.();
	await first;
	assert.equal(persisted, false);
	assert.deepEqual(writes, [true, false, false]);

	await store.write(undefined, async (value) => {
		persisted = value;
	});
	assert.equal(store.read(() => true), undefined);
	assert.equal(persisted, undefined);
});

test('late cloud keychain writes repair the newest credential before settling', async () => {
	const store = new SplunkCloudConnectionStore();
	let persisted: string | undefined;
	let releaseFirst: (() => void) | undefined;
	let markFirstStarted: (() => void) | undefined;
	const firstStarted = new Promise<void>((resolve) => {
		markFirstStarted = resolve;
	});
	const writes: Array<string | undefined> = [];
	const first = store.write('older', async (value) => {
		writes.push(value);
		if (writes.length === 1) {
			markFirstStarted?.();
			await new Promise<void>((resolve) => {
				releaseFirst = resolve;
			});
		}
		persisted = value;
	});

	await firstStarted;
	assert.equal(await store.read(async () => 'durable'), 'older');
	await store.write('newer', async (value) => {
		writes.push(value);
		persisted = value;
	});
	releaseFirst?.();
	await first;
	assert.equal(persisted, 'newer');
	assert.deepEqual(writes, ['older', 'newer', 'newer']);
});

test('rejected cloud preference writes fall back to durable state', async () => {
	const store = new SplunkCloudExportPreferenceStore();
	const failure = new Error('state write failed');
	await assert.rejects(
		store.write(true, async () => {
			throw failure;
		}),
		(error: unknown) => error === failure,
	);
	assert.equal(store.read(() => false), false);

	await store.write(true, async () => undefined);
	assert.equal(store.read(() => false), true);
});

test('a late writer does not retry a newer rejected preference', async () => {
	const store = new SplunkCloudExportPreferenceStore();
	let persisted: boolean | undefined;
	let releaseFirst: (() => void) | undefined;
	let markFirstStarted: (() => void) | undefined;
	const firstStarted = new Promise<void>((resolve) => {
		markFirstStarted = resolve;
	});
	const writes: Array<boolean | undefined> = [];
	const first = store.write(true, async (value) => {
		writes.push(value);
		markFirstStarted?.();
		await new Promise<void>((resolve) => {
			releaseFirst = resolve;
		});
		persisted = value;
	});

	await firstStarted;
	await assert.rejects(
		store.write(false, async (value) => {
			writes.push(value);
			throw new Error('newer write failed');
		}),
		/newer write failed/,
	);
	releaseFirst?.();
	await first;

	assert.deepEqual(writes, [true, false]);
	assert.equal(persisted, true);
	assert.equal(store.read(() => persisted), true);
});

test('cloud connect stores credentials before mutating Observer', async () => {
	const previous = { connectionValue: 'previous', exportEnabled: true };
	const status = cloudStatus(true, false, true);
	const rollbackToken = 'R'.repeat(43);
	const calls: string[] = [];
	const result = await connectSplunkCloudWithStorage({
		configureObserver: async () => {
			calls.push('configureObserver');
			return { ...status, rollbackToken };
		},
		readStoredState: async () => {
			calls.push('readStoredState');
			return previous;
		},
		rollbackObserver: async () => {
			throw new Error('rollbackObserver should not be called');
		},
		rollbackToken,
		restoreStoredState: async () => {
			throw new Error('restoreStoredState should not be called');
		},
		storeConnectedState: async () => {
			calls.push('storeConnectedState');
		},
	});
	assert.deepEqual(result, status);
	assert.equal(Object.prototype.hasOwnProperty.call(result, 'rollbackToken'), false);
	assert.deepEqual(calls, ['readStoredState', 'storeConnectedState', 'configureObserver']);
});

test('cloud connect restores storage without touching Observer when secure storage fails', async () => {
	const previous = { connectionValue: 'previous', exportEnabled: true };
	const calls: string[] = [];
	await assert.rejects(
		() => connectSplunkCloudWithStorage({
			configureObserver: async () => {
				calls.push('configureObserver');
				return cloudStatus(true, false, true);
			},
			readStoredState: async () => {
				calls.push('readStoredState');
				return previous;
			},
			rollbackObserver: async () => {
				calls.push('rollbackObserver');
			},
			rollbackToken: 'R'.repeat(43),
			restoreStoredState: async (state) => {
				assert.deepEqual(state, previous);
				calls.push('restoreStoredState');
			},
			storeConnectedState: async () => {
				calls.push('storeConnectedState');
				throw new Error('keychain unavailable');
			},
		}),
		/Could not store the cloud key securely: keychain unavailable/,
	);
	assert.deepEqual(calls, ['readStoredState', 'storeConnectedState', 'restoreStoredState']);
});

test('cloud connect restores both durable and Observer state after an uncertain mutation', async () => {
	const configureFailure = new Error('connection reset after request upload');
	const rollbackToken = 'R'.repeat(43);
	const previous = { connectionValue: 'previous', exportEnabled: true };
	const calls: string[] = [];

	await assert.rejects(
		() => connectSplunkCloudWithStorage({
			configureObserver: async () => {
				calls.push('configureObserver');
				throw configureFailure;
			},
			readStoredState: async () => {
				calls.push('readStoredState');
				return previous;
			},
			rollbackObserver: async (token) => {
				assert.equal(token, rollbackToken);
				calls.push('rollbackObserver');
			},
			rollbackToken,
			restoreStoredState: async (state) => {
				assert.deepEqual(state, previous);
				calls.push('restoreStoredState');
			},
			storeConnectedState: async () => {
				calls.push('storeConnectedState');
			},
		}),
		(error: unknown) => error === configureFailure,
	);
	assert.deepEqual(calls, [
		'readStoredState',
		'storeConnectedState',
		'configureObserver',
		'restoreStoredState',
		'rollbackObserver',
	]);
});

test('cloud connect does not roll back an authoritative configure rejection', async () => {
	const rejection = new ObserverCloudResponseError(401, 'access token rejected');
	let rollbackCalled = false;

	await assert.rejects(
		() => connectSplunkCloudWithStorage({
			configureObserver: async () => {
				throw rejection;
			},
			readStoredState: async () => ({ connectionValue: 'previous', exportEnabled: true }),
			rollbackObserver: async () => {
				rollbackCalled = true;
			},
			rollbackToken: 'R'.repeat(43),
			restoreStoredState: async () => undefined,
			storeConnectedState: async () => undefined,
		}),
		(error: unknown) => error === rejection,
	);
	assert.equal(rollbackCalled, false);
});

test('cloud connect leaves newer Observer state intact when uncertain rollback conflicts', async () => {
	const configureFailure = new Error('request timed out after upload');

	await assert.rejects(
		() => connectSplunkCloudWithStorage({
			configureObserver: async () => {
				throw configureFailure;
			},
			readStoredState: async () => ({ connectionValue: 'previous', exportEnabled: true }),
			rollbackObserver: async () => {
				throw new ObserverCloudResponseError(409, 'rollback capability is no longer valid');
			},
			rollbackToken: 'R'.repeat(43),
			restoreStoredState: async () => undefined,
			storeConnectedState: async () => undefined,
		}),
		(error: unknown) => error === configureFailure,
	);
});

test('cloud export enable rolls local state back without rewriting Observer after a 4xx rejection', async () => {
	const previous = { connectionValue: 'stored', exportEnabled: false };
	const rejection = new ObserverCloudResponseError(409, 'request rejected');
	const calls: string[] = [];
	await assert.rejects(
		() => setSplunkCloudExportEnabledWithStorage({
			enabled: true,
			readStoredState: async () => {
				calls.push('readStoredState');
				return previous;
			},
			rollbackObserver: async () => {
				throw new Error('authoritative rejection must not roll back Observer state');
			},
			rollbackToken: 'R'.repeat(43),
			restoreStoredExportEnabled: async (enabled) => {
				assert.equal(enabled, false);
				calls.push('restoreStoredExportEnabled');
			},
			setObserverEnabled: async () => {
				calls.push('setObserverEnabled');
				throw rejection;
			},
			storeExportEnabled: async (enabled) => {
				assert.equal(enabled, true);
				calls.push('storeExportEnabled');
			},
		}),
		(error: unknown) => error === rejection,
	);
	assert.deepEqual(calls, [
		'readStoredState',
		'storeExportEnabled',
		'setObserverEnabled',
		'restoreStoredExportEnabled',
	]);
});

test('cloud export enable uses its scoped Observer rollback after an uncertain server failure', async () => {
	const previous = { connectionValue: 'stored', exportEnabled: false };
	const failure = new ObserverCloudResponseError(500, 'server failed');
	const calls: string[] = [];
	await assert.rejects(
		() => setSplunkCloudExportEnabledWithStorage({
			enabled: true,
			readStoredState: async () => previous,
			rollbackObserver: async (token) => {
				assert.equal(token, 'R'.repeat(43));
				calls.push('rollbackObserver');
			},
			rollbackToken: 'R'.repeat(43),
			restoreStoredExportEnabled: async () => {
				calls.push('restoreStoredExportEnabled');
			},
			setObserverEnabled: async () => {
				throw failure;
			},
			storeExportEnabled: async () => {
				calls.push('storeExportEnabled');
			},
		}),
		(error: unknown) => error === failure,
	);
	assert.deepEqual(calls, [
		'storeExportEnabled',
		'restoreStoredExportEnabled',
		'rollbackObserver',
	]);
});

test('cloud forget uses its scoped Observer rollback after an uncertain failure', async () => {
	const previous = { connectionValue: 'stored', exportEnabled: true };
	const failure = new ObserverCloudResponseError(500, 'server failed');
	const calls: string[] = [];
	await assert.rejects(
		() => forgetSplunkCloudWithStorage({
			clearStoredState: async () => {
				calls.push('clearStoredState');
			},
			forgetObserver: async () => {
				calls.push('forgetObserver');
				throw failure;
			},
			readStoredState: async () => {
				calls.push('readStoredState');
				return previous;
			},
			rollbackObserver: async (token) => {
				assert.equal(token, 'R'.repeat(43));
				calls.push('rollbackObserver');
			},
			rollbackToken: 'R'.repeat(43),
			restoreStoredState: async (state) => {
				assert.deepEqual(state, previous);
				calls.push('restoreStoredState');
			},
		}),
		(error: unknown) => error === failure,
	);
	assert.deepEqual(calls, [
		'readStoredState',
		'clearStoredState',
		'forgetObserver',
		'restoreStoredState',
		'rollbackObserver',
	]);
});

test('cloud export recovery does not overwrite a newer Observer winner', async () => {
	const failure = new Error('connection reset');
	await assert.rejects(
		() => setSplunkCloudExportEnabledWithStorage({
			enabled: true,
			readStoredState: async () => ({ connectionValue: 'stored', exportEnabled: false }),
			rollbackObserver: async () => {
				throw new ObserverCloudResponseError(409, 'rollback capability is no longer valid');
			},
			rollbackToken: 'R'.repeat(43),
			restoreStoredExportEnabled: async () => undefined,
			setObserverEnabled: async () => {
				throw failure;
			},
			storeExportEnabled: async () => undefined,
		}),
		(error: unknown) => error === failure,
	);
});

test('cloud mutation helpers keep rollback capabilities inside the extension host', async () => {
	const status = cloudStatus(true, true, true);
	const enabled = await setSplunkCloudExportEnabledWithStorage({
		enabled: true,
		readStoredState: async () => ({ connectionValue: 'stored', exportEnabled: false }),
		rollbackObserver: async () => undefined,
		rollbackToken: 'R'.repeat(43),
		restoreStoredExportEnabled: async () => undefined,
		setObserverEnabled: async () => ({ ...status, rollbackToken: 'R'.repeat(43) }),
		storeExportEnabled: async () => undefined,
	});
	const forgotten = await forgetSplunkCloudWithStorage({
		clearStoredState: async () => undefined,
		forgetObserver: async () => ({ ...status, rollbackToken: 'R'.repeat(43) }),
		readStoredState: async () => ({ connectionValue: 'stored', exportEnabled: true }),
		rollbackObserver: async () => undefined,
		rollbackToken: 'R'.repeat(43),
		restoreStoredState: async () => undefined,
	});
	assert.equal(Object.prototype.hasOwnProperty.call(enabled, 'rollbackToken'), false);
	assert.equal(Object.prototype.hasOwnProperty.call(forgotten, 'rollbackToken'), false);
});

function cloudStatus(
	connected: boolean,
	enabled: boolean,
	configured: boolean,
	version = 'V'.repeat(43),
) {
	return {
		connected,
		enabled,
		metrics: { configured, enabled },
		traces: { configured, enabled },
		version,
	};
}

function cloudConfiguration(
	connected: boolean,
	enabled: boolean,
	accessToken?: string,
	realm?: string,
	changed = true,
) {
	return {
		...(connected ? { accessToken, realm } : {}),
		changed,
		connected,
		enabled,
		version: 'V'.repeat(43),
	};
}

test('extension unload paths stop only the extension-owned Observer process', () => {
	const source = fs.readFileSync(path.join(extensionRoot, 'src', 'extension.ts'), 'utf-8');

	assert.match(source, /export\s+async\s+function\s+deactivate\(\):\s*Promise<void>\s*\{/);
	assert.match(
		source,
		/export\s+async\s+function\s+deactivate[\s\S]*?observerDeactivationStarted\s*=\s*true;[\s\S]*?await\s+shutdownObserverForExtensionUnload\('Extension deactivated'\)/,
	);
	assert.match(
		source,
		/async\s+function\s+stopObserver\(\):\s*Promise<void>[\s\S]*?observerCloudLifecycleOperations\.run\([\s\S]*?terminateObserverProcess\(proc, 'SIGTERM'\)/,
	);
	assert.match(source, /operationCompletesWithin\(\s*stopObserver\(\),\s*observerExtensionUnloadDeadlineMs/);
	assert.match(source, /if\s*\(!stopped\)[\s\S]*?forceDisposeObserverForExtensionUnload\([\s\S]*?'SIGKILL'\)/);
	assert.match(source, /dispose:\s*\(\)\s*=>\s*\{[\s\S]*?disposeObserverForExtensionUnload\('Extension disposed'\)/);
	assert.doesNotMatch(source, /captureSplunkCloudState|shutdown-snapshot|persistManagedObserverCloudState/);
});

test('resolveBackend throws when the observer binary is missing', () => {
	withTempExtensionRoot((extensionRoot) => {
		assert.throws(() => resolveBackend(extensionRoot), /observer binary not found/);
	});
});

test('normalizeObserverBaseUrl accepts loopback base URLs and /mcp URLs', () => {
	assert.equal(normalizeObserverBaseUrl('http://127.0.0.1:3000'), 'http://127.0.0.1:3000');
	assert.equal(normalizeObserverBaseUrl('http://127.0.0.1:3000/'), 'http://127.0.0.1:3000');
	assert.equal(normalizeObserverBaseUrl('http://127.0.0.1:3000/mcp'), 'http://127.0.0.1:3000');
	assert.equal(normalizeObserverBaseUrl('http://[::]:3000/mcp'), 'http://[::1]:3000');
	assert.equal(normalizeObserverBaseUrl('https://localhost:3000/observer/mcp'), 'https://localhost:3000/observer');
});

test('normalizeObserverBaseUrl rejects every non-loopback host', () => {
	for (const raw of [
		'http://localhost:3000',
		'http://LOCALHOST.:3000',
		'http://127.0.0.1:3000',
		'http://127.42.0.9:3000',
		'http://[::1]:3000',
		'http://0.0.0.0:3000',
		'http://[::]:3000',
		'https://localhost:3000',
	]) {
		assert.doesNotThrow(() => normalizeObserverBaseUrl(raw), raw);
	}

	for (const raw of [
		'http://example.com:3000',
		'https://example.com:3000',
		'http://10.0.0.1:3000',
		'http://localhost.example.com:3000',
		'http://127.0.0.1.example.com:3000',
		'http://[::2]:3000',
	]) {
		assert.throws(() => normalizeObserverBaseUrl(raw), /host must be loopback/, raw);
	}
});

test('isLoopbackObserverHost recognizes only supported loopback host forms', () => {
	for (const hostname of ['localhost', 'LOCALHOST.', '127.0.0.1', '127.42.0.9', '::1', '[::1]']) {
		assert.equal(isLoopbackObserverHost(hostname), true, hostname);
	}
	for (const hostname of ['localhost.example.com', '127.0.0.1.example.com', '::2', '192.168.1.2']) {
		assert.equal(isLoopbackObserverHost(hostname), false, hostname);
	}
});

test('normalizeObserverBaseUrl rejects URL credentials and fragments', () => {
	for (const raw of ['https://user:password@localhost/observer', 'https://@localhost/observer']) {
		assert.throws(() => normalizeObserverBaseUrl(raw), /must not include user information/, raw);
	}
	for (const raw of ['https://localhost/observer#fragment', 'https://localhost/observer#']) {
		assert.throws(() => normalizeObserverBaseUrl(raw), /must not include a fragment/, raw);
	}
});

test('buildObserverValidatorSummaryUrl uses a normalized loopback Observer URL', () => {
	assert.equal(
		buildObserverValidatorSummaryUrl('http://127.0.0.1:3000/mcp'),
		'http://127.0.0.1:3000/api/query/validation/summary',
	);
	assert.equal(
		buildObserverValidatorSummaryUrl('https://localhost/observer/'),
		'https://localhost/observer/api/query/validation/summary',
	);
});

test('buildObserverHealthUrl uses a normalized loopback Observer URL', () => {
	assert.equal(
		buildObserverHealthUrl('http://127.0.0.1:3000/mcp'),
		'http://127.0.0.1:3000/api/health',
	);
	assert.equal(
		buildObserverHealthUrl('https://localhost/observer/'),
		'https://localhost/observer/api/health',
	);
});

test('observerPortFromUrl returns explicit and default loopback ports', () => {
	assert.equal(observerPortFromUrl('http://127.0.0.1:3000'), 3000);
	assert.equal(observerPortFromUrl('https://localhost'), 443);
	assert.equal(observerPortFromUrl('http://127.0.0.2/service/mcp'), 80);
});

test('readSharedObserverDiscovery ignores legacy credentials and keeps local endpoints', () => {
	const homeDir = fs.mkdtempSync(path.join(os.tmpdir(), 'obstudio-home-'));
	try {
		const stateDir = path.join(homeDir, '.obstudio');
		fs.mkdirSync(stateDir, { recursive: true });
		writePrivateSharedObserverState(
			path.join(stateDir, 'shared-observer.json'),
			{
				baseUrl: 'http://127.0.0.1:3001/',
				controlToken: 'legacy-control-token',
				healthProofSecret: 'legacy-health-proof',
				healthUrl: 'http://127.0.0.1:3001/api/health',
				mcpUrl: 'http://127.0.0.1:3001/mcp',
				pid: 3210,
				updatedAt: '2026-07-28T07:08:55.652888Z',
			},
		);

		assert.deepEqual(readSharedObserverDiscovery(homeDir), {
			baseUrl: 'http://127.0.0.1:3001',
			healthUrl: 'http://127.0.0.1:3001/api/health',
			mcpUrl: 'http://127.0.0.1:3001/mcp',
			pid: 3210,
			updatedAtMs: Date.parse('2026-07-28T07:08:55.652888Z'),
		});
	} finally {
		fs.rmSync(homeDir, { force: true, recursive: true });
	}
});

test('findOtherExtensionManagedObserver identifies only a matching sibling extension process', () => {
	const root = fs.mkdtempSync(path.join(os.tmpdir(), 'obstudio-upgrade-'));
	try {
		const currentExtensionPath = path.join(root, 'splunk.observability-studio-current');
		const otherExtensionPath = path.join(root, 'splunk.observability-studio-previous');
		const otherBinaryPath = path.join(
			otherExtensionPath,
			'dist',
			'observer',
			process.platform === 'win32' ? 'obstudio.exe' : 'obstudio',
		);
		fs.mkdirSync(currentExtensionPath, { recursive: true });
		fs.mkdirSync(path.dirname(otherBinaryPath), { recursive: true });
		fs.writeFileSync(path.join(otherExtensionPath, 'package.json'), JSON.stringify({
			name: 'observability-studio',
			publisher: 'Splunk',
			version: 'previous-install',
		}));
		fs.writeFileSync(otherBinaryPath, 'fixture');

		const discovery = { baseUrl: 'http://127.0.0.1:3000', pid: 4321 };
		const expected = {
			binaryPath: otherBinaryPath,
			pid: 4321,
			version: 'previous-install',
		};
		assert.deepEqual(findOtherExtensionManagedObserver({
			currentExtensionPath,
			discovery,
			processExecutablePath: otherBinaryPath,
		}), expected);

		for (const changes of [
			{ processExecutablePath: '/usr/local/bin/obstudio' },
			{ processExecutablePath: `${otherBinaryPath}-helper` },
			{ processExecutablePath: path.join(root, 'unrelated', 'obstudio') },
			{ discovery: { baseUrl: discovery.baseUrl } },
		]) {
			assert.equal(findOtherExtensionManagedObserver({
				currentExtensionPath,
				discovery,
				processExecutablePath: otherBinaryPath,
				...changes,
			}), undefined);
		}

		if (process.platform !== 'win32') {
			const externalBinaryPath = path.join(root, 'unrelated-obstudio');
			fs.writeFileSync(externalBinaryPath, 'fixture');
			fs.unlinkSync(otherBinaryPath);
			fs.symlinkSync(externalBinaryPath, otherBinaryPath);
			assert.equal(findOtherExtensionManagedObserver({
				currentExtensionPath,
				discovery,
				processExecutablePath: otherBinaryPath,
			}), undefined);
		}
	} finally {
		fs.rmSync(root, { force: true, recursive: true });
	}
});

test('readSharedObserverDiscovery rejects state that is not owner-only', () => {
	if (process.platform === 'win32') {
		return;
	}
	const homeDir = fs.mkdtempSync(path.join(os.tmpdir(), 'obstudio-home-'));
	try {
		const stateDir = path.join(homeDir, '.obstudio');
		fs.mkdirSync(stateDir, { recursive: true });
		const statePath = path.join(stateDir, 'shared-observer.json');
		fs.writeFileSync(statePath, JSON.stringify({ baseUrl: 'http://127.0.0.1:3001' }), { mode: 0o644 });
		fs.chmodSync(statePath, 0o644);
		assert.equal(readSharedObserverDiscovery(homeDir), undefined);
	} finally {
		fs.rmSync(homeDir, { force: true, recursive: true });
	}
});

test('readSharedObserverDiscovery rejects a symlinked state file', () => {
	if (process.platform === 'win32') {
		return;
	}
	const homeDir = fs.mkdtempSync(path.join(os.tmpdir(), 'obstudio-home-'));
	try {
		const stateDir = path.join(homeDir, '.obstudio');
		fs.mkdirSync(stateDir, { recursive: true });
		const victimPath = path.join(stateDir, 'victim.json');
		writePrivateSharedObserverState(victimPath, { baseUrl: 'http://127.0.0.1:3001' });
		fs.symlinkSync(victimPath, path.join(stateDir, 'shared-observer.json'));
		assert.equal(readSharedObserverDiscovery(homeDir), undefined);
	} finally {
		fs.rmSync(homeDir, { force: true, recursive: true });
	}
});

test('readSharedObserverDiscovery rejects a group-writable parent', () => {
	if (process.platform === 'win32') {
		return;
	}
	const homeDir = fs.mkdtempSync(path.join(os.tmpdir(), 'obstudio-home-'));
	const stateDir = path.join(homeDir, '.obstudio');
	try {
		fs.mkdirSync(stateDir, { recursive: true });
		writePrivateSharedObserverState(
			path.join(stateDir, 'shared-observer.json'),
			{ baseUrl: 'http://127.0.0.1:3001' },
		);
		fs.chmodSync(stateDir, 0o770);
		assert.equal(readSharedObserverDiscovery(homeDir), undefined);
	} finally {
		fs.chmodSync(stateDir, 0o700);
		fs.rmSync(homeDir, { force: true, recursive: true });
	}
});

test('readSharedObserverDiscovery rejects plaintext non-local shared observer state', () => {
	const homeDir = fs.mkdtempSync(path.join(os.tmpdir(), 'obstudio-home-'));
	try {
		const stateDir = path.join(homeDir, '.obstudio');
		fs.mkdirSync(stateDir, { recursive: true });
		writePrivateSharedObserverState(
			path.join(stateDir, 'shared-observer.json'),
			{
				baseUrl: 'http://observer.example.test:3001',
				healthUrl: 'http://observer.example.test:3001/api/health',
				mcpUrl: 'http://observer.example.test:3001/mcp',
			},
		);

		assert.equal(readSharedObserverDiscovery(homeDir), undefined);
	} finally {
		fs.rmSync(homeDir, { force: true, recursive: true });
	}
});

test('local Observer operations accept only loopback hosts', () => {
	for (const hostname of [
		'localhost',
		'127.0.0.1',
		'127.0.0.2',
		'::1',
		'[::1]',
	]) {
		assert.equal(isLoopbackObserverHost(hostname), true, hostname);
	}
	for (const hostname of [
		'0.0.0.0',
		'::',
		'[::]',
		'192.0.2.10',
		'example.test',
		'127.example.test',
		'127.999.0.1',
	]) {
		assert.equal(isLoopbackObserverHost(hostname), false, hostname);
	}
});

test('shared Observer URLs normalize wildcard listeners and reject every non-loopback host', () => {
	assert.equal(normalizeSharedObserverBaseUrl('http://0.0.0.0:3001'), 'http://127.0.0.1:3001');
	assert.equal(normalizeSharedObserverBaseUrl('http://[::]:3001/mcp'), 'http://[::1]:3001');
	assert.equal(normalizeSharedObserverBaseUrl('http://LOCALHOST.:3001/mcp'), 'http://localhost:3001');
	assert.equal(normalizeSharedObserverBaseUrl('http://127.0.0.2:3001'), 'http://127.0.0.2:3001');
	assert.equal(
		normalizeSharedObserverHealthUrl('http://0.0.0.0:3001/api/health'),
		'http://127.0.0.1:3001/api/health',
	);
	assert.throws(
		() => normalizeSharedObserverBaseUrl('http://observer.example.test:3001'),
		/host must be loopback/,
	);
	assert.throws(
		() => normalizeSharedObserverBaseUrl('https://observer.example.test:3001'),
		/host must be loopback/,
	);
	assert.throws(
		() => normalizeSharedObserverMCPUrl('https://observer.example.test/team/mcp'),
		/host must be loopback/,
	);
});

test('managed startup strips obsolete control credentials and public endpoints', () => {
	const source = fs.readFileSync(path.join(extensionRoot, 'src', 'extension.ts'), 'utf8');
	assert.match(source, /OBSTUDIO_OWNER: extensionManagedObserverOwner/);
	assert.match(source, /OBSTUDIO_MODE: extensionManagedObserverMode/);
	assert.match(
		source,
		/delete managedObserverEnvironment\.OBSTUDIO_CONTROL_TOKEN;[\s\S]*?delete managedObserverEnvironment\.OBSTUDIO_HEALTH_PROOF_SECRET;[\s\S]*?delete managedObserverEnvironment\.OBSTUDIO_PUBLIC_MCP_URL;[\s\S]*?cp\.spawn/,
	);
});

test('agent integration install writes a credential-free local MCP endpoint', () => {
	const source = fs.readFileSync(path.join(extensionRoot, 'src', 'extension.ts'), 'utf8');
	const configureStart = source.indexOf('async function configureAgentMCP(');
	const configureEnd = source.indexOf('\nfunction execFile(', configureStart);
	assert.notEqual(configureStart, -1);
	assert.notEqual(configureEnd, -1);
	const configureHandling = source.slice(configureStart, configureEnd);
	assert.match(configureHandling, /agentIntegrationConfigurationQueue\.run\(/);
	assert.match(
		configureHandling,
		/\['install', '--target', target, '--shared-url', mcpUrl\][\s\S]*?backend\.env/,
	);
	assert.match(
		configureHandling,
		/getAgentIntegrationConfigState\(spec, mcpUrl\)[\s\S]*?recordAgentIntegrationConfigFingerprint\(context, spec, mcpUrl, installedConfig\)/,
	);
	assert.doesNotMatch(configureHandling, /controlToken|healthProof|Authorization/);
});

test('automatic agent refresh removes stale authentication before prompting', () => {
	const source = fs.readFileSync(path.join(extensionRoot, 'src', 'extension.ts'), 'utf8');
	const offerStart = source.indexOf('async function maybeOfferDetectedAgentIntegrations(');
	const offerEnd = source.indexOf('\nasync function configureAgentMCP(', offerStart);
	assert.notEqual(offerStart, -1);
	assert.notEqual(offerEnd, -1);
	const offerHandling = source.slice(offerStart, offerEnd);
	assert.match(
		offerHandling,
		/await refreshOwnedAgentIntegrationConfig\(context, detectedSpecs, mcpUrl\)[\s\S]*?showInformationMessage\(/,
	);

	const refreshStart = source.indexOf('function refreshOwnedAgentIntegrationConfig(');
	const refreshEnd = source.indexOf('\nasync function maybeOfferDetectedAgentIntegrations(', refreshStart);
	assert.notEqual(refreshStart, -1);
	assert.notEqual(refreshEnd, -1);
	const refreshHandling = source.slice(refreshStart, refreshEnd);
	assert.match(refreshHandling, /getAgentIntegrationConfigState\(spec, mcpUrl\) === 'different'/);
	assert.match(refreshHandling, /shouldRefreshOwnedAgentIntegrationConfig\(/);
	assert.match(refreshHandling, /const refreshable = specs\.filter\(shouldRefresh\)/);
	assert.match(
		refreshHandling,
		/await configureDetectedAgentIntegrations\([\s\S]*?observerEndpoints\?\.mcpUrl === mcpUrl,[\s\S]*?shouldRefresh/,
	);
	assert.doesNotMatch(refreshHandling, /controlToken|healthProof/);
});

test('shared startup validates health without a credential or feature probe', () => {
	const source = fs.readFileSync(path.join(extensionRoot, 'src', 'extension.ts'), 'utf8');
	assert.match(
		source,
		/waitForObserverReady\(\s*configuredEndpoints,\s*\{ requireStableOtlp: false \},\s*runId,\s*\)/,
	);
	assert.match(
		source,
		/probeObserver\([\s\S]*?discoveredEndpoints,[\s\S]*?\{ requireStableOtlp: true \}/,
	);
	assert.match(source, /const target = new URL\(endpoints\.healthUrl\)/);
	const probeStart = source.indexOf('async function probeObserver(');
	const probeEnd = source.indexOf('\nfunction validateObserverHealth(', probeStart);
	const probe = source.slice(probeStart, probeEnd);
	assert.doesNotMatch(probe, /challenge|proof|token|Authorization/i);
});

test('upgrade retirement verifies Observer health and the executable path before terminating a PID', () => {
	const source = fs.readFileSync(path.join(extensionRoot, 'src', 'extension.ts'), 'utf8');
	const startupStart = source.indexOf('async function startObserver(');
	const startupEnd = source.indexOf('\nasync function retireOtherExtensionManagedObserver(', startupStart);
	const startup = source.slice(startupStart, startupEnd);
	assert.match(
		startup,
		/let discoveryProbe = await probeObserver\([\s\S]*?const retirement = await retireOtherExtensionManagedObserver\([\s\S]*?discoveryProbe\.status === 'ready'/,
	);

	const retirementStart = startupEnd + 1;
	const retirementEnd = source.indexOf('\nasync function waitForProcessExit(', retirementStart);
	const retirement = source.slice(retirementStart, retirementEnd);
	assert.match(
		retirement,
		/const bundleVersion = getBundleVersion\(context\);[\s\S]*?observerVersion === bundleVersion/,
	);
	assert.match(
		retirement,
		/observerHealth\?\.owner !== extensionManagedObserverOwner[\s\S]*?observerHealth\.mode !== extensionManagedObserverMode/,
	);
	assert.ok(
		retirement.indexOf('if (!processIsRunning(pid))')
			< retirement.indexOf('observerHealth?.owner !== extensionManagedObserverOwner'),
		'a dead recorded PID must be treated as stale before requiring a live Observer ownership marker',
	);
	assert.ok(
		retirement.indexOf('observerHealth?.owner !== extensionManagedObserverOwner')
			< retirement.indexOf('const processExecutablePath = await readProcessExecutablePath'),
		'extension ownership must be established before inspecting or terminating the recorded PID',
	);
	assert.ok(
		retirement.indexOf('const preStopExecutablePath = await readProcessExecutablePath')
			< retirement.indexOf('await gracefullyTerminateProcess(otherExtensionObserver.pid)'),
		'the actual executable must be reverified immediately before graceful termination',
	);
	assert.doesNotMatch(
		retirement,
		/process\.kill\(otherExtensionObserver\.pid, 'SIGTERM'\)/,
		'the upgrade path must not treat Node SIGTERM as graceful on Windows',
	);
	assert.doesNotMatch(retirement, /readProcessCommand|processCommand/);
});

test('all local Observer reuse paths use the same bundled-version compatibility rule', () => {
	const source = fs.readFileSync(path.join(extensionRoot, 'src', 'extension.ts'), 'utf8');
	const startupStart = source.indexOf('async function startObserver(');
	const startupEnd = source.indexOf('\nasync function retireOtherExtensionManagedObserver(', startupStart);
	const startup = source.slice(startupStart, startupEnd);
	assert.match(startup, /const bundleVersion = getBundleVersion\(context\)/);
	assert.match(startup, /configuredProbe\.health\.version !== bundleVersion/);
	assert.match(
		startup,
		/managedProbe\.status === 'ready'[\s\S]*?retireOtherExtensionManagedObserver\([\s\S]*?managedProbe\.health/,
	);
	assert.match(startup, /existingObserver\.health\.version !== bundleVersion/);
	assert.match(startup, /startedProbe\.health\.version !== bundleVersion/);
	assert.doesNotMatch(startup, /0\.0\.18|0\.0\.20/);
});

test('manual lifecycle and panel commands settle configuration-triggered restarts before acting', () => {
	const source = fs.readFileSync(path.join(extensionRoot, 'src', 'extension.ts'), 'utf8');
	for (const command of ['openObserver', 'startObserver', 'stopObserver', 'restartObserver']) {
		const start = source.indexOf(`registerCommand('observability-studio.${command}', async () => {`);
		assert.notEqual(start, -1);
		const body = source.slice(start, source.indexOf('\n\t});', start));
		assert.match(body, /await settleObserverConfigurationRestart\(\);/);
	}
	const openStart = source.indexOf("registerCommand('observability-studio.openObserver', async () => {");
	const openBody = source.slice(openStart, source.indexOf('\n\t});', openStart));
	assert.match(
		openBody,
		/await openObserverPanel\(context\);/,
		'Open Observer must not resolve before its panel startup attempt finishes',
	);
	const stopStart = source.indexOf("registerCommand('observability-studio.stopObserver', async () => {");
	const stopBody = source.slice(stopStart, source.indexOf('\n\t});', stopStart));
	assert.match(
		stopBody,
		/observerBaseUrl === undefined[\s\S]*?observerLifecycleState\.status === 'stopped'/,
		'Stop must clear an idle startup error instead of returning before the lifecycle reset',
	);
});

function waitForObserverReadySource(): string {
	const source = fs.readFileSync(path.join(extensionRoot, 'src', 'extension.ts'), 'utf8');
	const start = source.indexOf('async function waitForObserverReady(');
	const end = source.indexOf('\nasync function probeObserver(', start);
	assert.notEqual(start, -1);
	assert.notEqual(end, -1);
	return source.slice(start, end);
}

test('a health mismatch retries with a bounded delay rather than an immediate failure', () => {
	// Regression coverage for the Cisco-Secure-Endpoint-content-filter false mismatch:
	// a mismatch below the attempt limit must retry, not throw on the first attempt.
	assert.match(
		waitForObserverReadySource(),
		/case 'mismatch': \{\n\t+mismatchAttempts \+= 1;[\s\S]*?if \(mismatchAttempts < maxMismatchAttempts\) \{[\s\S]*?await delay\(mismatchRetryDelayMs\);[\s\S]*?break;\n\t+\}/,
	);
});

test('a health mismatch throws once the attempt limit is reached, not retrying indefinitely', () => {
	const source = waitForObserverReadySource();
	assert.match(source, /const maxMismatchAttempts = 6;/);
	assert.match(
		source,
		/if \(mismatchAttempts < maxMismatchAttempts\) \{[\s\S]*?break;\n\t+\}\n\t+const mismatchContext[\s\S]*?throw wrappedError;/,
	);
});

test('readSharedObserverDiscovery ignores missing, malformed, and incomplete state', () => {
	const homeDir = fs.mkdtempSync(path.join(os.tmpdir(), 'obstudio-home-'));
	try {
		assert.equal(readSharedObserverDiscovery(homeDir), undefined);

		const stateDir = path.join(homeDir, '.obstudio');
		fs.mkdirSync(stateDir, { recursive: true });
		const statePath = path.join(stateDir, 'shared-observer.json');
		fs.writeFileSync(statePath, '{', { mode: 0o600 });
		fs.chmodSync(statePath, 0o600);
		assert.equal(readSharedObserverDiscovery(homeDir), undefined);

		writePrivateSharedObserverState(statePath, { healthUrl: 'http://127.0.0.1:3001/api/health' });
		assert.equal(readSharedObserverDiscovery(homeDir), undefined);
	} finally {
		fs.rmSync(homeDir, { force: true, recursive: true });
	}
});

test('normalizeObserverBaseUrl rejects unsupported schemes', () => {
	assert.throws(() => normalizeObserverBaseUrl('stdio://obstudio'), /http or https/);
});

test('resetObserverOutputDirs recreates observer and webview output directories', () => {
	withTempExtensionRoot((extensionRoot) => {
		const paths = getBuildPaths(extensionRoot);

		fs.mkdirSync(paths.observerOutDir, { recursive: true });
		fs.mkdirSync(paths.webviewOutDir, { recursive: true });
		fs.writeFileSync(path.join(paths.observerOutDir, 'stale.txt'), 'stale');
		fs.writeFileSync(path.join(paths.webviewOutDir, 'stale.txt'), 'stale');

		resetObserverOutputDirs(paths);

		assert.equal(fs.existsSync(path.join(paths.observerOutDir, 'stale.txt')), false);
		assert.equal(fs.existsSync(path.join(paths.webviewOutDir, 'stale.txt')), false);
		assert.equal(fs.existsSync(paths.observerOutDir), true);
		assert.equal(fs.existsSync(paths.webviewOutDir), true);
	});
});

test('buildClientAssets rebuilds and stages the same client assets for the top-level webview', () => {
	const repoRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'obstudio-build-client-'));
	try {
		const fakeExtensionRoot = path.join(repoRoot, 'extension');
		fs.mkdirSync(fakeExtensionRoot);
		const paths = getBuildPaths(fakeExtensionRoot);
		fs.mkdirSync(paths.clientAssetsDir, { recursive: true });
		fs.mkdirSync(paths.webviewOutDir, { recursive: true });
		for (const asset of ['main.css', 'main.js', 'observer-icon.svg']) {
			fs.writeFileSync(path.join(paths.clientAssetsDir, asset), `built ${asset}`);
		}

		const calls: Array<{ args: string[]; cwd: string; file: string }> = [];
		buildClientAssets(paths, (file, args, options) => {
			calls.push({ args, cwd: options.cwd, file });
		});

		assert.deepEqual(calls, [{
			args: ['run', './cmd/build-client'],
			cwd: paths.observerRoot,
			file: 'go',
		}]);
		for (const asset of ['main.css', 'main.js', 'observer-icon.svg']) {
			assert.equal(
				fs.readFileSync(path.join(paths.webviewOutDir, asset), 'utf8'),
				`built ${asset}`,
			);
		}
	} finally {
		fs.rmSync(repoRoot, { force: true, recursive: true });
	}
});

test('skill docs ids cover the skills the Overview tab offers', () => {
	// The client lists these commands; the extension owns their URLs. If the two
	// drift, the webview's docs links silently stop opening.
	for (const expected of [
		'otel-audit',
		'otel-instrument',
		'otel-verify',
		'splunk-configure',
		'splunk-detector-publish',
		'splunk-dashboard-publish',
	]) {
		assert.ok(isSkillDocsId(expected), `${expected} should be a known skill id`);
	}
	assert.equal(skillDocsIds.length, 6);
	assert.equal(isSkillDocsId('splunk-sync'), false);
	assert.equal(isSkillDocsId(''), false);
});

test('every skill id maps to its own documentation URL', () => {
	// A broken or duplicated mapping would otherwise only surface as a dead
	// link inside the IDE webview, which the unit suite cannot drive.
	const seen = new Set<string>();
	for (const skill of skillDocsIds) {
		const url = skillDocsUrl(skill);
		assert.ok(url, `${skill} has no documentation URL`);
		assert.equal(
			url,
			`https://github.com/signalfx/obstudio/blob/main/skills/${skill}/SKILL.md`,
			`${skill} maps to an unexpected URL`,
		);
		assert.ok(!seen.has(url!), `${skill} reuses another skill's URL`);
		seen.add(url!);
	}
	assert.equal(seen.size, skillDocsIds.length);
});

test('unknown skill ids resolve to no URL', () => {
	for (const bogus of ['splunk-sync', 'https://evil.example.com', '../../etc/passwd', '', undefined, null, 7]) {
		assert.equal(skillDocsUrl(bogus), undefined, `${String(bogus)} should not resolve`);
	}
});

test('IDE host accepts the audit report action without a payload', () => {
	assert.equal(isObserverHostRequestEnvelope({
		request: { action: 'open-audit-report', kind: 'cloud' },
		requestId: 'request-123',
		type: 'obstudio.host.request',
	}), true);
	// The webview names the action only; it can never smuggle a destination.
	assert.equal(isObserverHostRequestEnvelope({
		request: {
			action: 'open-audit-report',
			kind: 'cloud',
			payload: { url: 'https://evil.example.com' },
		},
		requestId: 'request-123',
		type: 'obstudio.host.request',
	}), false);
});

test('audit report URL is built from the observer base URL alone', () => {
	assert.equal(auditReportUrl('http://127.0.0.1:3000'), `http://127.0.0.1:3000${auditReportPath}`);
	// A base URL carrying a path must not produce a nested report path.
	assert.equal(auditReportUrl('http://127.0.0.1:3000/ui/'), `http://127.0.0.1:3000${auditReportPath}`);
	assert.equal(auditReportUrl('https://observer.example.com'), `https://observer.example.com${auditReportPath}`);

	// Nothing usable produces no URL, so the caller reports it rather than
	// opening something unintended.
	assert.equal(auditReportUrl(undefined), undefined);
	assert.equal(auditReportUrl(''), undefined);
	assert.equal(auditReportUrl('   '), undefined);
	assert.equal(auditReportUrl('not a url'), undefined);
	assert.equal(auditReportUrl(3000), undefined);
	// Only http(s): a file: or javascript: base must never be opened.
	assert.equal(auditReportUrl('file:///etc/passwd'), undefined);
	assert.equal(auditReportUrl('javascript:alert(1)'), undefined);
});

class FakeObserverWebSocket {
	closed = false;
	readyState: number = WebSocket.CONNECTING;
	readonly sent: string[] = [];
	private readonly listeners = new Map<string, Array<(...args: unknown[]) => void>>();

	on(event: string, listener: (...args: unknown[]) => void): this {
		const listeners = this.listeners.get(event) ?? [];
		listeners.push(listener);
		this.listeners.set(event, listeners);
		return this;
	}

	emit(event: string, ...args: unknown[]): void {
		for (const listener of this.listeners.get(event) ?? []) {
			listener(...args);
		}
	}

	send(message: string): void {
		this.sent.push(message);
	}

	removeAllListeners(): this {
		this.listeners.clear();
		return this;
	}

	close(): void {
		this.closed = true;
		this.readyState = WebSocket.CLOSED;
	}

	terminate(): void {
		this.close();
	}
}
