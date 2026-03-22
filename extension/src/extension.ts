import * as cp from 'node:child_process';
import * as net from 'node:net';
import * as path from 'node:path';
import * as vscode from 'vscode';

// Extension-global observer state. The extension hosts one local observer process
// and optionally one WebView panel that embeds its UI.
let observerProcess: cp.ChildProcess | undefined;
let observerOutputChannel: vscode.OutputChannel | undefined;
let observerPanel: vscode.WebviewPanel | undefined;
let observerPort: number | undefined;
let observerStartupPromise: Promise<void> | undefined;

const observerPanelViewType = 'observabilityStudioObserver';

// The extension exposes a stable OTLP endpoint so instrumented apps can target a
// predictable localhost port.
const observerOtlpPort = 4318;

export async function activate(context: vscode.ExtensionContext) {
	observerOutputChannel = vscode.window.createOutputChannel('Observability Studio');
	context.subscriptions.push(observerOutputChannel);

	context.subscriptions.push(
		vscode.window.registerWebviewPanelSerializer(observerPanelViewType, {
			async deserializeWebviewPanel(webviewPanel: vscode.WebviewPanel) {
				observerPanel = webviewPanel;
				configureObserverPanel(webviewPanel, context);
				await showObserverWhenReady(context);
			},
		}),
	);

	// Start the packaged observer as soon as the extension activates so the UI
	// and OTLP receiver are ready before the user opens the panel.
	void startObserver(context, observerOutputChannel).catch((error) => {
		const message = getErrorMessage(error);
		observerOutputChannel?.appendLine(`Observer startup failed: ${message}`);
		void vscode.window.showErrorMessage(`Observability Studio could not start because OTLP port ${observerOtlpPort} is unavailable: ${message}`);
		refreshObserverPanel();
	});

	console.log('Congratulations, your extension "observability-studio" is now active!');

	const disposable = vscode.commands.registerCommand('observability-studio.helloWorld', () => {
		vscode.window.showInformationMessage('Hello World from Observability Studio!');
	});
	const openObserverDisposable = vscode.commands.registerCommand('observability-studio.openObserver', () => {
		openObserverPanel(context);
	});
	const observerStatusBarItem = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Right, 100);

	observerStatusBarItem.command = 'observability-studio.openObserver';
	observerStatusBarItem.text = '$(pulse) Observer';
	observerStatusBarItem.tooltip = 'Open Observability Studio Observer';
	observerStatusBarItem.show();

	context.subscriptions.push(disposable);
	context.subscriptions.push(openObserverDisposable);
	context.subscriptions.push(observerStatusBarItem);
	context.subscriptions.push({
		dispose: () => {
			stopObserver();
		},
	});
}

export function deactivate() {
	stopObserver();
}

async function startObserver(context: vscode.ExtensionContext, outputChannel: vscode.OutputChannel): Promise<void> {
	if (observerStartupPromise !== undefined) {
		return observerStartupPromise;
	}

	if (observerProcess !== undefined) {
		return;
	}

	observerStartupPromise = (async () => {
		const observerEntry = path.join(context.extensionPath, 'dist', 'observer', 'index.js');
		observerPort = await getAvailablePort();

		// The observer UI can move to any free localhost port, but OTLP stays fixed so
		// external telemetry producers do not need to rediscover the receiver port.
		const otlpPort = await ensurePortAvailable(observerOtlpPort);

		observerOutputChannel?.appendLine(`Starting observer on http://127.0.0.1:${observerPort}`);
		observerOutputChannel?.appendLine(`OTLP receiver listening on http://127.0.0.1:${otlpPort}`);

		observerProcess = cp.spawn(process.execPath, [observerEntry], {
			cwd: path.dirname(observerEntry),
			env: {
				...process.env,
				HOST: '127.0.0.1',
				OTLP_HOST: '127.0.0.1',
				OTLP_PORT: String(otlpPort),
				PORT: String(observerPort),
			},
			stdio: ['ignore', 'pipe', 'pipe'],
		});

		observerProcess.stdout?.on('data', (chunk: Buffer | string) => {
			outputChannel.append(chunk.toString());
		});

		observerProcess.stderr?.on('data', (chunk: Buffer | string) => {
			outputChannel.append(chunk.toString());
		});

		observerProcess.on('exit', (code, signal) => {
			outputChannel.appendLine(`Observer exited with code=${code ?? 'null'} signal=${signal ?? 'null'}`);
			observerProcess = undefined;
			observerPort = undefined;
			observerStartupPromise = undefined;
			refreshObserverPanel();
		});

		observerProcess.on('error', (error) => {
			outputChannel.appendLine(`Failed to start observer: ${error.message}`);
			void vscode.window.showErrorMessage(`Observability Studio failed to start observer: ${error.message}`);
			observerProcess = undefined;
			observerPort = undefined;
			observerStartupPromise = undefined;
			refreshObserverPanel();
		});

		refreshObserverPanel();
		await waitForObserverReady();
	})().catch((error) => {
		observerStartupPromise = undefined;
		throw error;
	});

	return observerStartupPromise;
}

function stopObserver(): void {
	if (observerProcess === undefined) {
		return;
	}

	observerProcess.kill();
	observerProcess = undefined;
	observerPort = undefined;
	refreshObserverPanel();
}

// Ask the OS for an ephemeral localhost port for the observer HTTP UI.
async function getAvailablePort(): Promise<number> {
	return new Promise((resolve, reject) => {
		const server = net.createServer();

		server.once('error', reject);
		server.listen(0, '127.0.0.1', () => {
			const address = server.address();
			if (address === null || typeof address === 'string') {
				server.close(() => {
					reject(new Error('Unable to allocate a local port for the observer.'));
				});
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

// Probe the fixed OTLP port during startup so activation can fail with a clear
// message before spawning the observer process.
async function ensurePortAvailable(port: number): Promise<number> {
	return new Promise((resolve, reject) => {
		const server = net.createServer();

		server.once('error', (error) => {
			reject(error);
		});
		server.listen(port, '127.0.0.1', () => {
			server.close((error) => {
				if (error) {
					reject(error);
					return;
				}

				resolve(port);
			});
		});
	});
}

async function openObserverPanel(context: vscode.ExtensionContext): Promise<void> {
	// Reuse the existing panel so the embedded app keeps its current state when the
	// user invokes the command again.
	if (observerPanel !== undefined) {
		await showObserverWhenReady(context);
		observerPanel.reveal(vscode.ViewColumn.One);
		return;
	}

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
	await showObserverWhenReady(context);
}

function configureObserverPanel(panel: vscode.WebviewPanel, context: vscode.ExtensionContext): void {
	panel.webview.options = {
		enableScripts: true,
	};
	panel.onDidDispose(() => {
		if (observerPanel === panel) {
			observerPanel = undefined;
		}
	}, undefined, context.subscriptions);
}

function refreshObserverPanel(): void {
	if (observerPanel === undefined) {
		return;
	}

	observerPanel.webview.html = observerPort === undefined
		? getObserverLoadingWebviewHtml()
		: getObserverWebviewHtml(observerPort);
}

async function showObserverWhenReady(context: vscode.ExtensionContext): Promise<void> {
	refreshObserverPanel();

	try {
		if (observerOutputChannel === undefined) {
			throw new Error('Observer output channel is not initialized.');
		}

		await startObserver(context, observerOutputChannel);
		refreshObserverPanel();
	} catch (error) {
		refreshObserverPanel();
		throw error;
	}
}

async function waitForObserverReady(): Promise<void> {
	if (observerPort === undefined) {
		throw new Error('Observer port is not available.');
	}

	const startupDeadline = Date.now() + 15_000;
	let lastError: unknown;

	while (Date.now() < startupDeadline) {
		try {
			await waitForPort(observerPort, 500);
			return;
		} catch (error) {
			lastError = error;
			if (observerProcess === undefined) {
				break;
			}
			await delay(100);
		}
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
			if (settled) {
				return;
			}
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
	return new Promise((resolve) => {
		setTimeout(resolve, ms);
	});
}

function getObserverWebviewHtml(port: number): string {
	const observerUrl = `http://127.0.0.1:${port}`;

	return `<!DOCTYPE html>
<html lang="en">
<head>
	<meta charset="UTF-8">
	<meta
		http-equiv="Content-Security-Policy"
		content="default-src 'none'; frame-src ${observerUrl}; style-src 'unsafe-inline';"
	>
	<meta name="viewport" content="width=device-width, initial-scale=1.0">
	<title>Observer</title>
	<style>
		html, body, iframe {
			height: 100%;
			margin: 0;
			padding: 0;
			width: 100%;
		}

		body {
			background: var(--vscode-editor-background);
		}

		iframe {
			border: 0;
		}
	</style>
</head>
<body>
	<iframe src="${observerUrl}" title="Observer"></iframe>
</body>
</html>`;
}

function getObserverLoadingWebviewHtml(): string {
	return `<!DOCTYPE html>
<html lang="en">
<head>
	<meta charset="UTF-8">
	<meta
		http-equiv="Content-Security-Policy"
		content="default-src 'none'; style-src 'unsafe-inline';"
	>
	<meta name="viewport" content="width=device-width, initial-scale=1.0">
	<title>Observer</title>
	<style>
		body {
			align-items: center;
			background: var(--vscode-editor-background);
			color: var(--vscode-foreground);
			display: flex;
			font-family: var(--vscode-font-family);
			height: 100vh;
			justify-content: center;
			margin: 0;
			padding: 24px;
			text-align: center;
		}
	</style>
</head>
<body>
	<div>Observability Studio is starting…</div>
</body>
</html>`;
}

function getErrorMessage(error: unknown): string {
	if (error instanceof Error) {
		return error.message;
	}

	return String(error);
}
