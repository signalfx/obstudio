import * as cp from 'node:child_process';
import * as net from 'node:net';
import * as path from 'node:path';
import * as vscode from 'vscode';

let observerProcess: cp.ChildProcess | undefined;
let observerOutputChannel: vscode.OutputChannel | undefined;
let observerPanel: vscode.WebviewPanel | undefined;
let observerPort: number | undefined;
const observerOtlpPort = 4318;

export async function activate(context: vscode.ExtensionContext) {
	observerOutputChannel = vscode.window.createOutputChannel('Observability Studio');
	context.subscriptions.push(observerOutputChannel);

	try {
		await startObserver(context, observerOutputChannel);
	} catch (error) {
		const message = getErrorMessage(error);
		observerOutputChannel.appendLine(`Observer startup failed: ${message}`);
		void vscode.window.showErrorMessage(`Observability Studio could not start because OTLP port ${observerOtlpPort} is unavailable: ${message}`);
	}

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
	if (observerProcess !== undefined) {
		return;
	}

	const observerEntry = path.join(context.extensionPath, 'dist', 'observer', 'index.js');
	observerPort = await getAvailablePort();
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
	});

	observerProcess.on('error', (error) => {
		outputChannel.appendLine(`Failed to start observer: ${error.message}`);
		void vscode.window.showErrorMessage(`Observability Studio failed to start observer: ${error.message}`);
		observerProcess = undefined;
		observerPort = undefined;
	});
}

function stopObserver(): void {
	if (observerProcess === undefined) {
		return;
	}

	observerProcess.kill();
	observerProcess = undefined;
	observerPort = undefined;
}

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

function openObserverPanel(context: vscode.ExtensionContext): void {
	if (observerPort === undefined) {
		void vscode.window.showErrorMessage('Observer is not running yet.');
		return;
	}

	if (observerPanel !== undefined) {
		observerPanel.webview.html = getObserverWebviewHtml(observerPort);
		observerPanel.reveal(vscode.ViewColumn.One);
		return;
	}

	observerPanel = vscode.window.createWebviewPanel(
		'observabilityStudioObserver',
		'Observer',
		vscode.ViewColumn.One,
		{
			enableScripts: true,
		},
	);

	observerPanel.webview.html = getObserverWebviewHtml(observerPort);
	observerPanel.onDidDispose(() => {
		observerPanel = undefined;
	}, undefined, context.subscriptions);
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

function getErrorMessage(error: unknown): string {
	if (error instanceof Error) {
		return error.message;
	}

	return String(error);
}
