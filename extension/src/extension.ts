import * as cp from 'node:child_process';
import * as net from 'node:net';
import * as path from 'node:path';
import * as vscode from 'vscode';

let observerProcess: cp.ChildProcess | undefined;
let observerOutputChannel: vscode.OutputChannel | undefined;

export async function activate(context: vscode.ExtensionContext) {
	observerOutputChannel = vscode.window.createOutputChannel('Observability Studio');
	context.subscriptions.push(observerOutputChannel);

	await startObserver(context, observerOutputChannel);

	console.log('Congratulations, your extension "observability-studio" is now active!');

	const disposable = vscode.commands.registerCommand('observability-studio.helloWorld', () => {
		vscode.window.showInformationMessage('Hello World from Observability Studio!');
	});

	context.subscriptions.push(disposable);
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
	const observerPort = await getAvailablePort();
	const otlpPort = await getAvailablePort();

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
	});

	observerProcess.on('error', (error) => {
		outputChannel.appendLine(`Failed to start observer: ${error.message}`);
		void vscode.window.showErrorMessage(`Observability Studio failed to start observer: ${error.message}`);
		observerProcess = undefined;
	});
}

function stopObserver(): void {
	if (observerProcess === undefined) {
		return;
	}

	observerProcess.kill();
	observerProcess = undefined;
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
