import * as assert from 'node:assert/strict';
import * as fs from 'node:fs';
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

const extensionRoot = path.resolve(__dirname, '..', '..');
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

test('extension unload paths clean up observer state', () => {
	const extensionSourcePath = path.join(extensionRoot, 'src', 'extension.ts');
	const source = fs.readFileSync(extensionSourcePath, 'utf-8');

	assert.match(source, /export\s+async\s+function\s+deactivate\(\):\s*Promise<void>\s*\{/);
	assert.match(source, /await\s+shutdownObserverForExtensionUnload\('Extension deactivated'\)/);
	assert.match(source, /async\s+function\s+shutdownObserverForExtensionUnload\(reason:\s*string\):\s*Promise<void>/);
	assert.match(source, /await\s+stopObserver\(\)/);
	assert.match(source, /disposeObserverForExtensionUnload\('Extension disposed'\)/);
	assert.match(source, /function\s+disposeObserverForExtensionUnload\(reason:\s*string\):\s*void/);
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
