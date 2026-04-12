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

async function waitForHttp(url: string, timeoutMs: number): Promise<void> {
	const deadline = Date.now() + timeoutMs;
	let lastError: unknown;
	while (Date.now() < deadline) {
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
	if (lastError instanceof Error) {
		throw lastError;
	}
	throw new Error(`Timed out waiting for ${url}`);
}

async function startSharedObserver(binaryPath: string): Promise<SharedObserverHandle> {
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
		await waitForHttp(baseUrl, 10_000);
	} catch (error) {
		child.kill();
		throw new Error(`shared observer failed to start: ${error instanceof Error ? error.message : String(error)}\n${stderr}`);
	}

	return {
		baseUrl,
		dispose: async () => {
			if (child.exitCode !== null || child.killed) {
				return;
			}
			child.kill();
			await new Promise<void>((resolve) => {
				child.once('exit', () => resolve());
			});
		},
	};
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
	test('status menu shows Configure Observer in the running-state order', async function () {
		this.timeout(30_000);

		await getExtension();
		const windowApi = vscode.window as typeof vscode.window & {
			showQuickPick: typeof vscode.window.showQuickPick;
		};
		const originalShowQuickPick = windowApi.showQuickPick;
		let labels: string[] = [];

		try {
			await vscode.commands.executeCommand('observability-studio.openObserver');

			const state = await waitFor(
				() => Promise.resolve(vscode.commands.executeCommand<RuntimeState>('observability-studio.internal.getRuntimeState')),
				(value) => {
					if (!value) {
						return false;
					}
					return value.panelVisible
						&& value.sharedMode === false
						&& typeof value.observerUrl === 'string'
						&& typeof value.panelHtml === 'string'
						&& value.panelHtml.includes('<iframe');
				},
				20_000,
			);
			await waitForHttp(state.observerUrl!, 20_000);

			windowApi.showQuickPick = (async (items: readonly any[]) => {
				labels = items.map((item) => item.label);
				return undefined;
			}) as typeof vscode.window.showQuickPick;

			await vscode.commands.executeCommand('observability-studio.statusMenu');

			assert.deepEqual(labels, [
				'$(window) Open Observer',
				'$(settings-gear) Configure Observer...',
				'$(debug-restart) Restart Observer',
				'$(debug-stop) Stop Observer',
				'$(output) Show Output Log',
			]);
		} finally {
			windowApi.showQuickPick = originalShowQuickPick;
			await vscode.commands.executeCommand('observability-studio.stopObserver');
		}
	});

	test('setup configures a local backend with custom ports and Codex MCP', async function () {
		this.timeout(30_000);

		await getExtension();
		const config = vscode.workspace.getConfiguration('observability-studio');
		const observerPort = await getAvailablePort();
		const httpPort = await getAvailablePort();
		const grpcPort = await getAvailablePort();
		const baseUrl = `http://127.0.0.1:${observerPort}`;
		const mcpUrl = `${baseUrl}/mcp`;
		const tempHome = fs.mkdtempSync(path.join(os.tmpdir(), 'obstudio-home-'));
		const originalHome = process.env.HOME;
		const originalUserProfile = process.env.USERPROFILE;
		const codexConfigPath = path.join(tempHome, '.codex', 'config.toml');
		const originalCodexConfigPath = originalHome ? path.join(originalHome, '.codex', 'config.toml') : '';
		const originalCodexSnapshot = snapshotFile(originalCodexConfigPath);
		const originalSharedObserverUrl = config.get<string>('sharedObserverUrl');
		const originalLocalObserverPort = config.get<number>('localObserverPort');
		const originalLocalOtlpHttpPort = config.get<number>('localOtlpHttpPort');
		const originalLocalOtlpGrpcPort = config.get<number>('localOtlpGrpcPort');
		const quickPickSelections = ['Start local backend', 'Choose custom ports', 'Codex'];
		const inputSelections = [String(observerPort), String(httpPort), String(grpcPort)];
		const infoMessages: string[] = [];
		const windowApi = vscode.window as typeof vscode.window & {
			showInformationMessage: typeof vscode.window.showInformationMessage;
			showInputBox: typeof vscode.window.showInputBox;
			showQuickPick: typeof vscode.window.showQuickPick;
		};
		const originalShowQuickPick = windowApi.showQuickPick;
		const originalShowInputBox = windowApi.showInputBox;
		const originalShowInformationMessage = windowApi.showInformationMessage;

		process.env.HOME = tempHome;
		process.env.USERPROFILE = tempHome;

		windowApi.showQuickPick = (async (items: readonly any[]) => {
			const next = quickPickSelections.shift();
			if (!next) {
				return undefined;
			}
			return items.find((item) => item?.label === next || item?.id === next);
		}) as typeof vscode.window.showQuickPick;
		windowApi.showInputBox = (async () => inputSelections.shift()) as typeof vscode.window.showInputBox;
		windowApi.showInformationMessage = (async (message: string) => {
			infoMessages.push(message);
			return undefined;
		}) as typeof vscode.window.showInformationMessage;

		try {
			await vscode.commands.executeCommand('observability-studio.setup');
			const updatedConfig = vscode.workspace.getConfiguration('observability-studio');

			const state = await waitFor(
				() => Promise.resolve(vscode.commands.executeCommand<RuntimeState>('observability-studio.internal.getRuntimeState')),
				(value) => {
					if (!value) {
						return false;
					}
					return value.sharedMode === false && value.observerUrl === baseUrl;
				},
				20_000,
			);

			assert.equal(state.sharedMode, false);
			assert.equal(state.observerUrl, baseUrl);
			assert.equal(updatedConfig.get('sharedObserverUrl'), '');
			assert.equal(updatedConfig.get('localObserverPort'), observerPort);
			assert.equal(updatedConfig.get('localOtlpHttpPort'), httpPort);
			assert.equal(updatedConfig.get('localOtlpGrpcPort'), grpcPort);

			await vscode.commands.executeCommand('observability-studio.openObserver');
			const panelState = await waitFor(
				() => Promise.resolve(vscode.commands.executeCommand<RuntimeState>('observability-studio.internal.getRuntimeState')),
				(value) => {
					if (!value) {
						return false;
					}
					return value.panelVisible && value.observerUrl === baseUrl && typeof value.panelHtml === 'string' && value.panelHtml.includes(baseUrl);
				},
				20_000,
			);
			assert.ok(panelState.panelHtml?.includes(baseUrl));

			const health = await fetchJson(`${baseUrl}/api/health`);
			assert.equal(health.endpoints.otlpHttp, `http://127.0.0.1:${httpPort}`);
			assert.equal(health.endpoints.otlpGrpc, `127.0.0.1:${grpcPort}`);

			await assertCodexConfigured([codexConfigPath, originalCodexConfigPath], mcpUrl);
			assert.ok(
				infoMessages.some((message) => message.includes(`Codex MCP ${mcpUrl}`)),
				'setup should show a concise completion summary',
			);
		} finally {
			windowApi.showQuickPick = originalShowQuickPick;
			windowApi.showInputBox = originalShowInputBox;
			windowApi.showInformationMessage = originalShowInformationMessage;
			await vscode.commands.executeCommand('observability-studio.stopObserver');
			await config.update('sharedObserverUrl', originalSharedObserverUrl, vscode.ConfigurationTarget.Global);
			await config.update('localObserverPort', originalLocalObserverPort, vscode.ConfigurationTarget.Global);
			await config.update('localOtlpHttpPort', originalLocalOtlpHttpPort, vscode.ConfigurationTarget.Global);
			await config.update('localOtlpGrpcPort', originalLocalOtlpGrpcPort, vscode.ConfigurationTarget.Global);
			process.env.HOME = originalHome;
			process.env.USERPROFILE = originalUserProfile;
			restoreSnapshot(originalCodexSnapshot);
			fs.rmSync(tempHome, { force: true, recursive: true });
		}
	});

	test('setup cancellation at the agent step leaves settings and runtime unchanged', async function () {
		this.timeout(30_000);

		const extension = await getExtension();
		const sharedObserver = await startSharedObserver(path.join(extension.extensionPath, 'dist', 'observer', 'obstudio'));
		const config = vscode.workspace.getConfiguration('observability-studio');
		const previousSharedUrl = `${sharedObserver.baseUrl}/mcp`;
		const observerPort = await getAvailablePort();
		const httpPort = await getAvailablePort();
		const grpcPort = await getAvailablePort();
		const windowApi = vscode.window as typeof vscode.window & {
			showQuickPick: typeof vscode.window.showQuickPick;
			showInputBox: typeof vscode.window.showInputBox;
		};
		const originalShowQuickPick = windowApi.showQuickPick;
		const originalShowInputBox = windowApi.showInputBox;
		const quickPickSelections = ['Start local backend', 'Choose custom ports'];
		const inputSelections = [String(observerPort), String(httpPort), String(grpcPort)];

		try {
			await config.update('sharedObserverUrl', previousSharedUrl, vscode.ConfigurationTarget.Global);

			await waitFor(
				() => Promise.resolve(vscode.commands.executeCommand<RuntimeState>('observability-studio.internal.getRuntimeState')),
				(value) => Boolean(value?.sharedMode && value.observerUrl === sharedObserver.baseUrl),
				20_000,
			);

			windowApi.showQuickPick = (async (items: readonly any[]) => {
				const next = quickPickSelections.shift();
				if (!next) {
					return undefined;
				}
				return items.find((item) => item?.label === next || item?.id === next);
			}) as typeof vscode.window.showQuickPick;
			windowApi.showInputBox = (async () => inputSelections.shift()) as typeof vscode.window.showInputBox;

			await vscode.commands.executeCommand('observability-studio.setup');
			const updatedConfig = vscode.workspace.getConfiguration('observability-studio');

			const state = await waitFor(
				() => Promise.resolve(vscode.commands.executeCommand<RuntimeState>('observability-studio.internal.getRuntimeState')),
				(value) => Boolean(value?.sharedMode && value.observerUrl === sharedObserver.baseUrl),
				20_000,
			);

			assert.equal(state.sharedMode, true);
			assert.equal(state.observerUrl, sharedObserver.baseUrl);
			assert.equal(updatedConfig.get('sharedObserverUrl'), previousSharedUrl);
		} finally {
			windowApi.showQuickPick = originalShowQuickPick;
			windowApi.showInputBox = originalShowInputBox;
			await config.update('sharedObserverUrl', '', vscode.ConfigurationTarget.Global);
			await sharedObserver.dispose();
		}
	});

	test('setup failure restores the previous settings and runtime', async function () {
		this.timeout(30_000);

		const extension = await getExtension();
		const sharedObserver = await startSharedObserver(path.join(extension.extensionPath, 'dist', 'observer', 'obstudio'));
		const config = vscode.workspace.getConfiguration('observability-studio');
		const previousSharedUrl = `${sharedObserver.baseUrl}/mcp`;
		const observerPort = await getAvailablePort();
		const httpPort = await getAvailablePort();
		const grpcPort = await getAvailablePort();
		const tempHome = fs.mkdtempSync(path.join(os.tmpdir(), 'obstudio-home-'));
		fs.chmodSync(tempHome, 0o555);
		const originalHome = process.env.HOME;
		const originalUserProfile = process.env.USERPROFILE;
		const errorMessages: string[] = [];
		const windowApi = vscode.window as typeof vscode.window & {
			showErrorMessage: typeof vscode.window.showErrorMessage;
			showInformationMessage: typeof vscode.window.showInformationMessage;
			showInputBox: typeof vscode.window.showInputBox;
			showQuickPick: typeof vscode.window.showQuickPick;
		};
		const originalShowQuickPick = windowApi.showQuickPick;
		const originalShowInputBox = windowApi.showInputBox;
		const originalShowInformationMessage = windowApi.showInformationMessage;
		const originalShowErrorMessage = windowApi.showErrorMessage;
		const quickPickSelections = ['Start local backend', 'Choose custom ports', 'Codex'];
		const inputSelections = [String(observerPort), String(httpPort), String(grpcPort)];

		try {
			process.env.HOME = tempHome;
			process.env.USERPROFILE = tempHome;
			await config.update('sharedObserverUrl', previousSharedUrl, vscode.ConfigurationTarget.Global);

			await waitFor(
				() => Promise.resolve(vscode.commands.executeCommand<RuntimeState>('observability-studio.internal.getRuntimeState')),
				(value) => Boolean(value?.sharedMode && value.observerUrl === sharedObserver.baseUrl),
				20_000,
			);

			windowApi.showQuickPick = (async (items: readonly any[]) => {
				const next = quickPickSelections.shift();
				if (!next) {
					return undefined;
				}
				return items.find((item) => item?.label === next || item?.id === next);
			}) as typeof vscode.window.showQuickPick;
			windowApi.showInputBox = (async () => inputSelections.shift()) as typeof vscode.window.showInputBox;
			windowApi.showInformationMessage = (async () => undefined) as typeof vscode.window.showInformationMessage;
			windowApi.showErrorMessage = (async (message: string) => {
				errorMessages.push(message);
				return undefined;
			}) as typeof vscode.window.showErrorMessage;

			await vscode.commands.executeCommand('observability-studio.setup');
			const updatedConfig = vscode.workspace.getConfiguration('observability-studio');

			const state = await waitFor(
				() => Promise.resolve(vscode.commands.executeCommand<RuntimeState>('observability-studio.internal.getRuntimeState')),
				(value) => Boolean(value?.sharedMode && value.observerUrl === sharedObserver.baseUrl),
				20_000,
			);

			assert.equal(state.sharedMode, true);
			assert.equal(state.observerUrl, sharedObserver.baseUrl);
			assert.equal(updatedConfig.get('sharedObserverUrl'), previousSharedUrl);
			assert.ok(
				errorMessages.some((message) => message.includes('Previous configuration was restored.')),
				'setup failure should restore the previous configuration',
			);
		} finally {
			windowApi.showQuickPick = originalShowQuickPick;
			windowApi.showInputBox = originalShowInputBox;
			windowApi.showInformationMessage = originalShowInformationMessage;
			windowApi.showErrorMessage = originalShowErrorMessage;
			await config.update('sharedObserverUrl', '', vscode.ConfigurationTarget.Global);
			process.env.HOME = originalHome;
			process.env.USERPROFILE = originalUserProfile;
			fs.chmodSync(tempHome, 0o755);
			fs.rmSync(tempHome, { force: true, recursive: true });
			await sharedObserver.dispose();
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
		const claudeConfigPath = path.join(tempHome, '.claude', 'settings.json');
		const cursorConfigPath = path.join(tempHome, '.cursor', 'mcp.json');
		const originalCodexConfigPath = originalHome ? path.join(originalHome, '.codex', 'config.toml') : '';
		const originalClaudeConfigPath = originalHome ? path.join(originalHome, '.claude', 'settings.json') : '';
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
			fs.rmSync(tempHome, { force: true, recursive: true });
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
