import * as assert from 'node:assert/strict';
import * as cp from 'node:child_process';
import * as fs from 'node:fs';
import * as http from 'node:http';
import * as net from 'node:net';
import * as os from 'node:os';
import * as path from 'node:path';
import { suite, test } from 'mocha';
import * as vscode from 'vscode';

type RuntimeState = {
	observerPort?: number;
	observerUrl?: string;
	panelHtml?: string;
	panelVisible: boolean;
	sharedMode: boolean;
	statusBarCommand?: string;
	statusBarPresent: boolean;
	statusBarText?: string;
	validatorSummaryUrl?: string;
};

type SharedObserverHandle = {
	baseUrl: string;
	dispose: () => Promise<void>;
};

type FileSnapshot = {
	content?: string;
	existed: boolean;
	filePath: string;
};

const sharedObserverStartupRetries = 5;

async function waitFor<T>(load: () => Promise<T>, ready: (value: T) => boolean, timeoutMs: number): Promise<T> {
	const deadline = Date.now() + timeoutMs;
	let last: T | undefined;
	let lastError: unknown;
	while (Date.now() < deadline) {
		try {
			last = await load();
			if (ready(last)) {
				return last;
			}
			lastError = undefined;
		} catch (error) {
			lastError = error;
		}
		await new Promise((resolve) => setTimeout(resolve, 200));
	}
	if (last !== undefined) {
		return last;
	}
	if (lastError instanceof Error) {
		throw lastError;
	}
	throw new Error('Timed out waiting for condition');
}

async function getExtension() {
	const extension = vscode.extensions.all.find((item) => item.packageJSON.name === 'observability-studio');
	assert.ok(extension, 'observability-studio extension should be installed in the test host');
	if (!extension.isActive) {
		await extension.activate();
	}
	return extension;
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

function isRetryableSharedObserverStartupFailure(stderr: string): boolean {
	return /\bEADDRINUSE\b/i.test(stderr) || /\baddress already in use\b/i.test(stderr);
}

async function terminateChild(child: cp.ChildProcess): Promise<void> {
	if (child.exitCode !== null || child.killed) {
		return;
	}
	child.kill();
	await Promise.race([
		new Promise<void>((resolve) => {
			child.once('exit', () => resolve());
		}),
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

async function waitForHttpOrExit(url: string, child: cp.ChildProcess, timeoutMs: number): Promise<void> {
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

async function startSharedObserver(binaryPath: string): Promise<SharedObserverHandle> {
	let lastFailure: Error | undefined;

	for (let attempt = 1; attempt <= sharedObserverStartupRetries; attempt += 1) {
		const port = await getAvailablePort();
		const grpcPort = await getAvailablePort();
		const httpPort = await getAvailablePort();
		const baseUrl = `http://127.0.0.1:${port}`;
		const child = cp.spawn(binaryPath, [], {
			env: {
				...process.env,
				HOST: '127.0.0.1',
				PORT: String(port),
				OTLP_GRPC_PORT: String(grpcPort),
				OTLP_HTTP_PORT: String(httpPort),
			},
			stdio: 'pipe',
		});
		let stderr = '';
		child.stderr?.on('data', (chunk: Buffer | string) => {
			stderr += chunk.toString();
		});

		try {
			await waitForHttpOrExit(baseUrl, child, 10_000);
			return {
				baseUrl,
				dispose: async () => {
					await terminateChild(child);
				},
			};
		} catch (error) {
			await terminateChild(child);
			lastFailure = new Error(
				`shared observer failed to start: ${error instanceof Error ? error.message : String(error)}\n${stderr}`,
			);
			if (attempt < sharedObserverStartupRetries && isRetryableSharedObserverStartupFailure(stderr)) {
				continue;
			}
			throw lastFailure;
		}
	}

	throw lastFailure ?? new Error('shared observer failed to start');
}

async function startSlowSharedObserver(delayMs: number): Promise<SharedObserverHandle> {
	const port = await getAvailablePort();
	const baseUrl = `http://127.0.0.1:${port}`;
	let healthRequestCount = 0;
	const server = http.createServer(async (request, response) => {
		if (request.url === '/api/health') {
			healthRequestCount += 1;
			if (healthRequestCount === 1) {
				await new Promise((resolve) => setTimeout(resolve, delayMs));
			}
			response.setHeader('Content-Type', 'application/json');
			response.end(JSON.stringify({
				apiVersion: 'v1',
				kind: 'obstudio',
			}));
			return;
		}

		response.setHeader('Content-Type', 'text/html; charset=utf-8');
		response.end('<!doctype html><title>Observer</title>');
	});

	await new Promise<void>((resolve, reject) => {
		server.once('error', reject);
		server.listen(port, '127.0.0.1', () => resolve());
	});

	return {
		baseUrl,
		dispose: async () => {
			await new Promise<void>((resolve, reject) => {
				server.close((error) => {
					if (error) {
						reject(error);
						return;
					}
					resolve();
				});
			});
		},
	};
}

async function startConflictingHttpService(port: number): Promise<SharedObserverHandle> {
	const server = http.createServer((_request, response) => {
		response.setHeader('Content-Type', 'text/plain; charset=utf-8');
		response.end('not-obstudio');
	});

	await new Promise<void>((resolve, reject) => {
		server.once('error', reject);
		server.listen(port, '127.0.0.1', () => resolve());
	});

	return {
		baseUrl: `http://127.0.0.1:${port}`,
		dispose: async () => {
			await new Promise<void>((resolve, reject) => {
				server.close((error) => {
					if (error) {
						reject(error);
						return;
					}
					resolve();
				});
			});
		},
	};
}

function readText(filePath: string): string {
	return fs.readFileSync(filePath, 'utf8');
}

async function waitForFileText(filePath: string): Promise<string> {
	return waitFor(
		async () => {
			if (!fs.existsSync(filePath)) {
				throw new Error(`Missing file ${filePath}`);
			}
			return readText(filePath);
		},
		(content) => content.length > 0,
		20_000,
	);
}

async function fetchJson(url: string): Promise<any> {
	return requestJson(url, 'GET');
}

async function assertCodexConfigured(filePaths: string[], mcpUrl: string): Promise<void> {
	for (const filePath of filePaths) {
		try {
			const content = await waitForFileText(filePath);
			assert.ok(content.includes('[mcp_servers.obstudio]'));
			assert.ok(content.includes(`url = "${mcpUrl}"`));
			return;
		} catch {
			// Try the next candidate path.
		}
	}

	throw new Error(`Missing Codex config in any expected path: ${filePaths.join(', ')}`);
}

async function assertCodexPreservesExistingConfig(filePaths: string[], mcpUrl: string): Promise<void> {
	for (const filePath of filePaths) {
		try {
			const content = await waitForFileText(filePath);
			assert.ok(content.includes(`url = "${mcpUrl}"`));
			assert.ok(content.includes(`model = "gpt-5.4"`));
			assert.ok(content.includes(`[mcp_servers.other]`));
			assert.ok(content.includes(`url = "http://example.com/mcp"`));
			assert.ok(content.includes(`[projects."/tmp/demo"]`));
			assert.ok(content.includes(`trust_level = "trusted"`));
			assert.equal((content.match(/\[mcp_servers\.obstudio\]/g) ?? []).length, 1);
			return;
		} catch {
			// Try the next candidate path.
		}
	}

	throw new Error(`Missing preserved Codex config in any expected path: ${filePaths.join(', ')}`);
}

async function assertJSONMCPConfigured(filePaths: string[], serverName: string, mcpUrl: string): Promise<void> {
	for (const filePath of filePaths) {
		try {
			const raw = JSON.parse(await waitForFileText(filePath));
			assert.equal(raw?.mcpServers?.[serverName]?.type, 'http');
			assert.equal(raw?.mcpServers?.[serverName]?.url, mcpUrl);
			return;
		} catch {
			// Try the next candidate path.
		}
	}

	throw new Error(`Missing JSON MCP config in any expected path: ${filePaths.join(', ')}`);
}

async function assertJSONMCPPreservesExistingServer(
	filePaths: string[],
	serverName: string,
	command: string,
	rootKey: string,
	rootValue: string,
): Promise<void> {
	for (const filePath of filePaths) {
		try {
			const raw = JSON.parse(await waitForFileText(filePath));
			assert.equal(raw?.mcpServers?.[serverName]?.command, command);
			assert.equal(raw?.[rootKey], rootValue);
			return;
		} catch {
			// Try the next candidate path.
		}
	}

	throw new Error(`Missing preserved JSON MCP config in any expected path: ${filePaths.join(', ')}`);
}

function snapshotFile(filePath: string): FileSnapshot {
	if (!filePath || !fs.existsSync(filePath)) {
		return { existed: false, filePath };
	}

	return {
		content: readText(filePath),
		existed: true,
		filePath,
	};
}

function restoreSnapshot(snapshot: FileSnapshot): void {
	if (!snapshot.filePath) {
		return;
	}

	if (snapshot.existed) {
		fs.mkdirSync(path.dirname(snapshot.filePath), { recursive: true });
		fs.writeFileSync(snapshot.filePath, snapshot.content ?? '', 'utf8');
		return;
	}

	fs.rmSync(snapshot.filePath, { force: true });
}

function cleanupTempDir(dirPath: string): void {
	const retryableCodes = new Set(['EBUSY', 'ENOTEMPTY', 'EPERM', 'EEXIST']);
	const sleep = (ms: number) => {
		Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, ms);
	};

	for (let attempt = 0; attempt < 8; attempt += 1) {
		try {
			fs.rmSync(dirPath, {
				force: true,
				maxRetries: 10,
				recursive: true,
				retryDelay: 100,
			});
			return;
		} catch (error) {
			const code = (error as NodeJS.ErrnoException | undefined)?.code;
			if (!code || !retryableCodes.has(code)) {
				throw error;
			}
			sleep(100 * (attempt + 1));
		}
	}

	try {
		fs.rmSync(dirPath, {
			force: true,
			maxRetries: 20,
			recursive: true,
			retryDelay: 150,
		});
		return;
	} catch {}

	if (process.platform !== 'win32') {
		try {
			cp.execFileSync('rm', ['-rf', dirPath], { stdio: 'ignore' });
		} catch {}
	}
}

async function postJson(url: string): Promise<any> {
	return requestJson(url, 'POST');
}

async function requestJson(url: string, method: 'GET' | 'POST'): Promise<any> {
	return new Promise((resolve, reject) => {
		const request = http.request(url, { method }, (response) => {
			let body = '';
			response.setEncoding('utf8');
			response.on('data', (chunk) => {
				body += chunk;
			});
			response.on('end', () => {
				try {
					resolve(JSON.parse(body));
				} catch (error) {
					reject(error);
				}
			});
		});
		request.on('error', reject);
		request.end();
	});
}

suite('VS Code Host', () => {
	test('shared observer startup retries port collisions', () => {
		assert.equal(
			isRetryableSharedObserverStartupFailure(
				'failed to start OTLP receiver: listen tcp 127.0.0.1:45621: bind: address already in use',
			),
			true,
		);
		assert.equal(
			isRetryableSharedObserverStartupFailure('spawn failed: EADDRINUSE'),
			true,
		);
		assert.equal(
			isRetryableSharedObserverStartupFailure('shared observer failed to start: connect ECONNREFUSED 127.0.0.1:36715'),
			false,
		);
	});

	test('fresh activation shows the Observer status bar item and wires it to the status menu', async function () {
		this.timeout(30_000);

		await getExtension();

		const state = await waitFor(
			() => Promise.resolve(vscode.commands.executeCommand<RuntimeState>('observability-studio.internal.getRuntimeState')),
			(value) => Boolean(
				value
				&& value.statusBarPresent
				&& value.statusBarCommand === 'observability-studio.statusMenu'
				&& value.statusBarText?.includes('Observer'),
			),
			20_000,
		);

		assert.equal(state.statusBarPresent, true);
		assert.equal(state.statusBarCommand, 'observability-studio.statusMenu');
		assert.match(state.statusBarText ?? '', /Observer/);
	});

	test('managed observer uses the configured port across restarts', async function () {
		this.timeout(30_000);
		if (process.platform === 'darwin') {
			this.skip();
		}

		await getExtension();
		const managedPort = await getAvailablePort();
		const config = vscode.workspace.getConfiguration('observability-studio');

		try {
			await config.update('sharedObserverUrl', '', vscode.ConfigurationTarget.Global);
			await config.update('managedObserverPort', managedPort, vscode.ConfigurationTarget.Global);
			await vscode.commands.executeCommand('observability-studio.stopObserver');

			await vscode.commands.executeCommand('observability-studio.startObserver');
			const firstState = await waitFor(
				() => Promise.resolve(vscode.commands.executeCommand<RuntimeState>('observability-studio.internal.getRuntimeState')),
				(value) => Boolean(value?.observerUrl === `http://127.0.0.1:${managedPort}`),
				20_000,
			);
			assert.equal(firstState.observerUrl, `http://127.0.0.1:${managedPort}`);
			const firstHealth = await fetchJson(`${firstState.observerUrl}/api/health`);
			assert.equal(firstHealth.kind, 'obstudio');

			await vscode.commands.executeCommand('observability-studio.restartObserver');
			const secondState = await waitFor(
				() => Promise.resolve(vscode.commands.executeCommand<RuntimeState>('observability-studio.internal.getRuntimeState')),
				(value) => Boolean(value?.observerUrl === `http://127.0.0.1:${managedPort}`),
				20_000,
			);
			assert.equal(secondState.observerUrl, `http://127.0.0.1:${managedPort}`);
			const secondHealth = await fetchJson(`${secondState.observerUrl}/api/health`);
			assert.equal(secondHealth.kind, 'obstudio');
		} finally {
			await vscode.commands.executeCommand('observability-studio.stopObserver');
			await config.update('managedObserverPort', undefined, vscode.ConfigurationTarget.Global);
		}
	});

	test('changing shared observer URL re-prompts detected agents to update their MCP endpoint', async function () {
		this.timeout(30_000);

		const tempHome = fs.mkdtempSync(path.join(os.tmpdir(), 'obstudio-home-'));
		const originalHome = process.env.HOME;
		const originalUserProfile = process.env.USERPROFILE;
		const extension = await getExtension();
		const firstSharedObserver = await startSharedObserver(path.join(extension.extensionPath, 'dist', 'observer', 'obstudio'));
		const secondSharedObserver = await startSharedObserver(path.join(extension.extensionPath, 'dist', 'observer', 'obstudio'));
		const config = vscode.workspace.getConfiguration('observability-studio');
		const firstSharedMcpUrl = `${firstSharedObserver.baseUrl}/mcp`;
		const secondSharedMcpUrl = `${secondSharedObserver.baseUrl}/mcp`;
		const codexConfigPath = path.join(tempHome, '.codex', 'config.toml');

		process.env.HOME = tempHome;
		process.env.USERPROFILE = tempHome;

		try {
			await config.update('sharedObserverUrl', firstSharedMcpUrl, vscode.ConfigurationTarget.Global);
			await waitFor(
				() => Promise.resolve(vscode.commands.executeCommand<RuntimeState>('observability-studio.internal.getRuntimeState')),
				(value) => Boolean(value && value.sharedMode && value.observerUrl === firstSharedObserver.baseUrl),
				20_000,
			);

			fs.mkdirSync(path.join(tempHome, '.codex'), { recursive: true });
			await vscode.commands.executeCommand('observability-studio.configureCodexMCP');
			await assertCodexConfigured([codexConfigPath], firstSharedMcpUrl);

			await vscode.commands.executeCommand('observability-studio.internal.resetAgentIntegrationPromptState');
			await config.update('sharedObserverUrl', secondSharedMcpUrl, vscode.ConfigurationTarget.Global);
			await waitFor(
				() => Promise.resolve(vscode.commands.executeCommand<RuntimeState>('observability-studio.internal.getRuntimeState')),
				(value) => Boolean(value && value.sharedMode && value.observerUrl === secondSharedObserver.baseUrl),
				20_000,
			);

			const prompts = await waitFor(
				() => Promise.resolve(vscode.commands.executeCommand<Array<{ detail?: string; message: string }>>(
					'observability-studio.internal.getAgentIntegrationPrompts',
				)),
				(value) => Array.isArray(value) && value.some((item) =>
					item.message.includes('Enable Codex integration for Splunk Observability Studio?')
					&& item.detail?.includes(secondSharedMcpUrl)
				),
				20_000,
			);

			const prompt = prompts.find((item) => item.message.includes('Enable Codex integration for Splunk Observability Studio?'));
			assert.ok(prompt, 'expected the Codex integration prompt after changing the shared Observer URL');
			assert.equal(prompt?.detail, `Install bundled skills and configure Codex to use the local Observer at ${secondSharedMcpUrl}.`);
		} finally {
			await config.update('sharedObserverUrl', '', vscode.ConfigurationTarget.Global);
			await firstSharedObserver.dispose();
			await secondSharedObserver.dispose();
			process.env.HOME = originalHome;
			process.env.USERPROFILE = originalUserProfile;
			cleanupTempDir(tempHome);
		}
	});

	test('managed observer does not fall back when the configured port is occupied', async function () {
		this.timeout(30_000);

		await getExtension();
		const conflictPort = await getAvailablePort();
		const conflictService = await startConflictingHttpService(conflictPort);
		const config = vscode.workspace.getConfiguration('observability-studio');

		try {
			await config.update('sharedObserverUrl', '', vscode.ConfigurationTarget.Global);
			await config.update('managedObserverPort', conflictPort, vscode.ConfigurationTarget.Global);
			await vscode.commands.executeCommand('observability-studio.stopObserver');

			await vscode.commands.executeCommand('observability-studio.openObserver');
			const failedState = await waitFor(
				() => Promise.resolve(vscode.commands.executeCommand<RuntimeState>('observability-studio.internal.getRuntimeState')),
				(value) => {
					if (!value || value.observerPort !== undefined || value.observerUrl !== undefined) {
						return false;
					}
					return typeof value.panelHtml === 'string'
						&& value.panelHtml.includes('Observer could not start')
						&& value.panelHtml.includes(`http://127.0.0.1:${conflictPort}`)
						&& value.panelHtml.includes('observability-studio.managedObserverPort');
				},
				20_000,
			);
			assert.equal(failedState.sharedMode, false);
		} finally {
			await vscode.commands.executeCommand('observability-studio.stopObserver');
			await config.update('managedObserverPort', undefined, vscode.ConfigurationTarget.Global);
			await conflictService.dispose();
		}
	});

	test('managed observer rejects ports reserved for fixed OTLP listeners', async function () {
		this.timeout(30_000);

		await getExtension();
		const config = vscode.workspace.getConfiguration('observability-studio');

		try {
			await config.update('sharedObserverUrl', '', vscode.ConfigurationTarget.Global);
			await config.update('managedObserverPort', 4318, vscode.ConfigurationTarget.Global);
			await vscode.commands.executeCommand('observability-studio.stopObserver');

			await vscode.commands.executeCommand('observability-studio.openObserver');
			const failedState = await waitFor(
				() => Promise.resolve(vscode.commands.executeCommand<RuntimeState>('observability-studio.internal.getRuntimeState')),
				(value) => {
					if (!value || value.observerPort !== undefined || value.observerUrl !== undefined) {
						return false;
					}
					return typeof value.panelHtml === 'string'
						&& value.panelHtml.includes('Observer could not start')
						&& value.panelHtml.includes('observability-studio.managedObserverPort')
						&& value.panelHtml.includes('4318')
						&& value.panelHtml.includes('OTLP/HTTP');
				},
				20_000,
			);
			assert.equal(failedState.sharedMode, false);
		} finally {
			await vscode.commands.executeCommand('observability-studio.stopObserver');
			await config.update('managedObserverPort', undefined, vscode.ConfigurationTarget.Global);
		}
	});

	test('openObserver reuses configured shared backend and configures MCP targets', async function () {
		this.timeout(30_000);

		const extension = await getExtension();
		const sharedObserver = await startSharedObserver(path.join(extension.extensionPath, 'dist', 'observer', 'obstudio'));
		const config = vscode.workspace.getConfiguration('observability-studio');
		const sharedMcpUrl = `${sharedObserver.baseUrl}/mcp`;
		const tempHome = fs.mkdtempSync(path.join(os.tmpdir(), 'obstudio-home-'));
		const originalHome = process.env.HOME;
		const originalUserProfile = process.env.USERPROFILE;
		const codexConfigPath = path.join(tempHome, '.codex', 'config.toml');
		const claudeConfigPath = path.join(tempHome, '.claude.json');
		const cursorConfigPath = path.join(tempHome, '.cursor', 'mcp.json');
		const originalCodexConfigPath = originalHome ? path.join(originalHome, '.codex', 'config.toml') : '';
		const originalClaudeConfigPath = originalHome ? path.join(originalHome, '.claude.json') : '';
		const originalCursorConfigPath = originalHome ? path.join(originalHome, '.cursor', 'mcp.json') : '';
		const originalSnapshots = [
			snapshotFile(originalCodexConfigPath),
			snapshotFile(originalClaudeConfigPath),
			snapshotFile(originalCursorConfigPath),
		];

		process.env.HOME = tempHome;
		process.env.USERPROFILE = tempHome;

		try {
			await config.update('sharedObserverUrl', sharedMcpUrl, vscode.ConfigurationTarget.Global);

			await waitFor(
				() => Promise.resolve(vscode.commands.executeCommand<RuntimeState>('observability-studio.internal.getRuntimeState')),
				(value) => {
					if (!value) {
						return false;
					}
					return value.sharedMode && value.observerUrl === sharedObserver.baseUrl;
				},
				20_000,
			);

			await vscode.commands.executeCommand('observability-studio.openObserver');

			const state = await waitFor(
				() => Promise.resolve(vscode.commands.executeCommand<RuntimeState>('observability-studio.internal.getRuntimeState')),
				(value) => {
					if (!value) {
						return false;
					}
					return value.panelVisible
						&& value.sharedMode
						&& value.observerUrl === sharedObserver.baseUrl
						&& typeof value.panelHtml === 'string'
						&& value.panelHtml.includes(sharedObserver.baseUrl);
				},
				20_000,
			);

			assert.equal(state.panelVisible, true);
			assert.equal(state.sharedMode, true);
			assert.equal(state.observerUrl, sharedObserver.baseUrl);
			assert.ok(state.panelHtml?.includes('<iframe '), 'observer panel should embed the Observer UI in an iframe');
			assert.ok(
				state.panelHtml?.includes(sharedObserver.baseUrl),
				'observer panel iframe should point at the shared backend',
			);

			await vscode.commands.executeCommand('observability-studio.configureCodexMCP');
			await vscode.commands.executeCommand('observability-studio.configureClaudeCodeMCP');
			await vscode.commands.executeCommand('observability-studio.configureCursorMCP');

			await assertCodexConfigured([codexConfigPath, originalCodexConfigPath], sharedMcpUrl);
			await assertJSONMCPConfigured([claudeConfigPath, originalClaudeConfigPath], 'obstudio', sharedMcpUrl);
			await assertJSONMCPConfigured([cursorConfigPath, originalCursorConfigPath], 'obstudio', sharedMcpUrl);
		} finally {
			await config.update('sharedObserverUrl', '', vscode.ConfigurationTarget.Global);
			await sharedObserver.dispose();
			process.env.HOME = originalHome;
			process.env.USERPROFILE = originalUserProfile;
			for (const snapshot of originalSnapshots) {
				restoreSnapshot(snapshot);
			}
			cleanupTempDir(tempHome);
		}
	});

	test('configuring JSON MCP targets appends obstudio without overwriting existing servers', async function () {
		this.timeout(30_000);

		const extension = await getExtension();
		const sharedObserver = await startSharedObserver(path.join(extension.extensionPath, 'dist', 'observer', 'obstudio'));
		const config = vscode.workspace.getConfiguration('observability-studio');
		const sharedMcpUrl = `${sharedObserver.baseUrl}/mcp`;
		const tempHome = fs.mkdtempSync(path.join(os.tmpdir(), 'obstudio-home-'));
		const originalHome = process.env.HOME;
		const originalUserProfile = process.env.USERPROFILE;
		const claudeConfigPath = path.join(tempHome, '.claude.json');
		const cursorConfigPath = path.join(tempHome, '.cursor', 'mcp.json');
		const originalClaudeConfigPath = originalHome ? path.join(originalHome, '.claude.json') : '';
		const originalCursorConfigPath = originalHome ? path.join(originalHome, '.cursor', 'mcp.json') : '';
		const originalSnapshots = [
			snapshotFile(originalClaudeConfigPath),
			snapshotFile(originalCursorConfigPath),
		];

		process.env.HOME = tempHome;
		process.env.USERPROFILE = tempHome;

		try {
			fs.mkdirSync(path.dirname(cursorConfigPath), { recursive: true });
			fs.writeFileSync(
				claudeConfigPath,
				JSON.stringify({
					editor: 'claude',
					mcpServers: {
						obstudio: {
							type: 'http',
							url: 'http://127.0.0.1:3999/mcp',
						},
						existingClaude: {
							command: 'existing-claude',
							args: ['--serve'],
						},
					},
				}, null, 2),
			);
			fs.writeFileSync(
				cursorConfigPath,
				JSON.stringify({
					theme: 'dark',
					mcpServers: {
						obstudio: {
							type: 'http',
							url: 'http://127.0.0.1:4999/mcp',
						},
						existingCursor: {
							command: 'existing-cursor',
							args: ['--serve'],
						},
					},
				}, null, 2),
			);

			await config.update('sharedObserverUrl', sharedMcpUrl, vscode.ConfigurationTarget.Global);
			await waitFor(
				() => Promise.resolve(vscode.commands.executeCommand<RuntimeState>('observability-studio.internal.getRuntimeState')),
				(value) => Boolean(value && value.sharedMode && value.observerUrl === sharedObserver.baseUrl),
				20_000,
			);

			await vscode.commands.executeCommand('observability-studio.configureClaudeCodeMCP');
			await vscode.commands.executeCommand('observability-studio.configureCursorMCP');

			await assertJSONMCPConfigured([claudeConfigPath, originalClaudeConfigPath], 'obstudio', sharedMcpUrl);
			await assertJSONMCPConfigured([cursorConfigPath, originalCursorConfigPath], 'obstudio', sharedMcpUrl);
			await assertJSONMCPPreservesExistingServer(
				[claudeConfigPath, originalClaudeConfigPath],
				'existingClaude',
				'existing-claude',
				'editor',
				'claude',
			);
			await assertJSONMCPPreservesExistingServer(
				[cursorConfigPath, originalCursorConfigPath],
				'existingCursor',
				'existing-cursor',
				'theme',
				'dark',
			);
		} finally {
			await config.update('sharedObserverUrl', '', vscode.ConfigurationTarget.Global);
			await sharedObserver.dispose();
			process.env.HOME = originalHome;
			process.env.USERPROFILE = originalUserProfile;
			for (const snapshot of originalSnapshots) {
				restoreSnapshot(snapshot);
			}
			cleanupTempDir(tempHome);
		}
	});

	test('detected agent integration preserves dummy MCP config across Codex, Claude, and Cursor', async function () {
		this.timeout(30_000);

		const extension = await getExtension();
		const sharedObserver = await startSharedObserver(path.join(extension.extensionPath, 'dist', 'observer', 'obstudio'));
		const config = vscode.workspace.getConfiguration('observability-studio');
		const sharedMcpUrl = `${sharedObserver.baseUrl}/mcp`;
		const tempHome = fs.mkdtempSync(path.join(os.tmpdir(), 'obstudio-home-'));
		const originalHome = process.env.HOME;
		const originalUserProfile = process.env.USERPROFILE;
		const codexConfigPath = path.join(tempHome, '.codex', 'config.toml');
		const claudeConfigPath = path.join(tempHome, '.claude.json');
		const cursorConfigPath = path.join(tempHome, '.cursor', 'mcp.json');
		const originalCodexConfigPath = originalHome ? path.join(originalHome, '.codex', 'config.toml') : '';
		const originalClaudeConfigPath = originalHome ? path.join(originalHome, '.claude.json') : '';
		const originalCursorConfigPath = originalHome ? path.join(originalHome, '.cursor', 'mcp.json') : '';
		const originalSnapshots = [
			snapshotFile(originalCodexConfigPath),
			snapshotFile(originalClaudeConfigPath),
			snapshotFile(originalCursorConfigPath),
		];

		process.env.HOME = tempHome;
		process.env.USERPROFILE = tempHome;

		try {
			fs.mkdirSync(path.join(tempHome, '.codex'), { recursive: true });
			fs.mkdirSync(path.join(tempHome, '.cursor'), { recursive: true });
			fs.writeFileSync(
				codexConfigPath,
				[
					`model = "gpt-5.4"`,
					``,
					`[mcp_servers.obstudio]`,
					`url = "http://127.0.0.1:3999/mcp"`,
					``,
					`[mcp_servers.other]`,
					`url = "http://example.com/mcp"`,
					``,
					`[projects."/tmp/demo"]`,
					`trust_level = "trusted"`,
					``,
				].join('\n'),
				'utf8',
			);
			fs.writeFileSync(
				claudeConfigPath,
				JSON.stringify({
					editor: 'claude',
					mcpServers: {
						obstudio: {
							type: 'http',
							url: 'http://127.0.0.1:3999/mcp',
						},
						existingClaude: {
							command: 'existing-claude',
							args: ['--serve'],
						},
					},
				}, null, 2),
			);
			fs.writeFileSync(
				cursorConfigPath,
				JSON.stringify({
					theme: 'dark',
					mcpServers: {
						obstudio: {
							type: 'http',
							url: 'http://127.0.0.1:4999/mcp',
						},
						existingCursor: {
							command: 'existing-cursor',
							args: ['--serve'],
						},
					},
				}, null, 2),
			);

			await config.update('sharedObserverUrl', sharedMcpUrl, vscode.ConfigurationTarget.Global);
			await waitFor(
				() => Promise.resolve(vscode.commands.executeCommand<RuntimeState>('observability-studio.internal.getRuntimeState')),
				(value) => Boolean(value && value.sharedMode && value.observerUrl === sharedObserver.baseUrl),
				20_000,
			);

			const configured = await vscode.commands.executeCommand<string[]>(
				'observability-studio.internal.configureDetectedAgentIntegrations',
			);
			assert.deepEqual(configured, ['Codex', 'Claude Code', 'Cursor']);

			await assertCodexPreservesExistingConfig([codexConfigPath, originalCodexConfigPath], sharedMcpUrl);
			await assertJSONMCPConfigured([claudeConfigPath, originalClaudeConfigPath], 'obstudio', sharedMcpUrl);
			await assertJSONMCPConfigured([cursorConfigPath, originalCursorConfigPath], 'obstudio', sharedMcpUrl);
			await assertJSONMCPPreservesExistingServer(
				[claudeConfigPath, originalClaudeConfigPath],
				'existingClaude',
				'existing-claude',
				'editor',
				'claude',
			);
			await assertJSONMCPPreservesExistingServer(
				[cursorConfigPath, originalCursorConfigPath],
				'existingCursor',
				'existing-cursor',
				'theme',
				'dark',
			);
		} finally {
			await config.update('sharedObserverUrl', '', vscode.ConfigurationTarget.Global);
			await sharedObserver.dispose();
			process.env.HOME = originalHome;
			process.env.USERPROFILE = originalUserProfile;
			for (const snapshot of originalSnapshots) {
				restoreSnapshot(snapshot);
			}
			cleanupTempDir(tempHome);
		}
	});

	test('detected agent installs can be enabled together through the automatic integration path', async function () {
		this.timeout(30_000);

		const tempHome = fs.mkdtempSync(path.join(os.tmpdir(), 'obstudio-home-'));
		const originalHome = process.env.HOME;
		const originalUserProfile = process.env.USERPROFILE;
		const codexConfigPath = path.join(tempHome, '.codex', 'config.toml');
		const codexSkillsDir = path.join(tempHome, '.codex', 'skills');
		const cursorConfigPath = path.join(tempHome, '.cursor', 'mcp.json');
		const cursorSkillsDir = path.join(tempHome, '.cursor', 'skills');
		const originalCodexConfigPath = originalHome ? path.join(originalHome, '.codex', 'config.toml') : '';
		const originalCursorConfigPath = originalHome ? path.join(originalHome, '.cursor', 'mcp.json') : '';
		const originalSnapshots = [
			snapshotFile(originalCodexConfigPath),
			snapshotFile(originalCursorConfigPath),
		];

		process.env.HOME = tempHome;
		process.env.USERPROFILE = tempHome;

		const extension = await getExtension();
		const sharedObserver = await startSharedObserver(path.join(extension.extensionPath, 'dist', 'observer', 'obstudio'));
		const config = vscode.workspace.getConfiguration('observability-studio');
		const sharedMcpUrl = `${sharedObserver.baseUrl}/mcp`;

		try {
			await config.update('sharedObserverUrl', sharedMcpUrl, vscode.ConfigurationTarget.Global);
			await waitFor(
				() => Promise.resolve(vscode.commands.executeCommand<RuntimeState>('observability-studio.internal.getRuntimeState')),
				(value) => Boolean(value && value.sharedMode && value.observerUrl === sharedObserver.baseUrl),
				20_000,
			);

			fs.mkdirSync(path.join(tempHome, '.codex'), { recursive: true });
			fs.mkdirSync(path.join(tempHome, '.cursor'), { recursive: true });
			fs.writeFileSync(
				cursorConfigPath,
				JSON.stringify({
					mcpServers: {
						obstudio: {
							type: 'http',
							url: 'http://127.0.0.1:4999/mcp',
						},
					},
				}, null, 2),
			);
			const configured = await vscode.commands.executeCommand<string[]>(
				'observability-studio.internal.configureDetectedAgentIntegrations',
			);
			assert.deepEqual(configured, ['Codex', 'Cursor']);

			await assertCodexConfigured([codexConfigPath, originalCodexConfigPath], sharedMcpUrl);
			await assertJSONMCPConfigured([cursorConfigPath, originalCursorConfigPath], 'obstudio', sharedMcpUrl);
			assert.equal(fs.existsSync(path.join(codexSkillsDir, 'obstudio', 'obstudio')), true);
			assert.equal(fs.existsSync(path.join(codexSkillsDir, 'obstudio', 'otel-audit', 'SKILL.md')), true);
			assert.equal(fs.existsSync(path.join(codexSkillsDir, 'otel-audit', 'SKILL.md')), true);
			assert.equal(fs.existsSync(path.join(cursorSkillsDir, 'obstudio', 'obstudio')), true);
			assert.equal(fs.existsSync(path.join(cursorSkillsDir, 'obstudio', 'otel-audit', 'SKILL.md')), true);
			assert.equal(fs.existsSync(path.join(cursorSkillsDir, 'otel-audit', 'SKILL.md')), true);
		} finally {
			await config.update('sharedObserverUrl', '', vscode.ConfigurationTarget.Global);
			await sharedObserver.dispose();
			process.env.HOME = originalHome;
			process.env.USERPROFILE = originalUserProfile;
			for (const snapshot of originalSnapshots) {
				restoreSnapshot(snapshot);
			}
			cleanupTempDir(tempHome);
		}
	});

	test('detected Codex installs show a VS Code enable integration prompt', async function () {
		this.timeout(30_000);

		const tempHome = fs.mkdtempSync(path.join(os.tmpdir(), 'obstudio-home-'));
		const originalHome = process.env.HOME;
		const originalUserProfile = process.env.USERPROFILE;
		const extension = await getExtension();
		const sharedObserver = await startSharedObserver(path.join(extension.extensionPath, 'dist', 'observer', 'obstudio'));
		const config = vscode.workspace.getConfiguration('observability-studio');
		const sharedMcpUrl = `${sharedObserver.baseUrl}/mcp`;

		process.env.HOME = tempHome;
		process.env.USERPROFILE = tempHome;

		try {
			fs.mkdirSync(path.join(tempHome, '.codex'), { recursive: true });
			await vscode.commands.executeCommand('observability-studio.internal.resetAgentIntegrationPromptState');
			await config.update('sharedObserverUrl', sharedMcpUrl, vscode.ConfigurationTarget.Global);
			await vscode.commands.executeCommand('observability-studio.stopObserver');
			await vscode.commands.executeCommand('observability-studio.startObserver');
			const prompts = await waitFor(
				() => Promise.resolve(vscode.commands.executeCommand<Array<{ detail?: string; message: string }>>(
					'observability-studio.internal.getAgentIntegrationPrompts',
				)),
				(value) => Array.isArray(value) && value.some((item) => item.message.includes('Enable Codex integration for Splunk Observability Studio?')),
				20_000,
			);

			const prompt = prompts.find((item) => item.message.includes('Enable Codex integration for Splunk Observability Studio?'));
			assert.ok(prompt, 'expected the Codex integration prompt to be shown');
			assert.equal(prompt?.detail, `Install bundled skills and configure Codex to use the local Observer at ${sharedMcpUrl}.`);
		} finally {
			await config.update('sharedObserverUrl', '', vscode.ConfigurationTarget.Global);
			await sharedObserver.dispose();
			process.env.HOME = originalHome;
			process.env.USERPROFILE = originalUserProfile;
			cleanupTempDir(tempHome);
		}
	});

	test('matching Codex, Claude Code, and Cursor MCP config does not prompt when bundled skills are present', async function () {
		this.timeout(30_000);

		const tempHome = fs.mkdtempSync(path.join(os.tmpdir(), 'obstudio-home-'));
		const originalHome = process.env.HOME;
		const originalUserProfile = process.env.USERPROFILE;
		const extension = await getExtension();
		const sharedObserver = await startSharedObserver(path.join(extension.extensionPath, 'dist', 'observer', 'obstudio'));
		const config = vscode.workspace.getConfiguration('observability-studio');
		const sharedMcpUrl = `${sharedObserver.baseUrl}/mcp`;

		process.env.HOME = tempHome;
		process.env.USERPROFILE = tempHome;

		try {
			fs.mkdirSync(path.join(tempHome, '.codex', 'skills', 'obstudio', 'otel-instrument'), { recursive: true });
			fs.mkdirSync(path.join(tempHome, '.claude', 'skills', 'obstudio', 'otel-instrument'), { recursive: true });
			fs.mkdirSync(path.join(tempHome, '.cursor', 'skills', 'obstudio', 'otel-instrument'), { recursive: true });
			fs.writeFileSync(path.join(tempHome, '.codex', 'skills', 'obstudio', 'otel-instrument', 'SKILL.md'), '# Codex skill\n', 'utf8');
			fs.writeFileSync(path.join(tempHome, '.claude', 'skills', 'obstudio', 'otel-instrument', 'SKILL.md'), '# Claude skill\n', 'utf8');
			fs.writeFileSync(path.join(tempHome, '.cursor', 'skills', 'obstudio', 'otel-instrument', 'SKILL.md'), '# Cursor skill\n', 'utf8');
			fs.symlinkSync(path.join('obstudio', 'otel-instrument'), path.join(tempHome, '.codex', 'skills', 'otel-instrument'));
			fs.symlinkSync(path.join('obstudio', 'otel-instrument'), path.join(tempHome, '.claude', 'skills', 'otel-instrument'));
			fs.mkdirSync(path.join(tempHome, '.cursor'), { recursive: true });
			fs.symlinkSync(path.join('obstudio', 'otel-instrument'), path.join(tempHome, '.cursor', 'skills', 'otel-instrument'));
			fs.writeFileSync(path.join(tempHome, '.codex', 'config.toml'), `model = "gpt-5.4"\n\n[mcp_servers.obstudio]\nurl = "${sharedMcpUrl}"\n`, 'utf8');
			fs.writeFileSync(
				path.join(tempHome, '.claude.json'),
				JSON.stringify({
					mcpServers: {
						obstudio: { type: 'http', url: sharedMcpUrl },
					},
				}, null, 2),
				'utf8',
			);
			fs.writeFileSync(
				path.join(tempHome, '.cursor', 'mcp.json'),
				JSON.stringify({
					mcpServers: {
						obstudio: { type: 'http', url: sharedMcpUrl },
					},
				}, null, 2),
				'utf8',
			);

			await vscode.commands.executeCommand('observability-studio.internal.resetAgentIntegrationPromptState');
			await config.update('sharedObserverUrl', sharedMcpUrl, vscode.ConfigurationTarget.Global);
			await vscode.commands.executeCommand('observability-studio.stopObserver');
			await vscode.commands.executeCommand('observability-studio.startObserver');
			await new Promise((resolve) => setTimeout(resolve, 1_000));

			const prompts = await vscode.commands.executeCommand<Array<{ detail?: string; message: string }>>(
				'observability-studio.internal.getAgentIntegrationPrompts',
			);
			assert.ok(Array.isArray(prompts), 'expected prompt history to be available');
			assert.equal(
				prompts.some((item) => item.message.includes('Enable detected agent integrations for Splunk Observability Studio?')),
				false,
			);
		} finally {
			await config.update('sharedObserverUrl', '', vscode.ConfigurationTarget.Global);
			await sharedObserver.dispose();
			process.env.HOME = originalHome;
			process.env.USERPROFILE = originalUserProfile;
			cleanupTempDir(tempHome);
		}
	});

	test('re-enabling integrations rewrites obstudio without duplicating MCP entries', async function () {
		this.timeout(30_000);

		const tempHome = fs.mkdtempSync(path.join(os.tmpdir(), 'obstudio-home-'));
		const originalHome = process.env.HOME;
		const originalUserProfile = process.env.USERPROFILE;
		const codexConfigPath = path.join(tempHome, '.codex', 'config.toml');
		const cursorConfigPath = path.join(tempHome, '.cursor', 'mcp.json');
		const extension = await getExtension();
		const sharedObserver = await startSharedObserver(path.join(extension.extensionPath, 'dist', 'observer', 'obstudio'));
		const config = vscode.workspace.getConfiguration('observability-studio');
		const sharedMcpUrl = `${sharedObserver.baseUrl}/mcp`;

		process.env.HOME = tempHome;
		process.env.USERPROFILE = tempHome;

		try {
			fs.mkdirSync(path.join(tempHome, '.codex'), { recursive: true });
			fs.mkdirSync(path.join(tempHome, '.cursor'), { recursive: true });

			await config.update('sharedObserverUrl', sharedMcpUrl, vscode.ConfigurationTarget.Global);
			await waitFor(
				() => Promise.resolve(vscode.commands.executeCommand<RuntimeState>('observability-studio.internal.getRuntimeState')),
				(value) => Boolean(value && value.sharedMode && value.observerUrl === sharedObserver.baseUrl),
				20_000,
			);

			await vscode.commands.executeCommand('observability-studio.configureCodexMCP');
			await vscode.commands.executeCommand('observability-studio.configureCursorMCP');
			await vscode.commands.executeCommand('observability-studio.configureCodexMCP');
			await vscode.commands.executeCommand('observability-studio.configureCursorMCP');

			const codexConfig = await waitForFileText(codexConfigPath);
			assert.equal((codexConfig.match(/\[mcp_servers\.obstudio\]/g) ?? []).length, 1);
			assert.equal((codexConfig.match(/# BEGIN OBSTUDIO MCP CONFIG/g) ?? []).length, 1);
			assert.ok(codexConfig.includes(`url = "${sharedMcpUrl}"`));

			const cursorConfig = JSON.parse(await waitForFileText(cursorConfigPath));
			assert.equal(Object.keys(cursorConfig.mcpServers).filter((name) => name === 'obstudio').length, 1);
			assert.equal(cursorConfig.mcpServers.obstudio.type, 'http');
			assert.equal(cursorConfig.mcpServers.obstudio.url, sharedMcpUrl);
		} finally {
			await config.update('sharedObserverUrl', '', vscode.ConfigurationTarget.Global);
			await sharedObserver.dispose();
			process.env.HOME = originalHome;
			process.env.USERPROFILE = originalUserProfile;
			cleanupTempDir(tempHome);
		}
	});

	test('openObserver exposes validator summary for a shared backend', async function () {
		this.timeout(30_000);

		const extension = await getExtension();
		const sharedObserver = await startSharedObserver(path.join(extension.extensionPath, 'dist', 'observer', 'obstudio'));
		const config = vscode.workspace.getConfiguration('observability-studio');

		try {
			await config.update('sharedObserverUrl', `${sharedObserver.baseUrl}/mcp`, vscode.ConfigurationTarget.Global);
			await vscode.commands.executeCommand('observability-studio.openObserver');

			const state = await waitFor(
				() => Promise.resolve(vscode.commands.executeCommand<RuntimeState>('observability-studio.internal.getRuntimeState')),
				(value) => {
					if (!value) {
						return false;
					}
					return value.panelVisible
						&& value.sharedMode
						&& value.observerUrl === sharedObserver.baseUrl
						&& typeof value.panelHtml === 'string'
						&& value.panelHtml.includes(sharedObserver.baseUrl)
						&& typeof value.validatorSummaryUrl === 'string';
				},
				20_000,
			);

			assert.ok(state.panelHtml?.includes('<iframe '), 'observer panel should embed the Observer UI in an iframe');
			assert.ok(
				state.panelHtml?.includes(sharedObserver.baseUrl),
				'observer panel iframe should point at the shared backend',
			);

			const idleSummary = await waitFor(
				() => fetchJson(state.validatorSummaryUrl!),
				(value) => value?.enabled === true && value?.status === 'idle',
				20_000,
			);
			assert.equal(idleSummary.enabled, true);
			assert.equal(idleSummary.hasResult, false);

			const runUrl = state.validatorSummaryUrl!.replace('/api/query/validation/summary', '/api/validation/run');
			const runSummary = await postJson(runUrl);
			assert.equal(runSummary.enabled, true);

			const readySummary = await waitFor(
				() => fetchJson(state.validatorSummaryUrl!),
				(value) => value?.enabled === true && value?.hasResult === true,
				20_000,
			);
			assert.equal(readySummary.enabled, true);
			assert.equal(readySummary.hasResult, true);
		} finally {
			await config.update('sharedObserverUrl', '', vscode.ConfigurationTarget.Global);
			await sharedObserver.dispose();
		}
	});

	test('openObserver retries when the shared backend health check times out once', async function () {
		this.timeout(30_000);

		await getExtension();
		const sharedObserver = await startSlowSharedObserver(750);
		const config = vscode.workspace.getConfiguration('observability-studio');
		const sharedMcpUrl = `${sharedObserver.baseUrl}/mcp`;

		try {
			await config.update('sharedObserverUrl', sharedMcpUrl, vscode.ConfigurationTarget.Global);
			await vscode.commands.executeCommand('observability-studio.openObserver');

			const state = await waitFor(
				() => Promise.resolve(vscode.commands.executeCommand<RuntimeState>('observability-studio.internal.getRuntimeState')),
				(value) => {
					if (!value) {
						return false;
					}
					return value.panelVisible
						&& value.sharedMode
						&& value.observerUrl === sharedObserver.baseUrl
						&& typeof value.panelHtml === 'string'
						&& value.panelHtml.includes(sharedObserver.baseUrl);
				},
				20_000,
			);

			assert.equal(state.sharedMode, true);
			assert.equal(state.observerUrl, sharedObserver.baseUrl);
			assert.ok(
				state.panelHtml?.includes(sharedObserver.baseUrl),
				'observer panel iframe should point at the shared backend after retrying a timeout',
			);
		} finally {
			await config.update('sharedObserverUrl', '', vscode.ConfigurationTarget.Global);
			await sharedObserver.dispose();
		}
	});
});
