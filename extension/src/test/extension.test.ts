import * as assert from 'node:assert/strict';
import * as fs from 'node:fs';
import * as os from 'node:os';
import * as path from 'node:path';
import test from 'node:test';
import { resolveBackend } from '../backend';

const { getBuildPaths, resetObserverOutputDirs } = require('../../build-observer.js') as {
	getBuildPaths: (extensionRoot?: string) => {
		observerGoRoot: string;
		observerGoOutDir: string;
		observerGoOutBinary: string;
	};
	resetObserverOutputDirs: (paths: ReturnType<typeof getBuildPaths>) => void;
};

function withTempExtensionRoot(run: (extensionRoot: string) => void) {
	const extensionRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'obstudio-extension-'));

	try {
		run(extensionRoot);
	} finally {
		fs.rmSync(extensionRoot, { force: true, recursive: true });
	}
}

test('resolveBackend returns observer-go binary when it exists', () => {
	withTempExtensionRoot((extensionRoot) => {
		const binary = path.join(extensionRoot, 'dist', 'observer-go', 'obstudio');

		fs.mkdirSync(path.dirname(binary), { recursive: true });
		fs.writeFileSync(binary, '#!/bin/sh\n');

		const backend = resolveBackend(extensionRoot);

		assert.equal(backend.command, binary);
		assert.deepEqual(backend.args, []);
		assert.equal(backend.cwd, path.dirname(binary));
		assert.equal(backend.label, 'observer-go');
	});
});

test('resolveBackend throws when the observer-go binary is missing', () => {
	withTempExtensionRoot((extensionRoot) => {
		assert.throws(() => resolveBackend(extensionRoot), /observer-go binary not found/);
	});
});

test('resetObserverOutputDirs removes stale output and recreates the directory', () => {
	withTempExtensionRoot((extensionRoot) => {
		const paths = getBuildPaths(extensionRoot);

		fs.mkdirSync(paths.observerGoOutDir, { recursive: true });
		fs.writeFileSync(path.join(paths.observerGoOutDir, 'stale.txt'), 'stale');

		resetObserverOutputDirs(paths);

		assert.equal(fs.existsSync(path.join(paths.observerGoOutDir, 'stale.txt')), false);
		assert.equal(fs.existsSync(paths.observerGoOutDir), true);
	});
});
