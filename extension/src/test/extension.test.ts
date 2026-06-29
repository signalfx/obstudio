import * as assert from 'node:assert/strict';
import * as fs from 'node:fs';
import * as http from 'node:http';
import * as os from 'node:os';
import * as path from 'node:path';
import test from 'node:test';
import {
	buildObserverHealthUrl,
	buildObserverValidatorSummaryUrl,
	normalizeObserverBaseUrl,
	observerPortFromUrl,
	resolveBackend,
} from '../backend';
import {
	configureObserverSplunkExport,
	forgetObserverSplunkExport,
	isO11yOAuthConnectionUsable,
	normalizeO11yOAuthIssuerUrl,
	o11yOAuthConnectionFingerprint,
	o11yOAuthSecretStorageKey,
	parseO11yOAuthForgetMarker,
	shouldForgetStoredO11yOAuthConnection,
} from '../o11y-oauth';
import {
	defaultCloudClientId,
	parseCloudConnectionOutput,
	persistCloudConnectionOrRevoke,
} from '../cloud-command';
import {
	observerControlTokenSecretStorageKey,
	resolveObserverControlToken,
} from '../observer-control-token';

const extensionRoot = path.resolve(__dirname, '..', '..');

test('Observer control token uses environment configuration for shared servers', async () => {
	const stored = new Map<string, string>();
	const storage = {
		get: async (key: string) => stored.get(key),
		store: async (key: string, value: string) => {
			stored.set(key, value);
		},
	};

	const token = await resolveObserverControlToken(storage, ' shared-control-token ', () => 'generated');

	assert.equal(token, 'shared-control-token');
	assert.equal(stored.size, 0);
});

test('Observer control token persists generated credentials in IDE SecretStorage', async () => {
	const stored = new Map<string, string>();
	const storage = {
		get: async (key: string) => stored.get(key),
		store: async (key: string, value: string) => {
			stored.set(key, value);
		},
	};

	const first = await resolveObserverControlToken(storage, undefined, () => 'generated-control-token');
	const second = await resolveObserverControlToken(storage, undefined, () => 'different-token');

	assert.equal(first, 'generated-control-token');
	assert.equal(second, first);
	assert.equal(stored.get(observerControlTokenSecretStorageKey), first);
});
const { getBuildPaths, resetObserverOutputDirs } = require('../../build-observer.js') as {
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

	assert.deepEqual(packageJSON.categories, ['Visualization', 'Debuggers', 'Testing', 'Other']);
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

test('OAuth issuer input accepts an organization URL but returns a trusted origin', () => {
	assert.equal(
		normalizeO11yOAuthIssuerUrl('https://APP.EU0.observability.splunkcloud.com/#/home'),
		'https://app.eu0.observability.splunkcloud.com',
	);
	assert.equal(
		normalizeO11yOAuthIssuerUrl('https://mon.signalfx.com/#/signin'),
		'https://mon.signalfx.com',
	);
	assert.throws(
		() => normalizeO11yOAuthIssuerUrl('https://attacker.example/#/home'),
		/registered Splunk Observability Cloud host/,
	);
	assert.throws(
		() => normalizeO11yOAuthIssuerUrl('https://user:password@app.eu0.observability.splunkcloud.com'),
		/must not contain credentials/,
	);
});

test('OAuth connection output requires a trusted issuer and bearer token', () => {
	assert.equal(o11yOAuthSecretStorageKey, 'observability-studio.o11y.oauth.connection');
	const connection = parseCloudConnectionOutput(JSON.stringify({
		accessToken: 'secret-token',
		connected: true,
		connectedAt: '2026-06-29T12:00:00Z',
		endpoint: 'https://ingest.us1.signalfx.com',
		issuer: 'https://app.us1.signalfx.com',
		realm: 'us1',
		tokenType: 'Bearer',
	}));
	assert.equal(connection.accessToken, 'secret-token');
	const internalConnection = parseCloudConnectionOutput(JSON.stringify({
		accessToken: 'internal-secret-token',
		connected: true,
		endpoint: 'https://mon-ingest.signalfx.com',
		issuer: 'https://mon.signalfx.com',
		realm: 'mon0',
		tokenType: 'Bearer',
	}));
	assert.equal(internalConnection.realm, 'mon0');
	assert.throws(
		() => parseCloudConnectionOutput('{"accessToken":"secret","issuer":"https://attacker.example"}'),
		/invalid connection/,
	);
	assert.throws(
		() => parseCloudConnectionOutput(JSON.stringify({
			accessToken: 'secret',
			endpoint: 'https://attacker.example',
			issuer: 'https://app.us1.signalfx.com',
			realm: 'us1',
			tokenType: 'Bearer',
		})),
		/invalid connection/,
	);
	assert.throws(
		() => parseCloudConnectionOutput(JSON.stringify({
			accessToken: 'secret',
			endpoint: 'https://ingest.us1.signalfx.com:8443/v2/datapoint/otlp',
			issuer: 'https://app.us1.signalfx.com',
			realm: 'us1',
			tokenType: 'Bearer',
		})),
		/invalid connection/,
	);
});

test('OAuth client registration follows the extension host', () => {
	assert.equal(defaultCloudClientId('Visual Studio Code'), 'obstudio-vscode');
	assert.equal(defaultCloudClientId('Cursor'), 'obstudio-cursor');
});

test('OAuth connection is revoked when IDE SecretStorage fails', async () => {
	let revoked = false;
	await assert.rejects(
		persistCloudConnectionOrRevoke(
			{
				accessToken: 'secret-token',
				connectedAt: '2026-06-29T12:00:00Z',
				endpoint: 'https://ingest.us1.signalfx.com',
				issuer: 'https://app.us1.signalfx.com',
				realm: 'us1',
				tokenType: 'Bearer',
			},
			async () => { throw new Error('keychain unavailable'); },
			async () => { revoked = true; },
		),
		/issued token was revoked/,
	);
	assert.equal(revoked, true);
});

test('OAuth forget marker only clears older stored connections', () => {
	const oldConnection = {
		accessToken: 'old-token',
		connectedAt: '2026-06-27T09:59:59.000Z',
		issuer: 'https://app.us0.signalfx.com',
		tokenType: 'Bearer',
	};
	const marker = parseO11yOAuthForgetMarker(JSON.stringify({
		connectionFingerprint: o11yOAuthConnectionFingerprint(oldConnection),
		forgottenAt: '2026-06-27T10:00:00.000Z',
	}));
	assert.ok(marker);
	assert.equal(
		shouldForgetStoredO11yOAuthConnection(oldConnection, marker),
		true,
	);
	assert.equal(
		shouldForgetStoredO11yOAuthConnection({
			...oldConnection,
			accessToken: 'different-token',
			tokenType: 'Bearer',
		}, marker),
		false,
	);
	assert.equal(
		shouldForgetStoredO11yOAuthConnection({
			...oldConnection,
			connectedAt: '2026-06-27T10:00:01.000Z',
		}, marker),
		false,
	);
	assert.equal(parseO11yOAuthForgetMarker('{"forgottenAt":"2026-06-27T10:00:00.000Z"}'), undefined);
	assert.equal(parseO11yOAuthForgetMarker('not-json'), undefined);
});

test('OAuth connection fingerprint canonicalizes issuer origins', () => {
	const connection = {
		accessToken: 'sf-token',
		connectedAt: '2026-06-27T09:59:59.000Z',
		issuer: 'https://APP.US0.signalfx.com:443/',
		tokenType: 'Bearer',
	};
	assert.equal(
		o11yOAuthConnectionFingerprint(connection),
		o11yOAuthConnectionFingerprint({
			...connection,
			issuer: 'https://app.us0.signalfx.com',
		}),
	);
});

test('OAuth connection reuse requires a non-expired token with all requested scopes', () => {
	const connection = {
		accessToken: 'sf-token',
		connectedAt: '2026-06-27T10:00:00.000Z',
		expiresAt: '2026-06-27T12:00:00.000Z',
		issuer: 'https://app.us0.signalfx.com',
		scope: 'api ingest',
		tokenId: 'token-id',
		tokenName: 'Obstudio token',
		tokenType: 'Bearer',
	};
	const now = new Date('2026-06-27T11:00:00.000Z');

	assert.equal(isO11yOAuthConnectionUsable(connection, 'ingest', now), true);
	assert.equal(
		isO11yOAuthConnectionUsable({ ...connection, tokenId: undefined, tokenName: undefined }, 'ingest', now),
		true,
	);
	assert.equal(isO11yOAuthConnectionUsable(connection, 'ingest api', now), true);
	assert.equal(isO11yOAuthConnectionUsable(connection, 'admin', now), false);
	assert.equal(isO11yOAuthConnectionUsable({ ...connection, accessToken: ' ' }, 'ingest', now), false);
	assert.equal(
		isO11yOAuthConnectionUsable({ ...connection, expiresAt: '2026-06-27T11:00:30.000Z' }, 'ingest', now),
		false,
	);
	assert.equal(isO11yOAuthConnectionUsable({ ...connection, expiresAt: 'invalid' }, 'ingest', now), false);
});

test('OAuth connection configures local observer export with control token', async () => {
	let receivedAuth = '';
	let receivedBody = '';
	const server = http.createServer((request, response) => {
		receivedAuth = request.headers.authorization ?? '';
		request.on('data', (chunk: Buffer) => {
			receivedBody += chunk.toString('utf8');
		});
		request.on('end', () => {
			assert.equal(request.method, 'POST');
			assert.equal(request.url, '/api/splunk/export');
			response.writeHead(200, { 'Content-Type': 'application/json' });
			response.end(JSON.stringify({ metrics: { configured: true }, traces: { configured: true } }));
		});
	});

	const baseUrl = await new Promise<string>((resolve, reject) => {
		server.once('error', reject);
		server.listen(0, '127.0.0.1', () => {
			const address = server.address();
			if (typeof address === 'object' && address !== null) {
				resolve(`http://127.0.0.1:${address.port}`);
			} else {
				reject(new Error('server did not bind to an address'));
			}
		});
	});
	try {
		await configureObserverSplunkExport({
			baseUrl,
			connection: {
				accessToken: 'sf-secret',
				connectedAt: '2026-06-27T00:00:00.000Z',
				endpoint: 'https://ingest.lab0.signalfx.com',
				issuer: 'http://127.0.0.1:3000',
				realm: 'lab0',
				tokenId: 'token-id',
				tokenName: 'Obstudio token',
				tokenType: 'Bearer',
			},
			controlToken: 'control-secret',
		});
	} finally {
		await new Promise<void>((resolve) => {
			server.close(() => resolve());
		});
	}

	assert.equal(receivedAuth, 'Bearer control-secret');
	const payload = JSON.parse(receivedBody) as {
		accessToken?: string;
		enabled?: boolean;
		endpoint?: string;
		issuer?: string;
		realm?: string;
	};
	assert.equal(payload.accessToken, 'sf-secret');
	assert.equal(payload.enabled, false);
	assert.equal(payload.endpoint, 'https://ingest.lab0.signalfx.com');
	assert.equal(payload.issuer, 'http://127.0.0.1:3000');
	assert.equal(payload.realm, 'lab0');
});

test('OAuth helper clears local observer export with control token', async () => {
	let receivedAuth = '';
	let receivedBody = '';
	const server = http.createServer((request, response) => {
		receivedAuth = request.headers.authorization ?? '';
		request.on('data', (chunk: Buffer) => {
			receivedBody += chunk.toString('utf8');
		});
		request.on('end', () => {
			assert.equal(request.method, 'POST');
			assert.equal(request.url, '/api/splunk/export/forget');
			response.writeHead(200, { 'Content-Type': 'application/json' });
			response.end(JSON.stringify({ metrics: { accessTokenConfigured: false }, traces: { accessTokenConfigured: false } }));
		});
	});

	const baseUrl = await new Promise<string>((resolve, reject) => {
		server.once('error', reject);
		server.listen(0, '127.0.0.1', () => {
			const address = server.address();
			if (typeof address === 'object' && address !== null) {
				resolve(`http://127.0.0.1:${address.port}`);
			} else {
				reject(new Error('server did not bind to an address'));
			}
		});
	});
	try {
		await forgetObserverSplunkExport({
			baseUrl,
			controlToken: 'control-secret',
		});
	} finally {
		await new Promise<void>((resolve) => {
			server.close(() => resolve());
		});
	}

	assert.equal(receivedAuth, 'Bearer control-secret');
	assert.equal(receivedBody, '{}');
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
