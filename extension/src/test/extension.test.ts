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
	getBuildPaths: (extensionRoot?: string) => {
		observerRoot: string;
		observerOutDir: string;
		observerOutBinary: string;
	};
	resetObserverOutputDirs: (paths: ReturnType<typeof getBuildPaths>) => void;
};
const weaverBinaryName = 'weaver';

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
		const weaver = path.join(extensionRoot, 'dist', 'observer', 'weaver');

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

test('build output layout reserves the bundled weaver runtime path', () => {
	withTempExtensionRoot((extensionRoot) => {
		const paths = getBuildPaths(extensionRoot);
		const expected = path.join(paths.observerOutDir, weaverBinaryName);

		assert.equal(expected.startsWith(paths.observerOutDir), true);
	});
});

test('package metadata declares an extension icon that exists', () => {
	const packageJSONPath = path.join(extensionRoot, 'package.json');
	const packageJSON = JSON.parse(fs.readFileSync(packageJSONPath, 'utf-8')) as { icon?: string };

	assert.equal(typeof packageJSON.icon, 'string');
	assert.ok(packageJSON.icon);
	assert.equal(fs.existsSync(path.join(extensionRoot, packageJSON.icon!)), true);
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
