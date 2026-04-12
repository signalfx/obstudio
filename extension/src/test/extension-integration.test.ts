import * as assert from 'node:assert/strict';
import * as fs from 'node:fs';
import * as path from 'node:path';
import * as http from 'node:http';
import { execSync, execFileSync, spawn } from 'node:child_process';
import test, { describe, it } from 'node:test';

const extensionRoot = path.resolve(__dirname, '..', '..');
const repoRoot = path.resolve(extensionRoot, '..');

/** Resolve the locally-installed vsce binary. Fails if not found. */
function vsceCommand(): string {
	const localBin = path.join(extensionRoot, 'node_modules', '.bin', 'vsce');
	assert.ok(
		fs.existsSync(localBin),
		'@vscode/vsce must be installed locally (run npm install)'
	);
	return localBin;
}

interface TestContext {
	vsixFile?: string;
}

type ExtensionPackage = {
	contributes?: {
		commands?: Array<{
			category?: string;
			command: string;
			title: string;
		}>;
		configuration?: {
			properties?: Record<string, unknown>;
		};
	};
};

function cleanup(context: TestContext): void {
	if (context.vsixFile && fs.existsSync(context.vsixFile)) {
		try {
			fs.unlinkSync(context.vsixFile);
		} catch (e) {
			// Ignore cleanup errors
		}
	}
}

/** Build VSIX once and return its path. Fails if vsce is not installed locally. */
function buildVsix(): string {
	const vsce = vsceCommand();
	const output = execSync(`"${vsce}" package --no-dependencies`, {
		cwd: extensionRoot,
		stdio: 'pipe',
		timeout: 120_000,
		encoding: 'utf-8',
	});

	const vsixMatch = output.match(/(\S+\.vsix)/);
	assert.ok(vsixMatch, 'vsce should output the generated .vsix file path');
	return path.join(extensionRoot, vsixMatch[1]);
}

it('integration: buildObserverGo produces a binary', { timeout: 120_000 }, async (t) => {
	const buildObserverPath = path.join(extensionRoot, 'build-observer.js');
	assert.ok(fs.existsSync(buildObserverPath), 'build-observer.js should exist');

	try {
		// Run the build-observer.js script
		execFileSync('node', [buildObserverPath], {
			cwd: extensionRoot,
			stdio: 'pipe',
			timeout: 120_000,
		});

		// Verify the binary was created
		const binaryPath = path.join(extensionRoot, 'dist', 'observer', 'obstudio');
		assert.ok(fs.existsSync(binaryPath), `Binary should exist at ${binaryPath}`);

		// Verify it's executable
		const stats = fs.statSync(binaryPath);
		const isExecutable = (stats.mode & 0o111) !== 0;
		assert.ok(isExecutable, 'Binary should be executable');
	} catch (error) {
		const errorMessage = error instanceof Error ? error.message : String(error);
		// Skip (not pass) when the Go toolchain itself is not installed.
		if (
			errorMessage.includes('go: command not found') ||
			errorMessage.includes("'go' is not recognized")
		) {
			t.skip('Go toolchain not installed');
			return;
		}
		throw error;
	}
});

it('integration: VSIX packages successfully', { timeout: 120_000 }, async () => {
	const context: TestContext = {};

	try {
		const vsixFile = buildVsix();
		context.vsixFile = vsixFile;

		assert.ok(fs.existsSync(vsixFile), `VSIX file should exist at ${vsixFile}`);

		// Verify it's a valid file with some size
		const stats = fs.statSync(vsixFile);
		assert.ok(stats.size > 0, 'VSIX file should have content');
	} finally {
		cleanup(context);
	}
});

it('integration: VSIX contains observer binary', { timeout: 120_000 }, async () => {
	const context: TestContext = {};

	try {
		const vsixFile = buildVsix();
		context.vsixFile = vsixFile;

		// List contents of VSIX
		const unzipOutput = execSync(`unzip -l "${vsixFile}"`, {
			stdio: 'pipe',
			encoding: 'utf-8',
		});

		assert.ok(
			unzipOutput.includes('extension/dist/observer/obstudio'),
			'VSIX should contain extension/dist/observer/obstudio binary'
		);
	} finally {
		cleanup(context);
	}
});

it('integration: VSIX contains extension.js', { timeout: 120_000 }, async () => {
	const context: TestContext = {};

	try {
		const vsixFile = buildVsix();
		context.vsixFile = vsixFile;

		// List contents of VSIX
		const unzipOutput = execSync(`unzip -l "${vsixFile}"`, {
			stdio: 'pipe',
			encoding: 'utf-8',
		});

		assert.ok(
			unzipOutput.includes('extension/dist/extension.js'),
			'VSIX should contain extension/dist/extension.js'
		);
	} finally {
		cleanup(context);
	}
});

it('integration: extension.js exports activate and deactivate', { timeout: 120_000 }, async () => {
	const extensionJsPath = path.join(extensionRoot, 'dist', 'extension.js');

	// Delete any stale artifact so the test cannot pass on a leftover file.
	if (fs.existsSync(extensionJsPath)) {
		fs.unlinkSync(extensionJsPath);
	}

	// Compile — must succeed for the test to be meaningful.
	execSync('npm run compile', {
		cwd: extensionRoot,
		stdio: 'pipe',
		timeout: 120_000,
	});

	assert.ok(fs.existsSync(extensionJsPath), `extension.js should exist at ${extensionJsPath}`);

	// The extension.js requires 'vscode' which is only available inside VS Code runtime.
	// Instead of loading the module, verify exports statically by checking the source.
	const source = fs.readFileSync(extensionJsPath, 'utf-8');

	// esbuild IIFE bundles assign exports on the module.exports or exports object
	assert.ok(
		source.includes('activate') && source.includes('deactivate'),
		'extension.js should contain activate and deactivate exports'
	);

	// Verify the bundle references key extension functionality
	assert.ok(
		source.includes('obstudio'),
		'extension.js should reference obstudio binary'
	);

	// Verify all 5 commands are registered in the compiled bundle
	for (const cmd of [
		'observability-studio.openObserver',
		'observability-studio.statusMenu',
		'observability-studio.startObserver',
		'observability-studio.stopObserver',
		'observability-studio.restartObserver',
	]) {
		assert.ok(source.includes(cmd), `extension.js should register command "${cmd}"`);
	}

	// Verify status bar states are present
	assert.ok(source.includes('loading~spin'), 'extension.js should contain starting spinner icon');
	assert.ok(source.includes('pulse'), 'extension.js should contain running pulse icon');
	assert.ok(source.includes('circle-outline'), 'extension.js should contain stopped icon');

	// Verify error and stopped webview pages are present
	assert.ok(source.includes('Observer could not start'), 'extension.js should contain error webview heading');
	assert.ok(source.includes('Observer is stopped'), 'extension.js should contain stopped webview message');

	// Verify port conflict detection
	assert.ok(source.includes('EADDRINUSE'), 'extension.js should handle EADDRINUSE port conflicts');
	assert.ok(source.includes('lsof'), 'extension.js should use lsof to identify port owners');

	// Verify async stop with SIGTERM/SIGKILL
	assert.ok(source.includes('SIGTERM'), 'extension.js should send SIGTERM on stop');
	assert.ok(source.includes('SIGKILL'), 'extension.js should fallback to SIGKILL');
});

it('integration: package.json registers all commands', () => {
	const pkgPath = path.join(extensionRoot, 'package.json');
	const pkg = JSON.parse(fs.readFileSync(pkgPath, 'utf-8'));
	const commands = (pkg.contributes?.commands ?? []).map((c: { command: string }) => c.command);

	for (const expected of [
		'observability-studio.openObserver',
		'observability-studio.statusMenu',
		'observability-studio.startObserver',
		'observability-studio.stopObserver',
		'observability-studio.restartObserver',
		'observability-studio.setup',
	]) {
		assert.ok(
			commands.includes(expected),
			`package.json should register command "${expected}"`
		);
	}
});

it('integration: contributed commands are grouped under Observability Studio', async () => {
	const packageJsonPath = path.join(extensionRoot, 'package.json');
	const packageJson = JSON.parse(fs.readFileSync(packageJsonPath, 'utf-8')) as ExtensionPackage;
	const commands = packageJson.contributes?.commands ?? [];
	const expectedCommands = [
		'observability-studio.openObserver',
		'observability-studio.setup',
		'observability-studio.configureCodexMCP',
		'observability-studio.configureClaudeCodeMCP',
		'observability-studio.configureCursorMCP',
	];

	for (const commandId of expectedCommands) {
		const command = commands.find((entry) => entry.command === commandId);
		assert.ok(command, `command ${commandId} should be contributed`);
		assert.equal(
			command?.category,
			'Observability Studio',
			`command ${commandId} should be grouped under Observability Studio`,
		);
	}
});

it('integration: package.json contributes sharedObserverUrl setting', async () => {
	const packageJsonPath = path.join(extensionRoot, 'package.json');
	const packageJson = JSON.parse(fs.readFileSync(packageJsonPath, 'utf-8')) as ExtensionPackage;
	const property = packageJson.contributes?.configuration?.properties?.['observability-studio.sharedObserverUrl'];

	assert.ok(property, 'sharedObserverUrl setting should be contributed');
});

it('integration: package.json contributes local observer port settings', async () => {
	const packageJsonPath = path.join(extensionRoot, 'package.json');
	const packageJson = JSON.parse(fs.readFileSync(packageJsonPath, 'utf-8')) as ExtensionPackage;
	const properties = packageJson.contributes?.configuration?.properties ?? {};

	assert.ok(properties['observability-studio.localObserverPort']);
	assert.ok(properties['observability-studio.localOtlpHttpPort']);
	assert.ok(properties['observability-studio.localOtlpGrpcPort']);
});

it('integration: binary serves client UI assets', { timeout: 180_000 }, async (t) => {
	const binaryPath = path.join(extensionRoot, 'dist', 'observer', 'obstudio');
	const assetsDir = path.join(repoRoot, 'observer', 'internal', 'web', 'static', 'assets');

	// Delete pre-existing client assets so build-observer.js must produce them.
	fs.rmSync(assetsDir, { force: true, recursive: true });

	const buildObserverPath = path.join(extensionRoot, 'build-observer.js');
	try {
		execFileSync('node', [buildObserverPath], {
			cwd: extensionRoot,
			stdio: 'pipe',
			timeout: 120_000,
		});
	} catch (error) {
		const errorMessage = error instanceof Error ? error.message : String(error);
		if (
			errorMessage.includes('go: command not found') ||
			errorMessage.includes("'go' is not recognized")
		) {
			t.skip('Go toolchain not installed');
			return;
		}
		throw error;
	}

	assert.ok(fs.existsSync(binaryPath), `Binary should exist at ${binaryPath}`);

	// Start the binary and verify it serves UI assets.
	// Use unique ports for all listeners to avoid conflicts with other tests or processes.
	const port = 13579;
	const child = spawn(binaryPath, [], {
		env: {
			...process.env,
			PORT: String(port),
			OTLP_GRPC_PORT: '13580',
			OTLP_HTTP_PORT: '13581',
		},
		stdio: 'pipe',
	});

	try {
		// Wait for the server to be ready (up to 5s).
		await new Promise<void>((resolve, reject) => {
			const timeout = setTimeout(() => reject(new Error('Server did not start within 5s')), 5000);
			const check = () => {
				const req = http.get(`http://127.0.0.1:${port}/`, (res) => {
					res.resume();
					clearTimeout(timeout);
					resolve();
				});
				req.on('error', () => setTimeout(check, 200));
			};
			check();
		});

		// Verify main.js is served.
		const jsStatus = await new Promise<number>((resolve, reject) => {
			http.get(`http://127.0.0.1:${port}/assets/main.js`, (res) => {
				res.resume();
				resolve(res.statusCode ?? 0);
			}).on('error', reject);
		});
		assert.equal(jsStatus, 200, '/assets/main.js should return 200 — client assets not embedded in binary');

		// Verify main.css is served.
		const cssStatus = await new Promise<number>((resolve, reject) => {
			http.get(`http://127.0.0.1:${port}/assets/main.css`, (res) => {
				res.resume();
				resolve(res.statusCode ?? 0);
			}).on('error', reject);
		});
		assert.equal(cssStatus, 200, '/assets/main.css should return 200 — client assets not embedded in binary');
	} finally {
		child.kill();
	}
});
