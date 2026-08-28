import * as assert from 'node:assert/strict';
import * as fs from 'node:fs';
import * as os from 'node:os';
import * as path from 'node:path';
import test from 'node:test';
import {
	buildObserverHealthUrl,
	buildObserverValidatorSummaryUrl,
	isLocalObserverControlHost,
	normalizeObserverBaseUrl,
	observerPortFromUrl,
	readSharedObserverControlToken,
	readSharedObserverDiscovery,
	resolveSharedObserverControlToken,
	resolveBackend,
} from '../backend';
import {
	auditReportPath,
	auditReportUrl,
	isCloudBridgeReady,
	isCloudBridgeRequest,
	isSkillDocsId,
	ObserverCloudResponseError,
	parseObserverCloudResponseBody,
	skillDocsIds,
	skillDocsUrl,
	parseStoredSplunkCloudConnection,
	restoreSplunkCloudConnectionFromStorage,
	restoreSplunkCloudConnectionWithLegacyFallback,
	shouldRestoreObserverAfterCloudMutationFailure,
	validateCloudClipboardText,
} from '../cloud-bridge';

const extensionRoot = path.resolve(__dirname, '..', '..');
const { buildClientAssets, getBuildPaths, resetObserverOutputDirs } = require('../../build-observer.js') as {
	buildClientAssets: (
		paths: ReturnType<typeof getBuildPaths>,
		run?: (file: string, args: string[], options: { cwd: string; stdio: string }) => unknown,
	) => void;
	getBuildPaths: (extensionRoot?: string, env?: NodeJS.ProcessEnv) => {
		observerRoot: string;
		observerOutDir: string;
		observerOutBinary: string;
		target: {
			binaryName: string;
			goarch: string;
			goos: string;
		};
	};
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

test('cloud bridge accepts only bounded known requests', () => {
	assert.equal(isCloudBridgeRequest({
		action: 'connect',
		bridgeToken: 'bridge-token-1234567890123456',
		payload: {
			accessToken: 'token_1234567890123456',
			realm: 'us0',
		},
		requestId: 'request-123',
		type: 'obstudio.cloud.request',
	}), true);
	assert.equal(isCloudBridgeRequest({
		action: 'read-clipboard',
		bridgeToken: 'bridge-token-1234567890123456',
		requestId: 'request-123',
		type: 'obstudio.cloud.request',
	}), true);
	assert.equal(isCloudBridgeRequest({
		action: 'connect',
		bridgeToken: 'bridge-token-1234567890123456',
		payload: { accessToken: 'é'.repeat(2048), realm: 'us0' },
		requestId: 'request-123',
		type: 'obstudio.cloud.request',
	}), true);
	assert.equal(isCloudBridgeRequest({
		action: 'connect',
		bridgeToken: 'bridge-token-1234567890123456',
		payload: { accessToken: 'é'.repeat(2049), realm: 'us0' },
		requestId: 'request-123',
		type: 'obstudio.cloud.request',
	}), false);
	assert.equal(isCloudBridgeRequest({
		action: 'read-clipboard',
		bridgeToken: 'bridge-token-1234567890123456',
		payload: { accessToken: 'clipboard reads take no payload' },
		requestId: 'request-123',
		type: 'obstudio.cloud.request',
	}), false);
	assert.equal(isCloudBridgeRequest({
		action: 'open-free-edition',
		bridgeToken: 'bridge-token-1234567890123456',
		requestId: 'request-123',
		type: 'obstudio.cloud.request',
	}), true);
	assert.equal(isCloudBridgeRequest({
		action: 'open-ingest-token-help',
		bridgeToken: 'bridge-token-1234567890123456',
		requestId: 'request-123',
		type: 'obstudio.cloud.request',
	}), true);
	assert.equal(isCloudBridgeRequest({
		action: 'unsupported',
		bridgeToken: 'bridge-token-1234567890123456',
		requestId: 'request-123',
		type: 'obstudio.cloud.request',
	}), false);
	assert.equal(isCloudBridgeRequest({
		action: 'open-skill-docs',
		bridgeToken: 'bridge-token-1234567890123456',
		payload: { skill: 'otel-instrument' },
		requestId: 'request-123',
		type: 'obstudio.cloud.request',
	}), true);
	// Only known skill ids pass; the webview can never name a URL.
	assert.equal(isCloudBridgeRequest({
		action: 'open-skill-docs',
		bridgeToken: 'bridge-token-1234567890123456',
		payload: { skill: 'https://evil.example.com' },
		requestId: 'request-123',
		type: 'obstudio.cloud.request',
	}), false);
	assert.equal(isCloudBridgeRequest({
		action: 'open-skill-docs',
		bridgeToken: 'bridge-token-1234567890123456',
		payload: { skill: '../../etc/passwd' },
		requestId: 'request-123',
		type: 'obstudio.cloud.request',
	}), false);
	// Every advertised skill id must pass validation, including the Splunk
	// Observability Cloud skills surfaced on the Overview tab.
	for (const skill of skillDocsIds) {
		assert.equal(isCloudBridgeRequest({
			action: 'open-skill-docs',
			bridgeToken: 'bridge-token-1234567890123456',
			payload: { skill },
			requestId: 'request-123',
			type: 'obstudio.cloud.request',
		}), true, `skill id ${skill} should validate`);
	}
	assert.equal(isCloudBridgeRequest({
		action: 'connect',
		bridgeToken: 'short',
		requestId: 'request-123',
		type: 'obstudio.cloud.request',
	}), false);
	assert.equal(isCloudBridgeRequest({
		action: 'connect',
		bridgeToken: 'bridge-token-1234567890123456',
		payload: { unexpectedField: 'must-not-pass' },
		requestId: 'request-123',
		type: 'obstudio.cloud.request',
	}), false);
});

test('cloud clipboard text fails clearly instead of being silently truncated', () => {
	assert.equal(validateCloudClipboardText('x'.repeat(4096)), 'x'.repeat(4096));
	assert.equal(validateCloudClipboardText('é'.repeat(2048)), 'é'.repeat(2048));
	assert.throws(
		() => validateCloudClipboardText('é'.repeat(2049)),
		/4,096 UTF-8-byte cloud field limit/,
	);
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

test('cloud restore falls back to the legacy configure route only when restore is unavailable', async () => {
	for (const statusCode of [404, 405]) {
		const calls: string[] = [];
		const fallbackResult = await restoreSplunkCloudConnectionWithLegacyFallback(
			async () => {
				calls.push('restore');
				throw new ObserverCloudResponseError(statusCode, 'route unavailable');
			},
			async () => {
				calls.push('legacy');
				return { connected: true };
			},
		);
		assert.deepEqual(fallbackResult, { connected: true });
		assert.deepEqual(calls, ['restore', 'legacy']);
	}

	let legacyCalled = false;
	await assert.rejects(
		() => restoreSplunkCloudConnectionWithLegacyFallback(
			async () => { throw new ObserverCloudResponseError(401, 'unauthorized'); },
			async () => {
				legacyCalled = true;
				return {};
			},
		),
		/unauthorized/,
	);
	assert.equal(legacyCalled, false);
});

test('cloud bridge ready messages require the bound token shape', () => {
	assert.equal(isCloudBridgeReady({
		bridgeToken: 'bridge-token-1234567890123456',
		type: 'obstudio.cloud.ready',
	}), true);
	assert.equal(isCloudBridgeReady({
		type: 'obstudio.cloud.ready',
	}), false);
	assert.equal(isCloudBridgeReady({
		bridgeToken: 'short',
		type: 'obstudio.cloud.ready',
	}), false);
	assert.equal(isCloudBridgeReady({
		bridgeToken: 'bridge-token-1234567890123456',
		type: 'obstudio.cloud.request',
	}), false);
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
		/completeObserverStart\(observerLifecycleState,\s*runId,\s*observerPort\)[\s\S]*?await restoreManagedObserverCloudConnection\(context\);[\s\S]*?syncObserverUi\(\);/,
	);
});

test('cloud export preference survives managed observer restarts', async () => {
	const stored = {
		accessToken: 'token_1234567890123456',
		realm: 'us0',
	};
	const refreshed = cloudStatus(false, false, false);
	const configured = cloudStatus(true, false, true);
	const enabled = cloudStatus(true, true, true);
	const calls: Array<[string, unknown?]> = [];

	const result = await restoreSplunkCloudConnectionFromStorage({
		configure: async (connection) => {
			calls.push(['configure', connection]);
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
		setEnabled: async (value) => {
			calls.push(['setEnabled', value]);
			return enabled;
		},
	});

	assert.equal(result, enabled);
	assert.deepEqual(calls, [
		['refresh'],
		['readConnection'],
		['configure', stored],
		['readExportEnabled'],
		['setEnabled', true],
	]);
});

test('cloud export restore skips secure storage when observer is already configured', async () => {
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
		setEnabled: async () => {
			throw new Error('setEnabled should not be called');
		},
	});

	assert.equal(result, refreshed);
	assert.equal(readConnection, false);
});

test('cloud export bridge persists preference keys and refresh fallback paths', () => {
	const extensionSourcePath = path.join(extensionRoot, 'src', 'extension.ts');
	const source = fs.readFileSync(extensionSourcePath, 'utf-8');

	assert.match(source, /const splunkCloudExportEnabledStateKey = 'splunkCloudExportEnabled\.v1';/);
	assert.match(
		source,
		/case 'set-enabled':[\s\S]*?context\.globalState\.update\(\s*splunkCloudExportEnabledStateKey,\s*request\.payload\.enabled[\s\S]*?postObserverCloudJSON\('\/api\/splunk\/export\/enabled'/,
	);
	const setEnabledStart = source.indexOf("case 'set-enabled':");
	const setEnabledEnd = source.indexOf("case 'forget':", setEnabledStart);
	assert.notEqual(setEnabledStart, -1);
	assert.notEqual(setEnabledEnd, -1);
	const setEnabledSource = source.slice(setEnabledStart, setEnabledEnd);
	assert.match(
		setEnabledSource,
		/restoreObserverCloudConnection\(\s*storedValue,\s*storedExportEnabled,\s*\{\s*clearWhenMissing:\s*false\s*\},?\s*\)/,
	);
	assert.match(
		source,
		/async function refreshSplunkCloudConnection[\s\S]*?configure: \(connection\) => restoreSplunkCloudConnectionWithLegacyFallback\([\s\S]*?postObserverCloudJSON\('\/api\/splunk\/export\/restore', connection\)[\s\S]*?postObserverCloudJSON\('\/api\/splunk\/export', connection\)[\s\S]*?context\.globalState\.get<boolean>\(splunkCloudExportEnabledStateKey\)[\s\S]*?refresh: \(\) => refreshObserverCloudStatus\(\)[\s\S]*?postObserverCloudJSON\('\/api\/splunk\/export\/enabled', \{ enabled \}\)/,
	);
	assert.match(
		source,
		/async function refreshObserverCloudStatus[\s\S]*?restoreSplunkCloudConnectionWithLegacyFallback\([\s\S]*?postObserverCloudJSON\('\/api\/splunk\/export\/refresh', \{\}\)[\s\S]*?getObserverCloudJSON\('\/api\/splunk\/export'\)/,
	);
	assert.match(
		source,
		/case 'connect':[\s\S]*?postObserverCloudJSON\('\/api\/splunk\/export', connection\)[\s\S]*?context\.secrets\.store\(splunkCloudConnectionSecretKey[\s\S]*?context\.globalState\.update\(splunkCloudExportEnabledStateKey, false\)/,
	);
	assert.match(
		source,
		/case 'read-clipboard':[\s\S]*?readApprovedCloudClipboard\(request\.bridgeToken\)/,
	);
	assert.match(
		source,
		/async function readApprovedCloudClipboard[\s\S]*?vscode\.window\.showInformationMessage\([\s\S]*?allowCloudClipboardAction[\s\S]*?validateCloudClipboardText\(await vscode\.env\.clipboard\.readText\(\)\)/,
	);
	assert.match(
		source,
		/async function forgetSplunkCloudConnection[\s\S]*?context\.globalState\.update\(splunkCloudExportEnabledStateKey, undefined\)/,
	);
});

test('authoritative cloud mutation rejections do not trigger Observer rollback writes', () => {
	const extensionSourcePath = path.join(extensionRoot, 'src', 'extension.ts');
	const source = fs.readFileSync(extensionSourcePath, 'utf-8');
	const setEnabledStart = source.indexOf("case 'set-enabled':");
	const setEnabledEnd = source.indexOf("case 'forget':", setEnabledStart);
	const forgetStart = source.indexOf('async function forgetSplunkCloudConnection');
	const forgetEnd = source.indexOf('async function restoreStoredCloudConnectionState', forgetStart);

	assert.match(
		source.slice(setEnabledStart, setEnabledEnd),
		/shouldRestoreObserverAfterCloudMutationFailure\(serverError\)/,
	);
	assert.match(
		source.slice(forgetStart, forgetEnd),
		/shouldRestoreObserverAfterCloudMutationFailure\(forgetError\)/,
	);
});

function cloudStatus(connected: boolean, enabled: boolean, configured: boolean) {
	return {
		connected,
		enabled,
		metrics: { configured, enabled },
		traces: { configured, enabled },
	};
}

test('shared observer control requests refresh rotated state tokens and retry one unauthorized response', () => {
	const extensionSourcePath = path.join(extensionRoot, 'src', 'extension.ts');
	const source = fs.readFileSync(extensionSourcePath, 'utf-8');

	assert.match(
		source,
		/function activeObserverControlToken\(\): string \{[\s\S]*?sharedObserverControlTokenForUrl\(observerBaseUrl\)[\s\S]*?observerSharedControlToken = currentToken/,
	);
	assert.match(
		source,
		/response\.statusCode === 401[\s\S]*?sharedObserverControlTokenForUrl\(observerBaseUrl\)[\s\S]*?refreshedToken !== controlToken[\s\S]*?continue;/,
	);
});

test('extension unload paths clean up observer state', () => {
	const extensionSourcePath = path.join(extensionRoot, 'src', 'extension.ts');
	const source = fs.readFileSync(extensionSourcePath, 'utf-8');

	assert.match(source, /export\s+async\s+function\s+deactivate\(\):\s*Promise<void>\s*\{/);
	assert.match(source, /await\s+shutdownObserverForExtensionUnload\('Extension deactivated'\)/);
	assert.match(source, /async\s+function\s+shutdownObserverForExtensionUnload\(reason:\s*string\):\s*Promise<void>/);
	assert.match(source, /await\s+stopObserver\(\)/);
	assert.match(source, /dispose:\s*\(\)\s*=>\s*\{[\s\S]*?disposeObserverForExtensionUnload\('Extension disposed'\)/);
	assert.match(source, /function\s+disposeObserverForExtensionUnload\(reason:\s*string\):\s*void/);
	assert.match(source, /stopObserverRun\(observerLifecycleState\)/);
	assert.match(source, /terminateObserverProcess\(proc,\s*'SIGTERM'\)/);
	assert.doesNotMatch(source, /export\s+function\s+deactivate\(\)\s*\{[\s\S]*?terminateObserverProcess\(observerProcess,\s*'SIGTERM'\)/);
});

test('resolveBackend throws when the observer binary is missing', () => {
	withTempExtensionRoot((extensionRoot) => {
		assert.throws(() => resolveBackend(extensionRoot), /observer binary not found/);
	});
});

test('normalizeObserverBaseUrl accepts base URLs and /mcp URLs', () => {
	assert.equal(normalizeObserverBaseUrl('http://127.0.0.1:3000'), 'http://127.0.0.1:3000');
	assert.equal(normalizeObserverBaseUrl('http://127.0.0.1:3000/'), 'http://127.0.0.1:3000');
	assert.equal(normalizeObserverBaseUrl('http://127.0.0.1:3000/mcp'), 'http://127.0.0.1:3000');
	assert.equal(normalizeObserverBaseUrl('https://example.com/observer/mcp'), 'https://example.com/observer');
});

test('buildObserverValidatorSummaryUrl uses normalized observer base URL', () => {
	assert.equal(
		buildObserverValidatorSummaryUrl('http://127.0.0.1:3000/mcp'),
		'http://127.0.0.1:3000/api/query/validation/summary',
	);
	assert.equal(
		buildObserverValidatorSummaryUrl('https://example.com/observer/'),
		'https://example.com/observer/api/query/validation/summary',
	);
});

test('buildObserverHealthUrl uses normalized observer base URL', () => {
	assert.equal(
		buildObserverHealthUrl('http://127.0.0.1:3000/mcp'),
		'http://127.0.0.1:3000/api/health',
	);
	assert.equal(
		buildObserverHealthUrl('https://example.com/observer/'),
		'https://example.com/observer/api/health',
	);
});

test('observerPortFromUrl returns explicit and default ports', () => {
	assert.equal(observerPortFromUrl('http://127.0.0.1:3000'), 3000);
	assert.equal(observerPortFromUrl('https://example.com'), 443);
	assert.equal(observerPortFromUrl('http://example.com/service/mcp'), 80);
});

test('readSharedObserverDiscovery reads the CLI shared observer state', () => {
	const homeDir = fs.mkdtempSync(path.join(os.tmpdir(), 'obstudio-home-'));
	try {
		const stateDir = path.join(homeDir, '.obstudio');
		fs.mkdirSync(stateDir, { recursive: true });
		fs.writeFileSync(
			path.join(stateDir, 'shared-observer.json'),
			JSON.stringify({
				baseUrl: 'http://127.0.0.1:3001/',
				controlToken: 'shared-control-token',
				updatedAt: '2026-07-28T07:08:55.652888Z',
			}),
		);

		assert.deepEqual(readSharedObserverDiscovery(homeDir), {
			baseUrl: 'http://127.0.0.1:3001',
			controlToken: 'shared-control-token',
			updatedAtMs: Date.parse('2026-07-28T07:08:55.652888Z'),
		});
	} finally {
		fs.rmSync(homeDir, { force: true, recursive: true });
	}
});

test('readSharedObserverControlToken matches the shared observer URL', () => {
	const homeDir = fs.mkdtempSync(path.join(os.tmpdir(), 'obstudio-home-'));
	try {
		const stateDir = path.join(homeDir, '.obstudio');
		fs.mkdirSync(stateDir, { recursive: true });
		fs.writeFileSync(
			path.join(stateDir, 'shared-observer.json'),
			JSON.stringify({ baseUrl: 'http://127.0.0.1:3001', controlToken: 'shared-control-token' }),
		);

		assert.equal(
			readSharedObserverControlToken('http://127.0.0.1:3001/mcp', homeDir),
			'shared-control-token',
		);
		assert.equal(
			readSharedObserverControlToken('http://localhost:3001/mcp', homeDir),
			'shared-control-token',
		);
		assert.equal(
			readSharedObserverControlToken('http://[::1]:3001/mcp', homeDir),
			'shared-control-token',
		);
		assert.equal(
			readSharedObserverControlToken('http://0.0.0.0:3001/mcp', homeDir),
			'shared-control-token',
		);
		assert.equal(
			readSharedObserverControlToken('http://[::]:3001/mcp', homeDir),
			'shared-control-token',
		);
		assert.equal(
			readSharedObserverControlToken('http://127.0.0.2:3001/mcp', homeDir),
			undefined,
			'distinct 127.x listeners must not share bearer tokens',
		);
		assert.equal(
			readSharedObserverControlToken('http://127.0.0.1:3002', homeDir),
			undefined,
		);
		assert.equal(
			readSharedObserverControlToken('https://localhost:3001', homeDir),
			undefined,
		);

		fs.writeFileSync(
			path.join(stateDir, 'shared-observer.json'),
			JSON.stringify({ baseUrl: 'http://localhost:3001', controlToken: 'localhost-state-token' }),
		);
		assert.equal(
			readSharedObserverControlToken('http://127.0.0.1:3001/mcp', homeDir),
			'localhost-state-token',
		);

		fs.writeFileSync(
			path.join(stateDir, 'shared-observer.json'),
			JSON.stringify({ baseUrl: 'http://[::1]:3001', controlToken: 'ipv6-state-token' }),
		);
		assert.equal(
			readSharedObserverControlToken('http://127.0.0.1:3001/mcp', homeDir),
			'ipv6-state-token',
		);

		fs.writeFileSync(
			path.join(stateDir, 'shared-observer.json'),
			JSON.stringify({ baseUrl: 'http://localhost', controlToken: 'http-default-port-token' }),
		);
		assert.equal(
			readSharedObserverControlToken('http://127.0.0.1:80/mcp', homeDir),
			'http-default-port-token',
		);

		fs.writeFileSync(
			path.join(stateDir, 'shared-observer.json'),
			JSON.stringify({ baseUrl: 'https://localhost', controlToken: 'https-default-port-token' }),
		);
		assert.equal(
			readSharedObserverControlToken('https://127.0.0.1:443/mcp', homeDir),
			'https-default-port-token',
		);
	} finally {
		fs.rmSync(homeDir, { force: true, recursive: true });
	}
});

test('cloud control treats loopback and wildcard bind hosts as local', () => {
	for (const hostname of [
		'localhost',
		'127.0.0.1',
		'127.0.0.2',
		'0.0.0.0',
		'::1',
		'[::1]',
		'::',
		'[::]',
	]) {
		assert.equal(isLocalObserverControlHost(hostname), true, hostname);
	}
	for (const hostname of ['192.0.2.10', 'example.test', '127.example.test', '127.999.0.1']) {
		assert.equal(isLocalObserverControlHost(hostname), false, hostname);
	}
});

test('matching shared observer state wins while mismatched state preserves the inherited token', () => {
	const homeDir = fs.mkdtempSync(path.join(os.tmpdir(), 'obstudio-home-'));
	try {
		const stateDir = path.join(homeDir, '.obstudio');
		fs.mkdirSync(stateDir, { recursive: true });
		fs.writeFileSync(
			path.join(stateDir, 'shared-observer.json'),
			JSON.stringify({ baseUrl: 'http://127.0.0.1:3001', controlToken: 'current-state-token' }),
		);

		assert.equal(
			resolveSharedObserverControlToken(
				'http://127.0.0.1:3001',
				homeDir,
				'stale-inherited-token',
			),
			'current-state-token',
		);
		assert.equal(
			resolveSharedObserverControlToken(
				'http://127.0.0.1:3002',
				homeDir,
				'inherited-token',
			),
			'inherited-token',
		);
	} finally {
		fs.rmSync(homeDir, { force: true, recursive: true });
	}
});

test('inherited shared observer token remains available when no discovery state exists', () => {
	const homeDir = fs.mkdtempSync(path.join(os.tmpdir(), 'obstudio-home-'));
	try {
		assert.equal(
			resolveSharedObserverControlToken(
				'http://127.0.0.1:3001',
				homeDir,
				'configured-inherited-token',
			),
			'configured-inherited-token',
		);
	} finally {
		fs.rmSync(homeDir, { force: true, recursive: true });
	}
});

test('readSharedObserverDiscovery ignores missing, malformed, and incomplete state', () => {
	const homeDir = fs.mkdtempSync(path.join(os.tmpdir(), 'obstudio-home-'));
	try {
		assert.equal(readSharedObserverDiscovery(homeDir), undefined);

		const stateDir = path.join(homeDir, '.obstudio');
		fs.mkdirSync(stateDir, { recursive: true });
		const statePath = path.join(stateDir, 'shared-observer.json');
		fs.writeFileSync(statePath, '{');
		assert.equal(readSharedObserverDiscovery(homeDir), undefined);

		fs.writeFileSync(statePath, JSON.stringify({ healthUrl: 'http://127.0.0.1:3001/api/health' }));
		assert.equal(readSharedObserverDiscovery(homeDir), undefined);
	} finally {
		fs.rmSync(homeDir, { force: true, recursive: true });
	}
});

test('normalizeObserverBaseUrl rejects unsupported schemes', () => {
	assert.throws(() => normalizeObserverBaseUrl('stdio://obstudio'), /http or https/);
});

test('resetObserverOutputDirs removes stale output and recreates the directory', () => {
	withTempExtensionRoot((extensionRoot) => {
		const paths = getBuildPaths(extensionRoot);

		fs.mkdirSync(paths.observerOutDir, { recursive: true });
		fs.writeFileSync(path.join(paths.observerOutDir, 'stale.txt'), 'stale');

		resetObserverOutputDirs(paths);

		assert.equal(fs.existsSync(path.join(paths.observerOutDir, 'stale.txt')), false);
		assert.equal(fs.existsSync(paths.observerOutDir), true);
	});
});

test('buildClientAssets rebuilds committed static assets before packaging', () => {
	const repoRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'obstudio-build-client-'));
	try {
		const fakeExtensionRoot = path.join(repoRoot, 'extension');
		fs.mkdirSync(fakeExtensionRoot);
		const paths = getBuildPaths(fakeExtensionRoot);
		const assetsDir = path.join(paths.observerRoot, 'internal', 'web', 'static', 'assets');
		fs.mkdirSync(assetsDir, { recursive: true });
		fs.writeFileSync(path.join(assetsDir, 'main.js'), 'committed build');

		const calls: Array<{ args: string[]; cwd: string; file: string }> = [];
		buildClientAssets(paths, (file, args, options) => {
			calls.push({ args, cwd: options.cwd, file });
		});

		assert.deepEqual(calls, [{
			args: ['run', './cmd/build-client'],
			cwd: paths.observerRoot,
			file: 'go',
		}]);
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

test('cloud bridge accepts the audit report action without a payload', () => {
	assert.equal(isCloudBridgeRequest({
		action: 'open-audit-report',
		bridgeToken: 'bridge-token-1234567890123456',
		requestId: 'request-123',
		type: 'obstudio.cloud.request',
	}), true);
	// The webview names the action only; it can never smuggle a destination.
	assert.equal(isCloudBridgeRequest({
		action: 'open-audit-report',
		bridgeToken: 'bridge-token-1234567890123456',
		payload: { url: 'https://evil.example.com' },
		requestId: 'request-123',
		type: 'obstudio.cloud.request',
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
