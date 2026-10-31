import * as assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import * as fs from 'node:fs';
import * as net from 'node:net';
import * as os from 'node:os';
import * as path from 'node:path';
import { performance } from 'node:perf_hooks';
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
	splunkSearchURLFromStatus,
	freeAccountSubmissionFailureIsOutcomeUnknown,
	initializeCloudBridgeState,
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
import {
	LoopbackPortReservations,
	loopbackPortsAreSimultaneouslyAvailable,
} from '../observer-port-handoff';

const extensionRoot = path.resolve(__dirname, '..', '..');

test('Splunk Search consumes the backend Web URL and does not guess from HEC', () => {
	const searchURL = 'https://stack.splunkcloud.com/en-US/app/search/search?q=search+index%3D%22studio%22';
	assert.equal(splunkSearchURLFromStatus({ endpoint: 'https://http-inputs-stack.splunkcloud.com/services/collector', index: 'studio', searchURL }), searchURL);
	for (const value of [undefined, {}, { endpoint: 'https://enterprise.example:8088/services/collector', index: 'studio' }, { searchURL: 'javascript:alert(1)' }, { searchURL: 'https://user:secret@example.com/' }, { searchURL: 'bad URL' }]) {
		assert.equal(splunkSearchURLFromStatus(value), undefined);
	}
});
const {
	buildClientAssets,
	bundleCopilotSkills,
	getBuildPaths,
	observerBuildArgs,
	observerBuildVersion,
	resetObserverOutputDirs,
	stageSkills,
} = require('../../build-observer.js') as {
	bundleCopilotSkills: (paths: ReturnType<typeof getBuildPaths>) => void;
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
		skillsOutDir: string;
	};
	observerBuildArgs: (
		paths: ReturnType<typeof getBuildPaths>,
		env?: NodeJS.ProcessEnv,
	) => string[];
	observerBuildVersion: (env?: NodeJS.ProcessEnv) => string;
	resetObserverOutputDirs: (paths: ReturnType<typeof getBuildPaths>) => void;
	stageSkills: (
		paths: ReturnType<typeof getBuildPaths>,
		run?: (file: string, args: string[], options: { cwd: string; stdio: string }) => unknown,
	) => void;
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
	assert.equal(isObserverHostRequestEnvelope(cloudRequest('set-enabled', {
		enabled: true,
		scope: 'observability',
	})), true);
	assert.equal(isObserverHostRequestEnvelope(cloudRequest('set-enabled', {
		enabled: true,
		scope: 'unknown',
	})), false);
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

test('Splunk Observability Studio cloud errors expose only allowlisted signup metadata', () => {
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
			'Splunk Observability Studio control unavailable',
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

test('Free Edition success requires a complete acknowledged Splunk Observability Studio result', () => {
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

test('agent integration refresh gates on ownership, independent of the target URL', () => {
	// The fingerprint obstudio recorded when it last wrote this config at :3000.
	const storedUrl = 'http://127.0.0.1:3000/mcp';
	const original = {
		fingerprintMaterial: JSON.stringify({
			headers: { Authorization: 'Bearer prior-control-token' },
			type: 'http',
			url: storedUrl,
		}),
		mcpUrl: storedUrl,
	};
	const fingerprint = createAgentIntegrationConfigFingerprint(original);

	// Secrets never leak into the fingerprint.
	assert.equal(JSON.stringify(fingerprint).includes('prior-control-token'), false);

	// Owned + on-disk unchanged: refreshes. The function no longer takes a target
	// URL, so an owned config left at a stale :3000 (shape drift or URL-moved to a
	// new fixed :17900 target) still qualifies for a silent rewrite.
	assert.equal(shouldRefreshOwnedAgentIntegrationConfig(fingerprint, original), true);

	// User hand-edited the managed material: digest differs → bail (visible prompt).
	assert.equal(shouldRefreshOwnedAgentIntegrationConfig(fingerprint, {
		...original,
		fingerprintMaterial: original.fingerprintMaterial.replace('prior-control-token', 'user-control-token'),
	}), false);
	assert.equal(shouldRefreshOwnedAgentIntegrationConfig(fingerprint, {
		...original,
		fingerprintMaterial: original.fingerprintMaterial.replace('"type":"http"', '"disabled":true,"type":"http"'),
	}), false);

	// On-disk url differs from the recorded fingerprint url (not an obstudio-owned
	// state) → bail.
	assert.equal(shouldRefreshOwnedAgentIntegrationConfig(fingerprint, {
		...original,
		mcpUrl: 'http://127.0.0.1:4000/mcp',
	}), false);

	// Missing current config / missing fingerprint / malformed digest → bail.
	assert.equal(shouldRefreshOwnedAgentIntegrationConfig(fingerprint, undefined), false);
	assert.equal(shouldRefreshOwnedAgentIntegrationConfig(undefined, original), false);
	assert.equal(shouldRefreshOwnedAgentIntegrationConfig({
		...fingerprint,
		configurationDigest: 'not-a-digest',
	}, original), false);
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

test('Splunk Observability Studio-mutating Cloud actions serialize with lifecycle transitions', () => {
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

test('Free Edition actions use the generic IDE host transport and fixed Splunk Observability Studio routes', () => {
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
		'/api/splunk/logs',
	]) {
		assert.equal(isAllowedObserverHostHTTPPath('GET', path), true, path);
	}
	assert.equal(isAllowedObserverHostHTTPPath('POST', '/api/validation/run'), true);
	assert.equal(isAllowedObserverHostHTTPPath('POST', '/api/splunk/logs'), true);
	assert.equal(isAllowedObserverHostHTTPPath('POST', '/api/splunk/logs/enabled'), true);
	assert.equal(isAllowedObserverHostHTTPPath('POST', '/api/splunk/logs/disconnect'), true);
	assert.equal(isAllowedObserverHostHTTPPath('GET', '/api/splunk/logs/disconnect'), false);
	assert.equal(isAllowedObserverHostHTTPPath('POST', '/api/splunk/logs/unknown'), false);
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

test('IDE telemetry maps Splunk Observability Studio HTTP URLs to WebSocket URLs', () => {
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
		assert.equal(backend.label, 'Splunk Observability Studio');
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

test('release Splunk Observability Studio builds embed the exact VSIX version', () => {
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

test('extension Splunk Observability Studio builds default to the extension manifest version', () => {
	const packageVersion = JSON.parse(
		fs.readFileSync(path.join(extensionRoot, 'package.json'), 'utf8'),
	) as { version: string };
	assert.equal(observerBuildVersion({}), packageVersion.version);
	assert.throws(
		() => observerBuildVersion({ OBSTUDIO_OBSERVER_VERSION: '1.2.3 -X unsafe=value' }),
		/Invalid Splunk Observability Studio build version/,
	);
});

test('package metadata declares an extension icon that exists', () => {
	const packageJSONPath = path.join(extensionRoot, 'package.json');
	const packageJSON = JSON.parse(fs.readFileSync(packageJSONPath, 'utf-8')) as { icon?: string };

	assert.equal(typeof packageJSON.icon, 'string');
	assert.ok(packageJSON.icon);
	assert.equal(fs.existsSync(path.join(extensionRoot, packageJSON.icon!)), true);
});

test('package metadata has no legacy product display labels', () => {
	const packageJSON = JSON.parse(
		fs.readFileSync(path.join(extensionRoot, 'package.json'), 'utf-8'),
	) as {
		contributes?: {
			commands?: Array<{ category?: string; title?: string }>;
			configuration?: {
				properties?: Record<string, { description?: string; markdownDescription?: string }>;
				title?: string;
			};
		};
		displayName?: string;
	};
	const displayCopy = [
		packageJSON.displayName,
		packageJSON.contributes?.configuration?.title,
		...Object.values(packageJSON.contributes?.configuration?.properties ?? {})
			.flatMap((property) => [property.description, property.markdownDescription]),
		...(packageJSON.contributes?.commands ?? [])
			.flatMap((command) => [command.category, command.title]),
	].filter((value): value is string => typeof value === 'string');

	assert.equal(displayCopy.some((value) => /\bObserver\b/.test(value)), false);
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

test('observer webview panel uses the full product title', () => {
	const extensionSourcePath = path.join(extensionRoot, 'src', 'extension.ts');
	const source = fs.readFileSync(extensionSourcePath, 'utf-8');

	assert.match(
		source,
		/const observerPanelTitle = 'Splunk Observability Studio – Telemetry Explorer';/,
	);
	assert.match(source, /createWebviewPanel\(\s*observerPanelViewType,\s*observerPanelTitle,/s);
	assert.match(source, /panel\.title = observerPanelTitle;/);
});

test('managed observer startup restores cloud export without opening the Cloud tab', () => {
	const extensionSourcePath = path.join(extensionRoot, 'src', 'extension.ts');
	const source = fs.readFileSync(extensionSourcePath, 'utf-8');

	assert.match(
		source,
		/const startupCompleted = await observerCloudLifecycleOperations\.run\(async \(\) => \{[\s\S]*?completeObserverStart\(observerLifecycleState,\s*runId,\s*observerPort\)[\s\S]*?await restoreManagedObserverCloudConnection\(context\);[\s\S]*?return true;[\s\S]*?if \(!startupCompleted\)[\s\S]*?syncObserverUi\(\);/,
	);
});

test('a hot-installed CIMD manifest cannot make disabled Cloud initialization fail', () => {
	const extensionSourcePath = path.join(extensionRoot, 'src', 'extension.ts');
	const source = fs.readFileSync(extensionSourcePath, 'utf-8');
	const configurationStart = source.indexOf('function getSISCIMDOAuthConfiguration(');
	const configurationEnd = source.indexOf('\nasync function loadCurrentSISCIMDOAuthSession(', configurationStart);
	const initializeStart = source.indexOf("\t\tcase 'initialize': {");
	const initializeEnd = source.indexOf("\n\t\tcase 'open-free-edition':", initializeStart);
	assert.notEqual(configurationStart, -1);
	assert.notEqual(configurationEnd, -1);
	assert.notEqual(initializeStart, -1);
	assert.notEqual(initializeEnd, -1);

	const configuration = source.slice(configurationStart, configurationEnd);
	const initialize = source.slice(initializeStart, initializeEnd);
	assert.match(
		configuration,
		/resolveSISCIMDOAuthScope\(configuration\.get<string>\(sisCimdOAuthScopeSetting\)\)/,
		'the runtime must own a fallback while VS Code still exposes the pre-upgrade manifest',
	);
	assert.match(
		configuration,
		/if \(scope === ''\) \{[\s\S]*?Set observability-studio\.sisCimdOAuthScope to at least one SIS-supported scope\./,
		'an explicitly blank scope must remain invalid after applying the missing-value fallback',
	);
	assert.match(
		initialize,
		/return initializeCloudBridgeState\(\{[\s\S]*?readCimdSession: \(\) => currentSISCIMDSessionStatus\(context\)[\s\S]*?registrationAndAuthProtocol: getRegistrationAndAuthProtocol\(\),/,
		'disabled optional CIMD state must not be read during core Cloud initialization',
	);
});

test('disabled CIMD initialization never reads optional session configuration', async () => {
	const calls: string[] = [];
	const status = { connected: false };
	const result = await initializeCloudBridgeState({
		registrationAndAuthProtocol: 'NONE',
		readCimdSession: async () => {
			calls.push('cimd');
			throw new Error('newly contributed setting is not registered yet');
		},
		readStatus: async () => {
			calls.push('read');
			return status;
		},
		refreshStatus: async () => {
			calls.push('refresh');
			return status;
		},
	});

	assert.deepEqual(calls, ['refresh']);
	assert.deepEqual(result, { registrationAndAuthProtocol: 'NONE', status });
});

test('disabled CIMD initialization falls back to stored status without reading a session', async () => {
	const calls: string[] = [];
	const status = { connected: false };
	const result = await initializeCloudBridgeState({
		registrationAndAuthProtocol: 'NONE',
		readCimdSession: async () => {
			calls.push('cimd');
			throw new Error('must not be read');
		},
		readStatus: async () => {
			calls.push('read');
			return status;
		},
		refreshStatus: async () => {
			calls.push('refresh');
			throw new Error('refresh failed');
		},
	});

	assert.deepEqual(calls, ['refresh', 'read']);
	assert.deepEqual(result, {
		registrationAndAuthProtocol: 'NONE',
		status,
		warning: 'refresh failed',
	});
});

test('disabled CIMD initialization propagates fallback status errors', async () => {
	const fallbackError = new Error('stored status failed');
	let cimdReads = 0;
	await assert.rejects(
		initializeCloudBridgeState({
			registrationAndAuthProtocol: 'NONE',
			readCimdSession: async () => {
				cimdReads += 1;
				throw new Error('must not be read');
			},
			readStatus: async () => { throw fallbackError; },
			refreshStatus: async () => { throw new Error('refresh failed'); },
		}),
		(error) => error === fallbackError,
	);
	assert.equal(cimdReads, 0);
});

test('enabled CIMD initialization reads Cloud and session state concurrently', async () => {
	const calls: string[] = [];
	let resolveRefresh!: (value: unknown) => void;
	let resolveSession!: (value: { subject: string }) => void;
	const refresh = new Promise<unknown>((resolve) => { resolveRefresh = resolve; });
	const session = new Promise<{ subject: string }>((resolve) => { resolveSession = resolve; });
	const initialization = initializeCloudBridgeState({
		registrationAndAuthProtocol: 'CIMD',
		readCimdSession: () => {
			calls.push('cimd');
			return session;
		},
		readStatus: async () => {
			calls.push('read');
			return { connected: false };
		},
		refreshStatus: () => {
			calls.push('refresh');
			return refresh;
		},
	});

	assert.deepEqual(calls, ['refresh', 'cimd']);
	resolveSession({ subject: 'user-123' });
	resolveRefresh({ connected: true });
	assert.deepEqual(await initialization, {
		registrationAndAuthProtocol: 'CIMD',
		cimdSession: { subject: 'user-123' },
		status: { connected: true },
	});
});

test('enabled CIMD initialization retries only a failed session load', async () => {
	const status = { connected: false };
	let fallbackReads = 0;
	let sessionReads = 0;
	const result = await initializeCloudBridgeState({
		registrationAndAuthProtocol: 'CIMD',
		readCimdSession: async () => {
			sessionReads += 1;
			if (sessionReads === 1) {
				throw new Error('transient CIMD read failure');
			}
			return { subject: 'user-123' };
		},
		readStatus: async () => {
			fallbackReads += 1;
			return status;
		},
		refreshStatus: async () => status,
	});

	assert.equal(fallbackReads, 0);
	assert.equal(sessionReads, 2);
	assert.deepEqual(result, {
		registrationAndAuthProtocol: 'CIMD',
		cimdSession: { subject: 'user-123' },
		status,
		warning: 'transient CIMD read failure',
	});
});

test('enabled CIMD initialization preserves a session when Cloud refresh falls back', async () => {
	let sessionReads = 0;
	const result = await initializeCloudBridgeState({
		registrationAndAuthProtocol: 'CIMD',
		readCimdSession: async () => {
			sessionReads += 1;
			return { subject: 'user-123' };
		},
		readStatus: async () => ({ connected: false }),
		refreshStatus: async () => { throw new Error('refresh failed'); },
	});

	assert.deepEqual(result, {
		registrationAndAuthProtocol: 'CIMD',
		cimdSession: { subject: 'user-123' },
		status: { connected: false },
		warning: 'refresh failed',
	});
	assert.equal(sessionReads, 1);
});

test('enabled CIMD initialization waits for the original refresh before retrying a failed session', async () => {
	let resolveRefresh!: (value: unknown) => void;
	const refresh = new Promise<unknown>((resolve) => { resolveRefresh = resolve; });
	let fallbackStatusReads = 0;
	let sessionReads = 0;
	let initializationSettled = false;
	const initialization = initializeCloudBridgeState({
		registrationAndAuthProtocol: 'CIMD',
		readCimdSession: async () => {
			sessionReads += 1;
			if (sessionReads === 1) {
				throw new Error('transient CIMD read failure');
			}
			return { subject: 'user-123' };
		},
		readStatus: async () => {
			fallbackStatusReads += 1;
			return { connected: false };
		},
		refreshStatus: () => refresh,
	});
	void initialization.then(
		() => { initializationSettled = true; },
		() => { initializationSettled = true; },
	);

	await new Promise<void>((resolve) => { setImmediate(resolve); });
	assert.equal(initializationSettled, false);
	assert.equal(sessionReads, 1);

	resolveRefresh({ connected: true });
	assert.deepEqual(await initialization, {
		registrationAndAuthProtocol: 'CIMD',
		cimdSession: { subject: 'user-123' },
		status: { connected: true },
		warning: 'transient CIMD read failure',
	});
	assert.equal(fallbackStatusReads, 0);
	assert.equal(sessionReads, 2);
});

test('enabled CIMD initialization still rejects when fallback session loading fails', async () => {
	let sessionReads = 0;
	await assert.rejects(
		initializeCloudBridgeState({
			registrationAndAuthProtocol: 'CIMD',
			readCimdSession: async () => {
				sessionReads += 1;
				throw new Error('CIMD failed');
			},
			readStatus: async () => ({ connected: false }),
			refreshStatus: async () => ({ connected: true }),
		}),
		/CIMD failed/,
	);
	assert.equal(sessionReads, 2);
});

test('enabled CIMD initialization lets fallback status errors win over session warnings', async () => {
	const fallbackError = new Error('stored status failed');
	await assert.rejects(
		initializeCloudBridgeState({
			registrationAndAuthProtocol: 'CIMD',
			readCimdSession: async () => { throw new Error('CIMD failed'); },
			readStatus: async () => { throw fallbackError; },
			refreshStatus: async () => { throw new Error('refresh failed'); },
		}),
		(error) => error === fallbackError,
	);
});

test('shared Splunk Observability Studio initialization reads cloud status without mutating its configuration', async () => {
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
			throw new Error('shared Splunk Observability Studio configuration must not be refreshed');
		},
	});

	assert.equal(result, status);
	assert.deepEqual(calls, ['read']);
});

test('managed Splunk Observability Studio initialization refreshes its owned cloud configuration', async () => {
	const calls: string[] = [];
	const status = cloudStatus(true, false, true);

	const result = await initializeSplunkCloudStatus({
		isManagedObserver: true,
		readStatus: async () => {
			calls.push('read');
			throw new Error('managed Splunk Observability Studio should refresh its owned configuration');
		},
		refreshManagedStatus: async () => {
			calls.push('refresh');
			return status;
		},
	});

	assert.equal(result, status);
	assert.deepEqual(calls, ['refresh']);
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


test('extension unload paths stop only the extension-owned Splunk Observability Studio process', () => {
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
		assert.throws(() => resolveBackend(extensionRoot), /Splunk Observability Studio binary not found/);
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

test('buildObserverValidatorSummaryUrl uses a normalized loopback Splunk Observability Studio URL', () => {
	assert.equal(
		buildObserverValidatorSummaryUrl('http://127.0.0.1:3000/mcp'),
		'http://127.0.0.1:3000/api/query/validation/summary',
	);
	assert.equal(
		buildObserverValidatorSummaryUrl('https://localhost/observer/'),
		'https://localhost/observer/api/query/validation/summary',
	);
});

test('buildObserverHealthUrl uses a normalized loopback Splunk Observability Studio URL', () => {
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

test('local Splunk Observability Studio operations accept only loopback hosts', () => {
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

test('shared Splunk Observability Studio URLs normalize wildcard listeners and reject every non-loopback host', () => {
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

test('agent integration prompt collapses to two honest enable/update variants', () => {
	const source = fs.readFileSync(path.join(extensionRoot, 'src', 'extension.ts'), 'utf8');
	const offerStart = source.indexOf('async function maybeOfferDetectedAgentIntegrations(');
	const offerEnd = source.indexOf('\nasync function configureAgentMCP(', offerStart);
	assert.notEqual(offerStart, -1);
	assert.notEqual(offerEnd, -1);
	const offerHandling = source.slice(offerStart, offerEnd);

	// Owned configs migrate silently (refreshOwnedAgentIntegrationConfig), so the
	// visible prompt only fires for 'missing' or UNOWNED-'different' specs. ENABLE
	// covers all-missing; everything else (incl. mixed) folds into UPDATE. The
	// install action is monolithic, so wording describes the action, not the delta.
	assert.match(
		offerHandling,
		/const states = shownSpecs\.map\(\(spec\) => getAgentIntegrationConfigState\(spec, mcpUrl\)\)/,
	);
	assert.match(offerHandling, /const allMissing = states\.every\(\(state\) => state === 'missing'\)/);
	assert.match(offerHandling, /const actionWord = allMissing \? 'Enable' : 'Update'/);

	// Exactly two variants — the retired three-branch logic and its strings are gone.
	assert.doesNotMatch(offerHandling, /const allDifferent/);
	assert.doesNotMatch(offerHandling, /moved — update/);
	assert.doesNotMatch(offerHandling, /Configure detected agent integrations/);

	// ENABLE copy (all-missing). `detail` is invisible on a non-modal toast, so
	// the informative sentence is folded into the message itself.
	assert.match(offerHandling, /Enable the \$\{labels\[0\]\} integration for Splunk Observability Studio\? Installs the obstudio MCP server and bundled skills\./);
	assert.match(offerHandling, /Enable detected agent integrations for Splunk Observability Studio\? Installs the obstudio MCP server and bundled skills for \$\{labelList\}\./);

	// UPDATE copy (anything already present, incl. mixed) — detail folded in too.
	assert.match(offerHandling, /Update the \$\{labels\[0\]\} integration for Splunk Observability Studio\? Updates its obstudio MCP server and bundled skills\./);
	assert.match(offerHandling, /Update detected agent integrations for Splunk Observability Studio\? Updates the obstudio MCP server and bundled skills for \$\{labelList\}\./);

	// Copy never narrates header preservation or carries a stale {mcpUrl} reconfigure line.
	assert.doesNotMatch(offerHandling, /Reconfigure (it|them|\$\{labels)/);
	assert.doesNotMatch(offerHandling, /header/i);

	// The confirmation button label follows the computed action word.
	assert.match(offerHandling, /showInformationMessage\([\s\S]*?actionWord,[\s\S]*?'Not Now'/);
	assert.match(offerHandling, /if \(choice === actionWord\)/);
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

test('upgrade retirement verifies Splunk Observability Studio health and the executable path before terminating a PID', () => {
	const source = fs.readFileSync(path.join(extensionRoot, 'src', 'extension.ts'), 'utf8');
	const startupStart = source.indexOf('async function startObserver(');
	const startupEnd = source.indexOf('\nasync function retireMismatchedManagedPortObserver(', startupStart);
	const startup = source.slice(startupStart, startupEnd);
	assert.match(
		startup,
		/let discoveryProbe = await probeObserver\([\s\S]*?const retirement = await retireMismatchedManagedPortObserver\([\s\S]*?discoveryProbe\.status === 'ready'/,
	);

	const retirementStart = startupEnd + 1;
	const retirementEnd = source.indexOf('\nasync function waitForProcessExit(', retirementStart);
	const retirement = source.slice(retirementStart, retirementEnd);
	assert.match(
		retirement,
		/const observerHealthVerified = observerHealth !== undefined;[\s\S]*?observerVersion === bundleVersion/,
	);
	assert.ok(
		retirement.indexOf('if (!observerHealthVerified)')
			< retirement.indexOf('const listenerInspection = await inspectListeningProcess(managedPort)'),
		'Splunk Observability Studio health must be verified before inspecting the managed-port listener',
	);
	assert.match(
		retirement,
		/const listenerInspection = await inspectListeningProcess\(managedPort\)[\s\S]*?const listener = listenerInspection\.process[\s\S]*?isObserverExecutablePath\(processExecutablePath\)/,
		'the listener PID must resolve to the Splunk Observability Studio executable',
	);
	assert.ok(
		retirement.indexOf('const preStopInspection = await inspectListeningProcess(managedPort)')
			< retirement.indexOf('const replacementProbe = await probeObserver('),
		'the listener must be fixed before refreshing the health identity',
	);
	assert.ok(
		retirement.indexOf('const replacementProbe = await probeObserver(')
			< retirement.indexOf('const confirmedInspection = await inspectListeningProcess(managedPort)'),
		'health must be refreshed before the final listener identity check',
	);
	assert.match(
		retirement,
		/const replacementProbe = await probeObserver\(\s*observerEndpointRolesForBase\(buildManagedObserverBaseUrl\(managedPort\)\),\s*500,\s*\{ requireStableOtlp: false \}/,
		'the refreshed health identity must come from the canonical managed listener, not a state-file URL',
	);
	assert.ok(
		retirement.indexOf('const confirmedInspection = await inspectListeningProcess(managedPort)')
			< retirement.indexOf('await gracefullyTerminateProcess(pid)'),
		'the port owner and executable must be reverified immediately before graceful termination',
	);
	assert.match(
		retirement,
		/confirmedListener\.pid !== pid[\s\S]*?processExecutablePathsEqual\(confirmedListener\.executablePath, processExecutablePath\)/,
	);
	assert.ok(
		retirement.indexOf('const forceStopInspection = await inspectListeningProcess(managedPort)')
			< retirement.indexOf('const currentProcessExecutablePath = await readProcessExecutablePath(pid)'),
		'the managed port must be checked before falling back to process identity',
	);
	assert.ok(
		retirement.indexOf('const currentProcessExecutablePath = await readProcessExecutablePath(pid)')
			< retirement.indexOf('await forceTerminateProcess(pid)'),
		'the original PID and executable path must be reverified before forced termination',
	);
	assert.match(
		retirement,
		/forceStopInspection\.status === 'ambiguous'[\s\S]*?forceStopInspection\.status === 'unavailable'/,
	);
	assert.match(
		retirement,
		/forceStopInspection\.status === 'unique'[\s\S]*?forceStopInspection\.process\.pid !== pid/,
	);
	assert.match(
		retirement,
		/currentProcessExecutablePath === undefined[\s\S]*?processExecutablePathsEqual\(currentProcessExecutablePath, processExecutablePath\)/,
	);
	assert.doesNotMatch(
		retirement,
		/process\.kill\(pid, 'SIGTERM'\)/,
		'the upgrade path must not treat Node SIGTERM as graceful on Windows',
	);
	assert.doesNotMatch(
		retirement,
		/observerHealth\?\.owner|observerHealth\.mode|findOtherExtension|readProcessCommand|processCommand/,
	);
});

test('upgrade retirement treats a vacated managed port as already retired', () => {
	const source = fs.readFileSync(path.join(extensionRoot, 'src', 'extension.ts'), 'utf8');
	const retirementStart = source.indexOf('async function retireMismatchedManagedPortObserver(');
	const retirementEnd = source.indexOf('\nasync function waitForProcessExit(', retirementStart);
	const retirement = source.slice(retirementStart, retirementEnd);

	for (const inspectionName of [
		'listenerInspection',
		'preStopInspection',
		'replacementProbeInspection',
		'confirmedInspection',
	]) {
		assert.match(
			retirement,
			new RegExp(
				`const ${inspectionName} = await inspectListeningProcess\\(managedPort\\);[\\s\\S]*?`
				+ `${inspectionName}\\.status === 'none'[\\s\\S]*?status: 'retired'`,
			),
			`${inspectionName} must distinguish a free port from failed or ambiguous inspection`,
		);
	}
});

test('all local Splunk Observability Studio reuse paths use the same bundled-version compatibility rule', () => {
	const source = fs.readFileSync(path.join(extensionRoot, 'src', 'extension.ts'), 'utf8');
	const startupStart = source.indexOf('async function startObserver(');
	const startupEnd = source.indexOf('\nasync function retireMismatchedManagedPortObserver(', startupStart);
	const startup = source.slice(startupStart, startupEnd);
	assert.match(startup, /const bundleVersion = getBundleVersion\(context\)/);
	assert.match(startup, /configuredProbe\.health\.version !== bundleVersion/);
	assert.match(
		startup,
		/managedProbe\.status === 'ready'[\s\S]*?retireMismatchedManagedPortObserver\([\s\S]*?managedProbe\.health/,
	);
	assert.match(
		startup,
		/existingObserver\.health\.version === bundleVersion[\s\S]*?retireMismatchedManagedPortObserver\(/,
	);
	assert.match(startup, /startedProbe\.health\.version !== bundleVersion/);
	assert.doesNotMatch(startup, /0\.0\.18|0\.0\.20/);
});

test('temporary port reservations destroy reconnecting exporter sockets before closing', async () => {
	const allocator = net.createServer();
	await new Promise<void>((resolve, reject) => {
		allocator.once('error', reject);
		allocator.listen(0, '127.0.0.1', () => resolve());
	});
	const address = allocator.address();
	assert.ok(address !== null && typeof address !== 'string');
	const port = address.port;
	await new Promise<void>((resolve) => allocator.close(() => resolve()));

	const reservations = new LoopbackPortReservations();
	let exporter: net.Socket | undefined;
	try {
		assert.equal(await reservations.reserve(port, performance.now() + 1_000), true);
		const connectedExporter = net.createConnection({ host: '127.0.0.1', port });
		exporter = connectedExporter;
		const exporterClosed = new Promise<void>((resolve) => connectedExporter.once('close', () => resolve()));
		await new Promise<void>((resolve, reject) => {
			connectedExporter.once('connect', () => resolve());
			connectedExporter.once('error', reject);
		});
		let closeTimeout: NodeJS.Timeout | undefined;
		try {
			await Promise.race([
				reservations.close(),
				new Promise<never>((_resolve, reject) => {
					closeTimeout = setTimeout(
						() => reject(new Error('port reservation close exceeded its bound')),
						1_000,
					);
				}),
			]);
		} finally {
			if (closeTimeout !== undefined) {
				clearTimeout(closeTimeout);
			}
		}
		await exporterClosed;
		assert.equal(
			await loopbackPortsAreSimultaneouslyAvailable([port], performance.now() + 1_000),
			true,
			'the temporary listener must release its port after rejecting the exporter connection',
		);
	} finally {
		exporter?.destroy();
		await reservations.close();
	}
});

test('reload startup gives unavailable Observer listeners one bounded port handoff', () => {
	const source = fs.readFileSync(path.join(extensionRoot, 'src', 'extension.ts'), 'utf8');
	const startupStart = source.indexOf('async function startObserver(');
	const startupEnd = source.indexOf('\nasync function retireMismatchedManagedPortObserver(', startupStart);
	const startup = source.slice(startupStart, startupEnd);
	const deadlineStart = startup.indexOf('const observerHandoffDeadline = performance.now()');
	const waitStart = startup.indexOf('await waitForObserverPortHandoff(');
	const portChecksStart = startup.indexOf('const backend = resolveBackend(');
	assert.notEqual(deadlineStart, -1);
	assert.notEqual(waitStart, -1);
	assert.notEqual(portChecksStart, -1);
	assert.ok(deadlineStart < waitStart);
	assert.ok(waitStart < portChecksStart);
	assert.match(
		startup,
		/discoveryStateAgeMs[\s\S]*?performance\.now\(\) \+ sharedObserverStartupWindowMs - discoveryStateAgeMs/,
		'the fresh-discovery deadline must be monotonic after deriving its remaining wall-clock age',
	);
	assert.match(
		startup,
		/managedHandoffDiscovery[\s\S]*?loopbackPortsAreSimultaneouslyAvailable\(\s*\[observerOtlpGrpcPort, observerOtlpHttpPort, managedPort\],[\s\S]*?all prior Observer ports were released/,
		'a matching discovery must stop retrying as soon as the outgoing process releases every required port',
	);
	assert.match(
		startup,
		/observerProbeMayRecover\(existingObserver\)[\s\S]*?waitForObserverPortHandoff\(\s*\[observerOtlpGrpcPort, observerOtlpHttpPort, managedPort\][\s\S]*?existingObserver = await probeObserver/,
		'a recoverable managed Observer probe must bridge the prior-host handoff and then re-probe',
	);
	assert.match(startup, /while \(performance\.now\(\) < deadline\)/);
	assert.doesNotMatch(startup, /bridgeStartupPortConflict|reuseCompetingExtensionObserver/);
});

test('provisionally reused extension Observers recover if the outgoing host stops them', () => {
	const source = fs.readFileSync(path.join(extensionRoot, 'src', 'extension.ts'), 'utf8');
	const monitorStart = source.indexOf('function monitorExtensionObserverHandoff(');
	const monitorEnd = source.indexOf('\nasync function retireMismatchedManagedPortObserver(', monitorStart);
	assert.notEqual(monitorStart, -1);
	assert.notEqual(monitorEnd, -1);
	const monitor = source.slice(monitorStart, monitorEnd);
	assert.match(monitor, /health\.owner !== extensionManagedObserverOwner/);
	assert.match(monitor, /health\.mode !== extensionManagedObserverMode/);
	assert.match(monitor, /health\.version !== bundleVersion/);
	assert.match(monitor, /observerDeactivationStarted/);
	assert.match(monitor, /observerExplicitStopIntentCount > 0/);
	assert.match(monitor, /observerCloudLifecycleOperations\.run/);
	assert.match(
		monitor,
		/loopbackPortsAreSimultaneouslyAvailable\([\s\S]*?performance\.now\(\) \+ observerExtensionHandoffPortCheckMs[\s\S]*?observerCloudLifecycleOperations\.run[\s\S]*?performance\.now\(\) \+ observerExtensionHandoffPortCheckMs[\s\S]*?stopObserverRun\(observerLifecycleState\)/,
		'a failed health probe must not invalidate provisional reuse until every required port is free',
	);
	assert.match(
		monitor,
		/stopObserverRun\(observerLifecycleState\);[\s\S]*?await ensureObserverRunning\(context, recoveryGeneration\)/,
		'a confirmed handoff exit must invalidate the provisional reuse before starting a replacement',
	);
	assert.equal(
		(source.match(/monitorExtensionObserverHandoff\(/g) ?? []).length,
			3,
			'only automatic local reuse paths may arm handoff monitoring',
		);
	assert.match(
		source,
		/existingObserver\.health\.version === bundleVersion[\s\S]*?monitorExtensionObserverHandoff/,
		'a current-version service recovered after an earlier transient probe must be monitored during handoff',
	);
});

test('health probe treats shutdown transport and truncated response errors as unavailable', () => {
	const source = fs.readFileSync(path.join(extensionRoot, 'src', 'extension.ts'), 'utf8');
	const probeStart = source.indexOf('async function probeObserver(');
	const probeEnd = source.indexOf('\nfunction validateObserverHealth(', probeStart);
	const probe = source.slice(probeStart, probeEnd);
	for (const errorCode of ['ECONNABORTED', 'ECONNRESET', 'EPIPE']) {
		assert.match(probe, new RegExp(`error\\.code === '${errorCode}'`));
	}
	assert.match(
		probe,
		/collectObserverHostHTTPResponse\([\s\S]*?\(error: Error\) => finish\(\(\) => resolve\(\{ status: 'unavailable', error \}\)\)/,
		'the health probe must use the response collector whose executable tests cover aborted, closed, and errored streams',
	);
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
		'Open Splunk Observability Studio must not resolve before its panel startup attempt finishes',
	);
	const stopStart = source.indexOf("registerCommand('observability-studio.stopObserver', async () => {");
	const stopBody = source.slice(stopStart, source.indexOf('\n\t});', stopStart));
	assert.match(
		stopBody,
		/observerExplicitStopIntentCount \+= 1;[\s\S]*?await settleObserverConfigurationRestart\(\);[\s\S]*?await stopObserver\(\);[\s\S]*?observerExplicitStopIntentCount -= 1;/,
		'Stop intent must be visible before awaiting configuration work and remain visible through shutdown',
	);
	const restartStart = source.indexOf("registerCommand('observability-studio.restartObserver', async () => {");
	const restartBody = source.slice(restartStart, source.indexOf('\n\t});', restartStart));
	assert.match(
		restartBody,
		/restartGeneration = observerLifecycleState\.currentRunId;[\s\S]*?observerExplicitStopIntentCount -= 1;[\s\S]*?ensureObserverRunning\(context, restartGeneration\)/,
		'a later explicit Stop must prevent Restart from starting again after joining the same shutdown',
	);
	const stopFunctionStart = source.indexOf('async function stopObserver(): Promise<void>');
	const stopFunctionEnd = source.indexOf('\nasync function shutdownObserverForExtensionUnload(', stopFunctionStart);
	const stopFunction = source.slice(stopFunctionStart, stopFunctionEnd);
	assert.match(
		stopFunction,
		/observerStartupPromise === undefined && observerBaseUrl === undefined[\s\S]*?stopObserverRun\(observerLifecycleState\)/,
		'an idle explicit Stop must still invalidate any stale monitor recovery generation',
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

test('stageSkills bundles the embedded runtime tree with sibling resources and removes stale skills', () => {
	const repoRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'obstudio-build-skills-'));
	try {
		const paths = getBuildPaths(path.join(repoRoot, 'extension'));
		const stagedRoot = path.join(paths.observerRoot, 'cmd', 'obstudio', '_skills');
		const resources = [
			'otel-audit/SKILL.md',
			'otel-audit/scripts/scan.py',
			'otel-instrument/references/languages/go.md',
			'references/report-flow-contract.md',
		];
		const calls: string[][] = [];
		fs.mkdirSync(paths.skillsOutDir, { recursive: true });
		fs.writeFileSync(path.join(paths.skillsOutDir, 'retired.md'), 'stale');
		stageSkills(paths, (file, args, options) => {
			calls.push([file, ...args]);
			assert.equal(options.cwd, paths.observerRoot);
			for (const resource of resources) {
				const target = path.join(stagedRoot, resource);
				fs.mkdirSync(path.dirname(target), { recursive: true });
				fs.writeFileSync(target, resource);
			}
		});
		assert.deepEqual(calls, [['go', 'run', './cmd/stage-skills']]);
		for (const resource of resources) {
			assert.equal(fs.readFileSync(path.join(paths.skillsOutDir, resource), 'utf8'), resource);
		}
		assert.equal(fs.existsSync(path.join(paths.skillsOutDir, 'retired.md')), false);
		assert.throws(() => stageSkills(paths, () => {
			throw new Error('skill staging failed');
		}), /skill staging failed/);
	} finally {
		fs.rmSync(repoRoot, { recursive: true, force: true });
	}
});

test('each synchronized Copilot skill retains executable report helpers without sibling directories', async () => {
	const root = fs.mkdtempSync(path.join(os.tmpdir(), 'obstudio-synced-skills-'));
	try {
		const paths = getBuildPaths(path.join(root, 'extension'));
		fs.cpSync(path.resolve(extensionRoot, '..', 'skills'), paths.skillsOutDir, {
			recursive: true,
			filter: (source) => !['tests', 'evals', '__pycache__'].includes(path.basename(source)),
		});
		bundleCopilotSkills(paths);
		const python = process.env.OBSTUDIO_TEST_PYTHON || 'python3';
		const reportRoot = path.join(root, '.observe');
		fs.mkdirSync(reportRoot);
		const audit = path.join(reportRoot, 'otel-audit.json');
		execFileSync(python, ['-I', '-c', [
			'import json, runpy, sys',
			'from pathlib import Path',
			'fixtures = runpy.run_path(sys.argv[1])',
			'Path(sys.argv[2]).write_text(json.dumps(fixtures["sample_report"]()))',
		].join('\n'), path.resolve(extensionRoot, '..', 'skills/references/tests/test_observe_report.py'), audit]);
		for (const name of ['otel-audit', 'otel-instrument', 'otel-verify']) {
			const isolated = path.join(root, 'synced', name);
			fs.cpSync(path.join(root, 'extension', 'dist', 'copilot-skills', name), isolated, { recursive: true });
			const canonical = path.join(isolated, 'bundle', name);
			assert.equal(
				fs.readFileSync(path.join(canonical, 'SKILL.md'), 'utf8'),
				fs.readFileSync(path.resolve(extensionRoot, '..', 'skills', name, 'SKILL.md'), 'utf8'),
			);
			for (const command of ['select', 'validate-flow', 'render-instrumentation-html']) {
				const output = execFileSync(python, [
					'-I', path.join(canonical, 'scripts', 'observe_report.py'), command, '--help',
				], { cwd: root, encoding: 'utf8' });
				const plainOutput = output.replace(/\x1B\[[0-?]*[ -/]*[@-~]/g, '');
				assert.match(plainOutput, /usage: observe_report\.py/);
			}
			const launcher = path.join(canonical, 'scripts', 'observe_report.py');
			const selection = path.join(isolated, 'otel-selection.json');
			execFileSync(python, ['-I', launcher, 'select', audit, '--ids', 'OTEL-001', '-o', selection], {
				cwd: root, encoding: 'utf8',
			});
			const flow = execFileSync(python, [
				'-I', launcher, 'validate-flow', audit, '--selection-json', selection,
			], { cwd: root, encoding: 'utf8' });
			assert.match(flow, /PASS: audit -> selection/);
			assert.deepEqual(JSON.parse(fs.readFileSync(selection, 'utf8')).approved_ids, ['OTEL-001']);
			if (name === 'otel-instrument') {
				const instrumentation = path.join(reportRoot, 'otel-instrumentation.json');
				const verification = path.join(reportRoot, 'otel-verify.json');
				execFileSync(python, ['-I', '-c', [
					'import json, runpy, sys',
					'from pathlib import Path',
					'f = runpy.run_path(sys.argv[1])',
					'm = f["MODULE"]',
					'audit = m.normalize_audit_report(json.loads(Path(sys.argv[2]).read_text()))',
					'selection = json.loads(Path(sys.argv[3]).read_text())',
					'digest = m.audit_digest(audit)',
					'instrument = m.normalize_instrumentation(f["sample_instrumentation"](audit, digest, selection), audit, selection)',
					'Path(sys.argv[4]).write_text(json.dumps(instrument))',
					'Path(sys.argv[5]).write_text(json.dumps(f["sample_verify"](audit, digest, m.instrumentation_digest(instrument))))',
				].join('\n'), path.resolve(extensionRoot, '..', 'skills/references/tests/test_observe_report.py'),
				audit, selection, instrumentation, verification]);
				const flags = ['--selection-json', selection, '--instrumentation-json', instrumentation, '--verify-json', verification];
				assert.match(execFileSync(python, ['-I', launcher, 'validate-flow', audit, ...flags], {
					cwd: root, encoding: 'utf8',
				}), /PASS: audit -> selection -> instrumentation -> verify/);
				const html = path.join(reportRoot, 'otel-instrumentation.html');
				const rendered = JSON.parse(execFileSync(python, [
					'-I', launcher, 'render-instrumentation-html', audit, '-o', html, ...flags,
				], { cwd: root, encoding: 'utf8' })) as {
					result: string;
					server: { pid: number; url: string };
				};
				try {
					assert.equal(rendered.result, 'PASS');
					const response = await fetch(rendered.server.url);
					assert.equal(response.status, 200);
					assert.equal(await response.text(), fs.readFileSync(html, 'utf8'));
				} finally {
					process.kill(rendered.server.pid, 'SIGTERM');
				}
			}
			assert.ok(fs.existsSync(path.join(isolated, 'bundle', 'otel-verify', 'scripts', 'validate_reader_report.py')));
		}
		assert.equal(fs.existsSync(path.join(root, 'synced', 'references')), false);
		fs.writeFileSync(path.join(root, 'extension', 'dist', 'copilot-skills', 'stale.txt'), 'stale');
		bundleCopilotSkills(paths);
		assert.equal(fs.existsSync(path.join(root, 'extension', 'dist', 'copilot-skills', 'stale.txt')), false);
		fs.writeFileSync(path.join(paths.skillsOutDir, 'otel-audit', 'SKILL.md'), 'missing frontmatter');
		assert.throws(() => bundleCopilotSkills(paths), /Missing skill frontmatter/);
	} finally {
		fs.rmSync(root, { recursive: true, force: true });
	}
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
	assert.equal(isSkillDocsId('not-a-skill'), false);
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
	for (const bogus of ['not-a-skill', 'https://evil.example.com', '../../etc/passwd', '', undefined, null, 7]) {
		assert.equal(skillDocsUrl(bogus), undefined, `${String(bogus)} should not resolve`);
	}
});

test('retired splunk-sync skill is not exposed in the docs registry', () => {
	assert.equal(isSkillDocsId('splunk-sync'), false);
	assert.equal(skillDocsUrl('splunk-sync'), undefined);
});

test('retired splunk-dashboard-sync skill is not exposed in the docs registry', () => {
	assert.equal(isSkillDocsId('splunk-dashboard-sync'), false);
	assert.equal(skillDocsUrl('splunk-dashboard-sync'), undefined);
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

test('IDE connection edits accept explicit reuse flags without accepting destination URLs from the webview', () => {
 const request = (action: string, payload?: Record<string, unknown>) => ({ type: 'obstudio.host.request', requestId: 'edit-123', request: { kind: 'cloud', action, payload } });
 const payload = { realm: 'us1', accessToken: '', expectedVersion: 'V'.repeat(43), reuseSavedToken: true, preserveEnabled: true };
 assert.equal(isObserverHostRequestEnvelope(request('connect', payload)), true);
 for (const key of ['reuseSavedToken', 'preserveEnabled']) {
  assert.equal(isObserverHostRequestEnvelope(request('connect', { ...payload, [key]: 'true' })), false);
 }
 for (const action of ['open-hec-token-help', 'open-observability-cloud', 'open-observability-metrics', 'open-observability-traces', 'open-splunk-search'] as const) {
  assert.equal(isObserverHostRequestEnvelope(request(action)), true);
  assert.equal(isObserverHostRequestEnvelope(request(action, { destination: 'https://example.test' })), false);
  assert.equal(cloudBridgeActionRequiresLifecycleSerialization(action), false);
 }
});
