import * as cp from 'node:child_process';
import * as net from 'node:net';
import * as vscode from 'vscode';
import { resolveBackend } from './backend';
import {
	assertObserverRunCurrent,
	beginObserverStart,
	completeObserverStart,
	createObserverLifecycleState,
	failObserverStart,
	finishObserverRun,
	isObserverLifecycleCancelled,
	isObserverRunCurrent,
	stopObserverRun,
} from './observer-lifecycle';
import {
	getObserverWebviewHtml,
	getObserverLoadingWebviewHtml,
	getObserverErrorWebviewHtml,
	getObserverStoppedWebviewHtml,
	getStatusBarUpdate,
	getErrorMessage,
} from './webview-html';

// Extension-global observer state. The extension hosts one local observer process
// and optionally one WebView panel that embeds its UI.
let observerProcess: cp.ChildProcess | undefined;
let observerOutputChannel: vscode.OutputChannel | undefined;
let observerPanel: vscode.WebviewPanel | undefined;
let observerStartupPromise: Promise<void> | undefined;
let observerStopPromise: Promise<void> | undefined;
let observerStatusBarItem: vscode.StatusBarItem | undefined;
const observerLifecycleState = createObserverLifecycleState();
let lastObserverPanelRenderKey: string | undefined;

const observerPanelViewType = 'observabilityStudioObserver';

// The extension exposes a stable OTLP endpoint so instrumented apps can target a
// predictable localhost port.
const observerOtlpHttpPort = 4318;
const observerOtlpGrpcPort = 4317;

export async function activate(context: vscode.ExtensionContext) {
	observerOutputChannel = vscode.window.createOutputChannel('Observability Studio');
	context.subscriptions.push(observerOutputChannel);
	logObserverLifecycle('Extension activated.');

	context.subscriptions.push(
		vscode.window.registerWebviewPanelSerializer(observerPanelViewType, {
			async deserializeWebviewPanel(webviewPanel: vscode.WebviewPanel) {
				observerPanel = webviewPanel;
				configureObserverPanel(webviewPanel, context);
				logObserverLifecycle('Restored observer webview panel.');
				webviewPanel.webview.html = getObserverLoadingWebviewHtml();
				try {
					await ensureObserverRunning(context);
					refreshObserverPanel();
				} catch {
					refreshObserverPanel();
				}
			},
		}),
	);

	// Status bar item reflects observer state and toggles the panel.
	observerStatusBarItem = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Right, 100);
	observerStatusBarItem.command = 'observability-studio.openObserver';
	updateStatusBar('starting');
	observerStatusBarItem.show();
	logObserverLifecycle('Status bar item created.');

	// Start the packaged observer as soon as the extension activates so the UI
	// and OTLP receiver are ready before the user opens the panel.
	void ensureObserverRunning(context).catch((error) => {
		if (isObserverLifecycleCancelled(error)) {
			return;
		}
		const message = getErrorMessage(error);
		appendObserverOutputLine(`Observer startup failed: ${message}`);
		void vscode.window.showErrorMessage(`Observability Studio could not start: ${message}`);
	});

	const openObserverDisposable = vscode.commands.registerCommand('observability-studio.openObserver', () => {
		openObserverPanel(context);
	});

	const statusMenuDisposable = vscode.commands.registerCommand('observability-studio.statusMenu', async () => {
		if (observerLifecycleState.status === 'running') {
			const pick = await vscode.window.showQuickPick(
				[
					{ label: '$(window) Open Observer', id: 'open' },
					{ label: '$(debug-restart) Restart Observer', id: 'restart' },
					{ label: '$(debug-stop) Stop Observer', id: 'stop' },
					{ label: '$(output) Show Output Log', id: 'log' },
				],
				{ placeHolder: `Observer is running on port ${observerLifecycleState.port ?? '?'}` },
			);
			if (pick?.id === 'open') {
				void vscode.commands.executeCommand('observability-studio.openObserver');
			} else if (pick?.id === 'restart') {
				void vscode.commands.executeCommand('observability-studio.restartObserver');
			} else if (pick?.id === 'stop') {
				void vscode.commands.executeCommand('observability-studio.stopObserver');
			} else if (pick?.id === 'log') {
				observerOutputChannel?.show();
			}
		} else if (observerLifecycleState.status === 'starting') {
			const pick = await vscode.window.showQuickPick(
				[
					{ label: '$(debug-stop) Stop Observer', id: 'stop' },
					{ label: '$(debug-restart) Restart Observer', id: 'restart' },
					{ label: '$(output) Show Output Log', id: 'log' },
				],
				{ placeHolder: 'Observer is starting...' },
			);
			if (pick?.id === 'stop') {
				void vscode.commands.executeCommand('observability-studio.stopObserver');
			} else if (pick?.id === 'restart') {
				void vscode.commands.executeCommand('observability-studio.restartObserver');
			} else if (pick?.id === 'log') {
				observerOutputChannel?.show();
			}
		} else {
			const pick = await vscode.window.showQuickPick(
				[
					{ label: '$(play) Start Observer', id: 'start' },
					{ label: '$(output) Show Output Log', id: 'log' },
				],
				{
					placeHolder: observerLifecycleState.startupError
						? `Observer failed: ${observerLifecycleState.startupError}`
						: 'Observer is stopped',
				},
			);
			if (pick?.id === 'start') {
				void vscode.commands.executeCommand('observability-studio.startObserver');
			} else if (pick?.id === 'log') {
				observerOutputChannel?.show();
			}
		}
	});

	const startDisposable = vscode.commands.registerCommand('observability-studio.startObserver', async () => {
		if (observerLifecycleState.status === 'running') {
			void vscode.window.showInformationMessage('Observer is already running.');
			return;
		}
		if (observerLifecycleState.status === 'starting') {
			void vscode.window.showInformationMessage('Observer is already starting.');
			return;
		}
		try {
			await ensureObserverRunning(context);
			refreshObserverPanel();
		} catch (error) {
			if (isObserverLifecycleCancelled(error)) {
				refreshObserverPanel();
				return;
			}
			const message = getErrorMessage(error);
			void vscode.window.showErrorMessage(`Observability Studio could not start: ${message}`);
			refreshObserverPanel();
		}
	});

	const stopDisposable = vscode.commands.registerCommand('observability-studio.stopObserver', async () => {
		if (observerProcess === undefined && observerStartupPromise === undefined) {
			void vscode.window.showInformationMessage('Observer is not running.');
			return;
		}
		await stopObserver();
		void vscode.window.showInformationMessage('Observer stopped.');
	});

	const restartDisposable = vscode.commands.registerCommand('observability-studio.restartObserver', async () => {
		await stopObserver();
		try {
			await ensureObserverRunning(context);
			refreshObserverPanel();
		} catch (error) {
			if (isObserverLifecycleCancelled(error)) {
				refreshObserverPanel();
				return;
			}
			const message = getErrorMessage(error);
			void vscode.window.showErrorMessage(`Observability Studio could not start: ${message}`);
			refreshObserverPanel();
		}
	});

	context.subscriptions.push(openObserverDisposable);
	context.subscriptions.push(statusMenuDisposable);
	context.subscriptions.push(startDisposable);
	context.subscriptions.push(stopDisposable);
	context.subscriptions.push(restartDisposable);
	context.subscriptions.push(observerStatusBarItem);
	context.subscriptions.push({
		dispose: () => {
			logObserverLifecycle('Extension disposed; terminating observer process.');
			stopObserverRun(observerLifecycleState);
			observerStartupPromise = undefined;
			observerStopPromise = undefined;
			terminateObserverProcess(observerProcess, 'SIGTERM');
			observerProcess = undefined;
		},
	});
}

export function deactivate() {
	logObserverLifecycle('Extension deactivated; terminating observer process.');
	stopObserverRun(observerLifecycleState);
	observerStartupPromise = undefined;
	observerStopPromise = undefined;
	terminateObserverProcess(observerProcess, 'SIGTERM');
	observerProcess = undefined;
}

// ---------------------------------------------------------------------------
// Observer process lifecycle
// ---------------------------------------------------------------------------

async function ensureObserverRunning(context: vscode.ExtensionContext): Promise<void> {
	if (observerStartupPromise !== undefined) {
		logObserverLifecycle('Start requested while startup is already in progress; waiting for existing startup.');
		return observerStartupPromise;
	}
	if (observerStopPromise !== undefined) {
		logObserverLifecycle('Start requested while stop is in progress; waiting for observer shutdown.');
		await observerStopPromise;
	}
	if (observerLifecycleState.status === 'running' && observerProcess !== undefined) {
		logObserverLifecycle(`Start requested while observer is already running on port ${observerLifecycleState.port ?? '?'}.`);
		return;
	}

	if (observerOutputChannel === undefined) {
		throw new Error('Observer output channel is not initialized.');
	}

	return startObserver(context);
}

async function startObserver(context: vscode.ExtensionContext): Promise<void> {
	if (observerStartupPromise !== undefined) {
		return observerStartupPromise;
	}
	if (observerLifecycleState.status === 'running' && observerProcess !== undefined) {
		return;
	}

	const runId = beginObserverStart(observerLifecycleState);
	let startedProcess: cp.ChildProcess | undefined;

	logObserverLifecycle(`Starting observer run ${runId}.`);
	syncObserverUi();

	const startupPromise = (async () => {
		const backend = resolveBackend(context.extensionPath);
		const observerPort = await getAvailablePort();
		logObserverLifecycle(`Run ${runId}: reserved UI port ${observerPort}.`);
		assertObserverRunCurrent(observerLifecycleState, runId);

		const otlpHttpPort = await ensurePortAvailable(observerOtlpHttpPort);
		assertObserverRunCurrent(observerLifecycleState, runId);
		const otlpGrpcPort = await ensurePortAvailable(observerOtlpGrpcPort);
		assertObserverRunCurrent(observerLifecycleState, runId);
		logObserverLifecycle(`Run ${runId}: OTLP ports ready (HTTP ${otlpHttpPort}, gRPC ${otlpGrpcPort}).`);

		appendObserverOutputLine(`Starting ${backend.label} on http://127.0.0.1:${observerPort}`);
		appendObserverOutputLine(`OTLP/HTTP receiver listening on http://127.0.0.1:${otlpHttpPort}`);
		appendObserverOutputLine(`OTLP/gRPC receiver listening on 127.0.0.1:${otlpGrpcPort}`);

		startedProcess = cp.spawn(backend.command, backend.args, {
			cwd: backend.cwd,
			env: {
				...process.env,
				HOST: '127.0.0.1',
				OTLP_HOST: '127.0.0.1',
				OTLP_PORT: String(otlpHttpPort),
				OTLP_HTTP_PORT: String(otlpHttpPort),
				OTLP_GRPC_PORT: String(otlpGrpcPort),
				PORT: String(observerPort),
			},
			stdio: ['ignore', 'pipe', 'pipe'],
		});
		assertObserverRunCurrent(observerLifecycleState, runId);
		logObserverLifecycle(`Run ${runId}: spawned observer PID ${startedProcess.pid ?? 'unknown'}.`);

		observerProcess = startedProcess;

		startedProcess.stdout?.on('data', (chunk: Buffer | string) => {
			appendObserverOutput(chunk.toString());
		});

		startedProcess.stderr?.on('data', (chunk: Buffer | string) => {
			appendObserverOutput(chunk.toString());
		});

		startedProcess.on('exit', (code, signal) => {
			appendObserverOutputLine(`Observer exited with code=${code ?? 'null'} signal=${signal ?? 'null'}`);
			logObserverLifecycle(`Run ${runId}: observer process exited with code=${code ?? 'null'} signal=${signal ?? 'null'}.`);
			if (observerProcess === startedProcess) {
				observerProcess = undefined;
			}
			if (finishObserverRun(observerLifecycleState, runId)) {
				syncObserverUi();
			}
		});

		startedProcess.on('error', (error) => {
			appendObserverOutputLine(`Failed to start observer: ${error.message}`);
			logObserverLifecycle(`Run ${runId}: observer process error: ${error.message}`);
			if (observerProcess === startedProcess) {
				observerProcess = undefined;
			}
			if (failObserverStart(observerLifecycleState, runId, error.message)) {
				syncObserverUi();
				void vscode.window.showErrorMessage(`Observability Studio failed to start observer: ${error.message}`);
			}
		});

		await waitForObserverReady(observerPort, runId);
		logObserverLifecycle(`Run ${runId}: observer is accepting connections on UI port ${observerPort}.`);
		if (!completeObserverStart(observerLifecycleState, runId, observerPort)) {
			if (observerProcess === startedProcess) {
				observerProcess = undefined;
			}
			logObserverLifecycle(`Run ${runId}: startup completed after the run was superseded; terminating stale process.`);
			terminateObserverProcess(startedProcess, 'SIGTERM');
			return;
		}

		syncObserverUi();
	})().catch((error) => {
		if (isObserverLifecycleCancelled(error)) {
			logObserverLifecycle(`Run ${runId}: startup cancelled because lifecycle state changed.`);
			if (observerProcess === startedProcess) {
				observerProcess = undefined;
			}
			terminateObserverProcess(startedProcess, 'SIGTERM');
			return;
		}

		if (observerProcess === startedProcess) {
			observerProcess = undefined;
		}
		terminateObserverProcess(startedProcess, 'SIGTERM');
		if (failObserverStart(observerLifecycleState, runId, getErrorMessage(error))) {
			logObserverLifecycle(`Run ${runId}: startup failed: ${getErrorMessage(error)}`);
			syncObserverUi();
		}
		throw error;
	}).finally(() => {
		if (observerStartupPromise === startupPromise) {
			observerStartupPromise = undefined;
		}
	});

	observerStartupPromise = startupPromise;
	return observerStartupPromise;
}

async function stopObserver(): Promise<void> {
	if (observerStopPromise !== undefined) {
		logObserverLifecycle('Stop requested while shutdown is already in progress; waiting for existing shutdown.');
		return observerStopPromise;
	}

	const proc = observerProcess;
	if (proc === undefined && observerStartupPromise === undefined) {
		logObserverLifecycle('Stop requested but observer is already idle.');
		return;
	}

	logObserverLifecycle(
		`Stopping observer (status=${observerLifecycleState.status}, pid=${proc?.pid ?? 'none'}, port=${observerLifecycleState.port ?? 'none'}).`,
	);
	stopObserverRun(observerLifecycleState);
	observerProcess = undefined;
	observerStartupPromise = undefined;
	syncObserverUi();

	if (proc === undefined) {
		logObserverLifecycle('No observer process existed; shutdown completed after clearing in-flight startup state.');
		return;
	}

	const stopPromise = (async () => {
		const exitPromise = new Promise<void>((resolve) => {
			const timeout = setTimeout(() => {
				terminateObserverProcess(proc, 'SIGKILL');
				resolve();
			}, 2000);
			proc.once('exit', () => {
				clearTimeout(timeout);
				resolve();
			});
		});

		terminateObserverProcess(proc, 'SIGTERM');
		await exitPromise;
		await delay(300);
	})().finally(() => {
		if (observerStopPromise === stopPromise) {
			observerStopPromise = undefined;
		}
	});

	observerStopPromise = stopPromise;
	return observerStopPromise;
}

function syncObserverUi(): void {
	updateStatusBar(observerLifecycleState.status);
	refreshObserverPanel();
}

function terminateObserverProcess(
	proc: cp.ChildProcess | undefined,
	signal: NodeJS.Signals,
): void {
	if (proc === undefined || proc.exitCode !== null || proc.signalCode !== null) {
		return;
	}

	proc.kill(signal);
}

// ---------------------------------------------------------------------------
// WebView panel
// ---------------------------------------------------------------------------

async function openObserverPanel(context: vscode.ExtensionContext): Promise<void> {
	if (observerPanel === undefined) {
		logObserverLifecycle('Creating observer webview panel.');
		lastObserverPanelRenderKey = undefined;
		observerPanel = vscode.window.createWebviewPanel(
			observerPanelViewType,
			'Observer',
			vscode.ViewColumn.One,
			{
				enableScripts: true,
				retainContextWhenHidden: true,
			},
		);
		configureObserverPanel(observerPanel, context);
	}

	logObserverLifecycle('Revealing observer webview panel.');
	observerPanel.reveal(vscode.ViewColumn.One);

	// If already running, show the UI immediately.
	if (observerLifecycleState.status === 'running' && observerLifecycleState.port !== undefined) {
		refreshObserverPanel();
		return;
	}

	// Not running — show loading, auto-start, then show result.
	observerPanel.webview.html = getObserverLoadingWebviewHtml();
	try {
		await ensureObserverRunning(context);
		refreshObserverPanel();
	} catch {
		refreshObserverPanel();
	}
}

function configureObserverPanel(panel: vscode.WebviewPanel, context: vscode.ExtensionContext): void {
	panel.webview.options = {
		enableScripts: true,
	};
	panel.onDidDispose(() => {
		if (observerPanel === panel) {
			logObserverLifecycle('Observer webview panel disposed.');
			lastObserverPanelRenderKey = undefined;
			observerPanel = undefined;
		}
	}, undefined, context.subscriptions);
}

function refreshObserverPanel(): void {
	if (observerPanel === undefined) {
		return;
	}

	const renderKey = `${observerLifecycleState.status}:${observerLifecycleState.port ?? 'none'}:${observerLifecycleState.startupError ?? 'none'}`;
	if (renderKey !== lastObserverPanelRenderKey) {
		logObserverLifecycle(`Rendering observer panel state ${renderKey}.`);
		lastObserverPanelRenderKey = renderKey;
	}

	switch (observerLifecycleState.status) {
		case 'running':
			observerPanel.webview.html = observerLifecycleState.port === undefined
				? getObserverLoadingWebviewHtml()
				: getObserverWebviewHtml(observerLifecycleState.port);
			return;
		case 'error':
			observerPanel.webview.html = getObserverErrorWebviewHtml(
				observerLifecycleState.startupError ?? 'Observer could not start.',
			);
			return;
		case 'starting':
			observerPanel.webview.html = getObserverLoadingWebviewHtml();
			return;
		case 'stopped':
			observerPanel.webview.html = getObserverStoppedWebviewHtml();
			return;
	}
}

// ---------------------------------------------------------------------------
// Port helpers
// ---------------------------------------------------------------------------

async function getAvailablePort(): Promise<number> {
	return new Promise((resolve, reject) => {
		const server = net.createServer();
		server.once('error', reject);
		server.listen(0, '127.0.0.1', () => {
			const address = server.address();
			if (address === null || typeof address === 'string') {
				server.close(() => reject(new Error('Unable to allocate a local port for the observer.')));
				return;
			}
			server.close((error) => {
				if (error) { reject(error); return; }
				resolve(address.port);
			});
		});
	});
}

async function ensurePortAvailable(port: number): Promise<number> {
	return new Promise((resolve, reject) => {
		const server = net.createServer();
		server.once('error', (error: NodeJS.ErrnoException) => {
			if (error.code === 'EADDRINUSE') {
				void identifyPortOwner(port).then((owner) => {
					const detail = owner
						? `Port ${port} is already in use by "${owner}".`
						: `Port ${port} is already in use.`;
					logObserverLifecycle(detail);
					reject(new Error(
						`${detail} Stop the other process or run: kill $(lsof -ti :${port})`
					));
				});
				return;
			}
			logObserverLifecycle(`Port check failed for ${port}: ${error.message}`);
			reject(error);
		});
		server.listen(port, '127.0.0.1', () => {
			server.close((error) => {
				if (error) { reject(error); return; }
				resolve(port);
			});
		});
	});
}

async function identifyPortOwner(port: number): Promise<string | undefined> {
	return new Promise((resolve) => {
		cp.exec(`lsof -i :${port} -sTCP:LISTEN -n -P 2>/dev/null`, { timeout: 3000 }, (error, stdout) => {
			if (error || !stdout) { resolve(undefined); return; }
			const lines = stdout.trim().split('\n');
			if (lines.length < 2) { resolve(undefined); return; }
			const fields = lines[1].split(/\s+/);
			const command = fields[0];
			const pid = fields[1];
			resolve(command && pid ? `${command} (PID ${pid})` : undefined);
		});
	});
}

async function waitForObserverReady(port: number, runId: number): Promise<void> {
	const startupDeadline = Date.now() + 15_000;
	let lastError: unknown;

	while (Date.now() < startupDeadline) {
		assertObserverRunCurrent(observerLifecycleState, runId);

		try {
			await waitForPort(port, 500);
			assertObserverRunCurrent(observerLifecycleState, runId);
			return;
		} catch (error) {
			lastError = error;
			if (isObserverLifecycleCancelled(error)) {
				throw error;
			}
			if (!isObserverRunCurrent(observerLifecycleState, runId)) {
				assertObserverRunCurrent(observerLifecycleState, runId);
			}
			if (observerProcess === undefined) {
				break;
			}
			await delay(100);
		}
	}

	if (lastError !== undefined) {
		logObserverLifecycle(`Run ${runId}: readiness check timed out on port ${port}: ${getErrorMessage(lastError)}`);
	}
	throw lastError instanceof Error
		? lastError
		: new Error('Observer did not become ready in time.');
}

async function waitForPort(port: number, timeoutMs: number): Promise<void> {
	return new Promise((resolve, reject) => {
		const socket = new net.Socket();
		let settled = false;
		const finish = (callback: () => void) => {
			if (settled) { return; }
			settled = true;
			socket.destroy();
			callback();
		};
		socket.setTimeout(timeoutMs);
		socket.once('connect', () => finish(resolve));
		socket.once('timeout', () => finish(() => reject(new Error(`Timed out waiting for observer on port ${port}.`))));
		socket.once('error', (error) => finish(() => reject(error)));
		socket.connect(port, '127.0.0.1');
	});
}

function delay(ms: number): Promise<void> {
	return new Promise((resolve) => { setTimeout(resolve, ms); });
}

function appendObserverOutput(text: string): void {
	if (observerOutputChannel === undefined) {
		return;
	}

	try {
		observerOutputChannel.append(text);
	} catch {
		// VS Code can dispose the output channel during extension-host shutdown.
	}
}

function appendObserverOutputLine(text: string): void {
	appendObserverOutput(`${text}\n`);
}

function logObserverLifecycle(message: string): void {
	appendObserverOutputLine(`[extension] ${message}`);
}

// ---------------------------------------------------------------------------
// Status bar
// ---------------------------------------------------------------------------

function updateStatusBar(state: 'starting' | 'running' | 'stopped' | 'error'): void {
	if (observerStatusBarItem === undefined) {
		return;
	}
	const update = getStatusBarUpdate(state);
	observerStatusBarItem.text = update.text;
	observerStatusBarItem.tooltip = update.tooltip;
	observerStatusBarItem.command = update.command;
}
