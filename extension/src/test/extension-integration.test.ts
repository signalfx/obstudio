import * as assert from 'node:assert/strict';
import * as fs from 'node:fs';
import * as path from 'node:path';
import * as http from 'node:http';
import * as net from 'node:net';
import * as os from 'node:os';
import { execSync, execFileSync, spawn } from 'node:child_process';
import test, { describe, it } from 'node:test';
import { downloadAndUnzipVSCode, resolveCliArgsFromVSCodeExecutablePath } from '@vscode/test-electron';
import { currentVsCodeTarget } from '../startup-errors';

const extensionRoot = path.resolve(__dirname, '..', '..');
const repoRoot = path.resolve(extensionRoot, '..');
const nodeExecutable = process.execPath;

interface TestContext {
	ownsVsix?: boolean;
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
	if (context.ownsVsix === false) {
		return;
	}
	if (context.vsixFile && fs.existsSync(context.vsixFile)) {
		try {
			fs.unlinkSync(context.vsixFile);
		} catch (e) {
			// Ignore cleanup errors
		}
	}
}

/** Build VSIX once and return its path. Fails if @vscode/vsce is not installed locally. */
function buildVsix(env: NodeJS.ProcessEnv = process.env): string {
	return buildVsixWithArgs([], env);
}

function buildVsixWithArgs(extraArgs: string[], env: NodeJS.ProcessEnv = process.env): string {
	const output = execFileSync(nodeExecutable, ['build-vsix.js', '--no-dependencies', ...extraArgs], {
		cwd: extensionRoot,
		stdio: 'pipe',
		timeout: 120_000,
		encoding: 'utf-8',
		env,
	});

	const vsixMatch = output.match(/(\S+\.vsix)/);
	assert.ok(vsixMatch, 'vsce should output the generated .vsix file path');
	return path.join(extensionRoot, vsixMatch[1]);
}

function resolvePrebuiltVsixFile(env: NodeJS.ProcessEnv = process.env): string | undefined {
	const directPath = env.OBSTUDIO_PREBUILT_VSIX?.trim();
	if (directPath) {
		const candidate = path.isAbsolute(directPath)
			? directPath
			: path.resolve(extensionRoot, directPath);
		assert.ok(fs.existsSync(candidate), `expected prebuilt VSIX at ${candidate}`);
		return candidate;
	}

	const vsixDir = env.OBSTUDIO_PREBUILT_VSIX_DIR?.trim();
	if (!vsixDir) {
		return undefined;
	}
	const resolvedDir = path.isAbsolute(vsixDir)
		? vsixDir
		: path.resolve(extensionRoot, vsixDir);
	assert.ok(fs.existsSync(resolvedDir), `expected prebuilt VSIX directory at ${resolvedDir}`);
	const vsixFiles = fs.readdirSync(resolvedDir)
		.filter((value) => value.endsWith('.vsix'))
		.sort();
	assert.equal(
		vsixFiles.length,
		1,
		`expected exactly one prebuilt VSIX in ${resolvedDir}, found: ${vsixFiles.join(', ') || '(none)'}`,
	);
	return path.join(resolvedDir, vsixFiles[0]);
}

function currentVsixTarget(): string | undefined {
	const target = currentVsCodeTarget();
	return new Set(['darwin-arm64', 'darwin-x64', 'linux-x64', 'win32-x64']).has(target)
		? target
		: undefined;
}

function getPackagedObserverBinaryName(): string {
	return process.platform === 'win32' ? 'obstudio.exe' : 'obstudio';
}

function getPackagedWeaverBinaryName(): string {
	return process.platform === 'win32' ? 'weaver.exe' : 'weaver';
}

function findInstalledExtensionDir(extensionsDir: string): string {
	const names = fs.readdirSync(extensionsDir);
	const match = names.find((value) => value.startsWith('splunk.observability-studio-'));
	assert.ok(match, `expected installed extension under ${extensionsDir}`);
	return path.join(extensionsDir, match!);
}

async function getAvailablePort(): Promise<number> {
	return new Promise((resolve, reject) => {
		const server = net.createServer();
		server.once('error', reject);
		server.listen(0, '127.0.0.1', () => {
			const address = server.address();
			if (address === null || typeof address === 'string') {
				server.close(() => reject(new Error('Unable to allocate a test port.')));
				return;
			}
			server.close((error) => {
				if (error) {
					reject(error);
					return;
				}
				resolve(address.port);
			});
		});
	});
}

async function terminateChild(child: ReturnType<typeof spawn>): Promise<void> {
	if (child.exitCode !== null || child.killed) {
		return;
	}
	child.kill();
	await Promise.race([
		new Promise<void>((resolve) => child.once('exit', () => resolve())),
		new Promise<void>((resolve) => {
			setTimeout(() => {
				if (child.exitCode === null && !child.killed) {
					child.kill('SIGKILL');
				}
				resolve();
			}, 2_000);
		}),
	]);
}

async function waitFor<T>(
	load: () => Promise<T>,
	ready: (value: T) => boolean,
	timeoutMs: number,
): Promise<T> {
	const deadline = Date.now() + timeoutMs;
	let lastValue: T | undefined;
	let lastError: unknown;

	while (Date.now() < deadline) {
		try {
			lastValue = await load();
			if (ready(lastValue)) {
				return lastValue;
			}
			lastError = undefined;
		} catch (error) {
			lastError = error;
		}
		await new Promise((resolve) => setTimeout(resolve, 200));
	}

	if (lastValue !== undefined) {
		return lastValue;
	}
	if (lastError instanceof Error) {
		throw lastError;
	}
	throw new Error('Timed out waiting for condition');
}

async function waitForHttpOrExit(url: string, child: ReturnType<typeof spawn>, timeoutMs: number): Promise<void> {
	const deadline = Date.now() + timeoutMs;
	let lastError: unknown;

	while (Date.now() < deadline) {
		if (child.exitCode !== null || child.killed) {
			throw new Error(`Observer exited before becoming ready at ${url}.`);
		}

		try {
			await new Promise<void>((resolve, reject) => {
				http.get(url, (response) => {
					response.resume();
					resolve();
				}).on('error', reject);
			});
			return;
		} catch (error) {
			lastError = error;
			await new Promise((resolve) => setTimeout(resolve, 200));
		}
	}

	if (child.exitCode !== null || child.killed) {
		throw new Error(`Observer exited before becoming ready at ${url}.`);
	}
	if (lastError instanceof Error) {
		throw lastError;
	}
	throw new Error(`Timed out waiting for ${url}`);
}

async function requestJson(url: string, options: {
	body?: Buffer | string;
	headers?: Record<string, string>;
	method: 'DELETE' | 'GET' | 'POST';
}): Promise<{ body: any; statusCode: number }> {
	return new Promise((resolve, reject) => {
		const request = http.request(url, {
			method: options.method,
			headers: options.headers,
		}, (response) => {
			let raw = '';
			response.setEncoding('utf8');
			response.on('data', (chunk) => {
				raw += chunk;
			});
			response.on('end', () => {
				const body = raw.length === 0 ? undefined : JSON.parse(raw);
				resolve({
					body,
					statusCode: response.statusCode ?? 0,
				});
			});
		});
		request.on('error', reject);
		if (options.body !== undefined) {
			request.write(options.body);
		}
		request.end();
	});
}

it('integration: buildObserverGo produces a binary', { timeout: 120_000 }, async (t) => {
	const buildObserverPath = path.join(extensionRoot, 'build-observer.js');
	assert.ok(fs.existsSync(buildObserverPath), 'build-observer.js should exist');

	try {
		// Run the build-observer.js script
		execFileSync(nodeExecutable, [buildObserverPath], {
			cwd: extensionRoot,
			stdio: 'pipe',
			timeout: 120_000,
		});

		// Verify the binary was created
		const binaryPath = path.join(extensionRoot, 'dist', 'observer', 'obstudio');
		assert.ok(fs.existsSync(binaryPath), `Binary should exist at ${binaryPath}`);
		const weaverPath = path.join(extensionRoot, 'dist', 'observer', getPackagedWeaverBinaryName());
		assert.ok(fs.existsSync(weaverPath), `Weaver runtime should exist at ${weaverPath}`);

		// Verify it's executable
		const stats = fs.statSync(binaryPath);
		const isExecutable = (stats.mode & 0o111) !== 0;
		assert.ok(isExecutable, 'Binary should be executable');
		const weaverStats = fs.statSync(weaverPath);
		const weaverIsExecutable = (weaverStats.mode & 0o111) !== 0;
		assert.ok(weaverIsExecutable, 'Weaver runtime should be executable');
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

it('integration: VSIX manifest version can be derived from release metadata', { timeout: 120_000 }, async () => {
	const context: TestContext = {};

	try {
		const sourcePackageJson = JSON.parse(
			fs.readFileSync(path.join(extensionRoot, 'package.json'), 'utf-8'),
		) as { version: string };
		assert.equal(sourcePackageJson.version, '0.0.1');

		const vsixFile = buildVsix({
			...process.env,
			OBSTUDIO_EXTENSION_VERSION: 'v1.2.3',
		});
		context.vsixFile = vsixFile;

		const packagedManifest = execSync(
			`unzip -p "${vsixFile}" extension/package.json`,
			{ stdio: 'pipe', encoding: 'utf-8' },
		);
		const packagedPackageJson = JSON.parse(packagedManifest) as { version: string };

		assert.equal(packagedPackageJson.version, '1.2.3');

		const sourcePackageJsonAfterBuild = JSON.parse(
			fs.readFileSync(path.join(extensionRoot, 'package.json'), 'utf-8'),
		) as { version: string };
		assert.equal(
			sourcePackageJsonAfterBuild.version,
			'0.0.1',
			'build-vsix.js should not mutate the checked-in package.json version',
		);
	} finally {
		cleanup(context);
	}
});

it('integration: VSIX manifest version normalizes suffixed release tags', { timeout: 120_000 }, async () => {
	const context: TestContext = {};

	try {
		const vsixFile = buildVsix({
			...process.env,
			OBSTUDIO_EXTENSION_VERSION: 'v0.0.6-test',
		});
		context.vsixFile = vsixFile;

		const packagedManifest = execSync(
			`unzip -p "${vsixFile}" extension/package.json`,
			{ stdio: 'pipe', encoding: 'utf-8' },
		);
		const packagedPackageJson = JSON.parse(packagedManifest) as { version: string };

		assert.equal(packagedPackageJson.version, '0.0.6');
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
		assert.ok(
			unzipOutput.includes(`extension/dist/observer/${getPackagedWeaverBinaryName()}`),
			`VSIX should contain extension/dist/observer/${getPackagedWeaverBinaryName()} runtime`
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
	]) {
		assert.ok(
			commands.includes(expected),
			`package.json should register command "${expected}"`
		);
	}
});

it('integration: contributed commands are grouped under Splunk Observability Studio', async () => {
	const packageJsonPath = path.join(extensionRoot, 'package.json');
	const packageJson = JSON.parse(fs.readFileSync(packageJsonPath, 'utf-8')) as ExtensionPackage;
	const commands = packageJson.contributes?.commands ?? [];
	const expectedCommands = [
		'observability-studio.openObserver',
		'observability-studio.configureCodexMCP',
		'observability-studio.configureClaudeCodeMCP',
		'observability-studio.configureCursorMCP',
	];

	for (const commandId of expectedCommands) {
		const command = commands.find((entry) => entry.command === commandId);
		assert.ok(command, `command ${commandId} should be contributed`);
		assert.equal(
			command?.category,
			'Splunk Observability Studio',
			`command ${commandId} should be grouped under Splunk Observability Studio`,
		);
	}
});

it('integration: package.json contributes sharedObserverUrl setting', async () => {
	const packageJsonPath = path.join(extensionRoot, 'package.json');
	const packageJson = JSON.parse(fs.readFileSync(packageJsonPath, 'utf-8')) as ExtensionPackage;
	const property = packageJson.contributes?.configuration?.properties?.['observability-studio.sharedObserverUrl'];

	assert.ok(property, 'sharedObserverUrl setting should be contributed');
});

it('integration: binary serves client UI assets', { timeout: 180_000 }, async (t) => {
	const binaryPath = path.join(extensionRoot, 'dist', 'observer', 'obstudio');
	const assetsDir = path.join(repoRoot, 'observer', 'internal', 'web', 'static', 'assets');

	// Delete pre-existing client assets so build-observer.js must produce them.
	fs.rmSync(assetsDir, { force: true, recursive: true });

	const buildObserverPath = path.join(extensionRoot, 'build-observer.js');
	try {
		execFileSync(nodeExecutable, [buildObserverPath], {
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

it('integration: packaged binary enables validator when bundled weaver is present', { timeout: 180_000 }, async (t) => {
	const binaryPath = path.join(extensionRoot, 'dist', 'observer', 'obstudio');
	const buildObserverPath = path.join(extensionRoot, 'build-observer.js');
	try {
		execFileSync(nodeExecutable, [buildObserverPath], {
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

	const port = 13582;
	const child = spawn(binaryPath, [], {
		env: {
			...process.env,
			PORT: String(port),
			OTLP_GRPC_PORT: '13583',
			OTLP_HTTP_PORT: '13584',
		},
		stdio: 'pipe',
	});

	try {
		const summary = await new Promise<Record<string, unknown>>((resolve, reject) => {
			const timeout = setTimeout(() => reject(new Error('Validator summary did not become available within 10s')), 10_000);
			const check = () => {
				http.get(`http://127.0.0.1:${port}/api/query/validation/summary`, (res) => {
					let body = '';
					res.setEncoding('utf-8');
					res.on('data', (chunk) => {
						body += chunk;
					});
					res.on('end', () => {
						if ((res.statusCode ?? 0) !== 200) {
							setTimeout(check, 200);
							return;
						}
						try {
							const parsed = JSON.parse(body) as Record<string, unknown>;
							if (parsed.status === 'starting') {
								setTimeout(check, 200);
								return;
							}
							clearTimeout(timeout);
							resolve(parsed);
						} catch {
							setTimeout(check, 200);
						}
					});
				}).on('error', () => setTimeout(check, 200));
			};
			check();
		});

		assert.equal(summary.enabled, true, 'validator should be enabled when packaged weaver is bundled');
		assert.notEqual(summary.message, 'Validator unavailable', 'packaged binary should not report validator unavailable');
	} finally {
		child.kill();
	}
});

it('integration: installed VSIX smoke test starts the packaged observer and accepts OTLP traces', { timeout: 240_000 }, async (t) => {
	const target = currentVsixTarget();
	if (!target) {
		t.skip(`unsupported platform for VSIX smoke test: ${process.platform}/${process.arch}`);
		return;
	}

	const context: TestContext = {};
	let tempRoot = '';
	let child: ReturnType<typeof spawn> | undefined;

	try {
		const prebuiltVsixFile = resolvePrebuiltVsixFile();
		if (prebuiltVsixFile) {
			context.ownsVsix = false;
			context.vsixFile = prebuiltVsixFile;
		} else {
			try {
				const vsixFile = buildVsixWithArgs(['--target', target]);
				context.ownsVsix = true;
				context.vsixFile = vsixFile;
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
		}

		tempRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'obstudio-vsix-install-'));
		const extensionsDir = path.join(tempRoot, 'extensions');
		const userDataDir = path.join(tempRoot, 'user-data');
		fs.mkdirSync(extensionsDir, { recursive: true });
		fs.mkdirSync(userDataDir, { recursive: true });

		const vscodeExecutablePath = await downloadAndUnzipVSCode();
		const [cli, ...cliArgs] = resolveCliArgsFromVSCodeExecutablePath(vscodeExecutablePath);
		execFileSync(
			cli,
			[
				...cliArgs,
				'--install-extension',
				context.vsixFile!,
				'--extensions-dir',
				extensionsDir,
				'--user-data-dir',
				userDataDir,
				'--force',
			],
			{
				encoding: 'utf-8',
				shell: process.platform === 'win32',
				stdio: 'pipe',
				timeout: 120_000,
			},
		);

		const installedExtensionDir = findInstalledExtensionDir(extensionsDir);
		const binaryPath = path.join(
			installedExtensionDir,
			'dist',
			'observer',
			getPackagedObserverBinaryName(),
		);
		assert.ok(fs.existsSync(binaryPath), `installed observer binary should exist at ${binaryPath}`);
		const weaverPath = path.join(
			installedExtensionDir,
			'dist',
			'observer',
			getPackagedWeaverBinaryName(),
		);
		assert.ok(fs.existsSync(weaverPath), `installed weaver runtime should exist at ${weaverPath}`);

		const port = await getAvailablePort();
		const otlpGrpcPort = await getAvailablePort();
		const otlpHttpPort = await getAvailablePort();
		const baseUrl = `http://127.0.0.1:${port}`;
		const otlpHttpUrl = `http://127.0.0.1:${otlpHttpPort}`;

		child = spawn(binaryPath, [], {
			env: {
				...process.env,
				PORT: String(port),
				OTLP_GRPC_PORT: String(otlpGrpcPort),
				OTLP_HTTP_PORT: String(otlpHttpPort),
			},
			stdio: 'pipe',
		});

		await waitForHttpOrExit(`${baseUrl}/api/health`, child, 10_000);

		const health = await requestJson(`${baseUrl}/api/health`, { method: 'GET' });
		assert.equal(health.statusCode, 200);
		assert.equal(health.body.kind, 'obstudio');
		assert.equal(health.body.endpoints.otlpHttp, otlpHttpUrl);
		assert.equal(health.body.endpoints.otlpGrpc, `127.0.0.1:${otlpGrpcPort}`);

		const clearResponse = await requestJson(`${baseUrl}/api/data`, { method: 'DELETE' });
		assert.equal(clearResponse.statusCode, 200);

		const tracePayload = JSON.stringify({
			resourceSpans: [
				{
					resource: {
						attributes: [
							{
								key: 'service.name',
								value: {
									stringValue: 'vsix-smoke-test',
								},
							},
						],
					},
					scopeSpans: [
						{
							scope: {
								name: 'vsix-smoke',
							},
							spans: [
								{
									traceId: '0af7651916cd43dd8448eb211c80319c',
									spanId: 'b7ad6b7169203331',
									name: 'installed-vsix-span',
									kind: 1,
									startTimeUnixNano: 1000000000000000000,
									endTimeUnixNano: 1000000001000000000,
									status: {
										code: 0,
									},
									attributes: [],
								},
							],
						},
					],
				},
			],
		});
		const ingest = await requestJson(`${otlpHttpUrl}/v1/traces`, {
			method: 'POST',
			headers: {
				'Content-Type': 'application/json',
			},
			body: tracePayload,
		});
		assert.equal(ingest.statusCode, 200);

		const stats = await waitFor(
			async () => {
				const response = await requestJson(`${baseUrl}/api/query/stats`, { method: 'GET' });
				assert.equal(response.statusCode, 200);
				return response.body as {
					spanCount?: number;
					traceCount?: number;
				};
			},
			(value) => value.spanCount === 1 && value.traceCount === 1,
			10_000,
		);
		assert.equal(stats.spanCount, 1);
		assert.equal(stats.traceCount, 1);

		const traces = await requestJson(`${baseUrl}/api/query/traces?limit=5`, { method: 'GET' });
		assert.equal(traces.statusCode, 200);
		assert.ok(Array.isArray(traces.body), 'trace query should return an array');
		assert.ok(
			traces.body.some((trace: { serviceName?: string; traceId?: string }) =>
				trace.traceId === '0af7651916cd43dd8448eb211c80319c' || trace.serviceName === 'vsix-smoke-test'),
			'installed VSIX should expose the ingested OTLP trace through the REST query API',
		);
	} finally {
		if (child) {
			await terminateChild(child);
		}
		if (tempRoot) {
			fs.rmSync(tempRoot, { force: true, recursive: true });
		}
		cleanup(context);
	}
});
