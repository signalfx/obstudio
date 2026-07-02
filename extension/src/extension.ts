import * as cp from 'node:child_process';
import * as fs from 'node:fs';
import * as http from 'node:http';
import * as https from 'node:https';
import * as net from 'node:net';
import * as os from 'node:os';
import * as path from 'node:path';
import * as vscode from 'vscode';
import {
	buildObserverHealthUrl,
	buildObserverValidatorSummaryUrl,
	type ObserverHealth,
	normalizeObserverBaseUrl,
	observerPortFromUrl,
	resolveBackend,
} from './backend';
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
	getObserverErrorWebviewHtml,
	getObserverLoadingWebviewHtml,
	getObserverStoppedWebviewHtml,
	getStatusBarUpdate,
	getErrorMessage,
} from './webview-html';
import {
	describeObserverStartupFailure,
	formatObserverProbeMismatchMessage,
	formatObserverProbeUnavailableMessage,
	formatPortConflictMessage,
	getObserverProbeMismatchHint,
	getObserverProbeUnavailableHint,
	getObserverStartupHint,
	type ObserverPortRole,
} from './startup-errors';

// Extension-global observer state. The extension hosts one local observer process
// and optionally one WebView panel that embeds its UI.
let observerProcess: cp.ChildProcess | undefined;
let observerOutputChannel: vscode.OutputChannel | undefined;
let observerPanel: vscode.WebviewPanel | undefined;
let observerBaseUrl: string | undefined;
let observerStartupPromise: Promise<void> | undefined;
let observerStopPromise: Promise<void> | undefined;
let observerStatusBarItem: vscode.StatusBarItem | undefined;
let observerUsesSharedServer = false;
let agentIntegrationPromptPromise: Promise<void> | undefined;
let recentAgentIntegrationPrompts: Array<{ detail?: string; message: string }> = [];
const observerLifecycleState = createObserverLifecycleState();
let lastObserverPanelRenderKey: string | undefined;

const observerPanelViewType = 'observabilityStudioObserver';
const sharedObserverUrlSetting = 'sharedObserverUrl';
const managedObserverPortSetting = 'managedObserverPort';
const managedObserverHost = '127.0.0.1';
const defaultManagedObserverPort = 3000;
const observerKind = 'obstudio';
const observerAPIVersion = 'v1';
const agentIntegrationPromptDismissedPrefix = 'agentIntegrationPromptDismissed.';
const agentSkillsBundleVersionPrefix = 'agentSkillsBundleVersion.';

// The extension exposes a stable OTLP endpoint so instrumented apps can target a
// predictable localhost port.
const observerOtlpHttpPort = 4318;
const observerOtlpGrpcPort = 4317;
const observerOtlpHttpEndpoint = `http://${managedObserverHost}:${observerOtlpHttpPort}`;
const observerOtlpGrpcEndpoint = `${managedObserverHost}:${observerOtlpGrpcPort}`;

type InternalRuntimeState = {
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

type AgentIntegrationTarget = 'claude-code' | 'codex' | 'cursor';

type AgentIntegrationConfigFormat = 'json' | 'toml';

type AgentIntegrationSpec = {
	configFormat: AgentIntegrationConfigFormat;
	configPath: (home: string) => string;
	detectPaths: (home: string) => string[];
	label: string;
	skillsSentinelPath: (home: string) => string;
	target: AgentIntegrationTarget;
};

type AgentIntegrationConfigState = 'different' | 'matching' | 'missing';

type ObserverProbeOptions = {
	requireStableOtlp: boolean;
};

type ObserverProbeResult =
	| { health: ObserverHealth; status: 'ready' }
	| { error: Error; status: 'unavailable' }
	| { reason: string; status: 'mismatch' };

type PortReservation = {
	port: number;
	role: ObserverPortRole;
	settingName?: string;
};

type StartupHintCarrier = {
	startupHint?: string;
};

const agentIntegrationSpecs: AgentIntegrationSpec[] = [
	{
		target: 'codex',
		label: 'Codex',
		configFormat: 'toml',
		configPath: (home) => path.join(home, '.codex', 'config.toml'),
		detectPaths: (home) => [path.join(home, '.codex')],
		skillsSentinelPath: (home) => path.join(home, '.codex', 'skills', 'otel-instrument', 'SKILL.md'),
	},
	{
		target: 'claude-code',
		label: 'Claude Code',
		configFormat: 'json',
		configPath: (home) => path.join(home, '.claude.json'),
		detectPaths: (home) => [path.join(home, '.claude'), path.join(home, '.claude.json')],
		skillsSentinelPath: (home) => path.join(home, '.claude', 'skills', 'otel-instrument', 'SKILL.md'),
	},
	{
		target: 'cursor',
		label: 'Cursor',
		configFormat: 'json',
		configPath: (home) => path.join(home, '.cursor', 'mcp.json'),
		detectPaths: (home) => [path.join(home, '.cursor')],
		skillsSentinelPath: (home) => path.join(home, '.cursor', 'skills', 'otel-instrument', 'SKILL.md'),
	},
];

export async function activate(context: vscode.ExtensionContext) {
	observerOutputChannel = vscode.window.createOutputChannel('Splunk Observability Studio');
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
					void maybeOfferDetectedAgentIntegrations(context);
				} catch {
					refreshObserverPanel();
				}
			},
		}),
	);
	context.subscriptions.push(vscode.workspace.onDidChangeConfiguration((event) => {
		if (
			!event.affectsConfiguration(`observability-studio.${sharedObserverUrlSetting}`)
			&& !event.affectsConfiguration(`observability-studio.${managedObserverPortSetting}`)
		) {
			return;
		}
		void restartObserver(context);
	}));

	// Status bar item reflects observer state and opens the observer menu.
	observerStatusBarItem = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Right, 100);
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
		void vscode.window.showErrorMessage(`Splunk Observability Studio could not start: ${message}`);
	});
	void ensureObserverRunning(context)
		.then(() => maybeOfferDetectedAgentIntegrations(context))
		.catch((error) => {
			if (isObserverLifecycleCancelled(error)) {
				return;
			}
			logObserverLifecycle(`Skipping automatic agent integration prompt: ${getErrorMessage(error)}`);
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
				{
					placeHolder: observerUsesSharedServer
						? `Observer is reusing ${observerBaseUrl ?? 'a shared backend'}`
						: `Observer is running at ${observerBaseUrl ?? `http://${managedObserverHost}:${observerLifecycleState.port ?? '?'}`}`,
				},
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
			void maybeOfferDetectedAgentIntegrations(context);
		} catch (error) {
			if (isObserverLifecycleCancelled(error)) {
				refreshObserverPanel();
				return;
			}
			const message = getErrorMessage(error);
			void vscode.window.showErrorMessage(`Splunk Observability Studio could not start: ${message}`);
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
			void maybeOfferDetectedAgentIntegrations(context);
		} catch (error) {
			if (isObserverLifecycleCancelled(error)) {
				refreshObserverPanel();
				return;
			}
			const message = getErrorMessage(error);
			void vscode.window.showErrorMessage(`Splunk Observability Studio could not start: ${message}`);
			refreshObserverPanel();
		}
	});
	const configureCodexDisposable = vscode.commands.registerCommand(
		'observability-studio.configureCodexMCP',
		() => configureAgentMCP(context, 'codex', 'Codex'),
	);
	const configureClaudeDisposable = vscode.commands.registerCommand(
		'observability-studio.configureClaudeCodeMCP',
		() => configureAgentMCP(context, 'claude-code', 'Claude Code'),
	);
	const configureCursorDisposable = vscode.commands.registerCommand(
		'observability-studio.configureCursorMCP',
		() => configureAgentMCP(context, 'cursor', 'Cursor'),
	);
	const internalConfigureDetectedAgentsDisposable = vscode.commands.registerCommand(
		'observability-studio.internal.configureDetectedAgentIntegrations',
		() => configureDetectedAgentIntegrations(context),
	);
	const internalGetAgentIntegrationPromptsDisposable = vscode.commands.registerCommand(
		'observability-studio.internal.getAgentIntegrationPrompts',
		() => recentAgentIntegrationPrompts.map((item) => ({ ...item })),
	);
	const internalClearAgentIntegrationPromptsDisposable = vscode.commands.registerCommand(
		'observability-studio.internal.clearAgentIntegrationPrompts',
		() => {
			recentAgentIntegrationPrompts = [];
		},
	);
	const internalResetAgentIntegrationPromptStateDisposable = vscode.commands.registerCommand(
		'observability-studio.internal.resetAgentIntegrationPromptState',
		async () => {
			agentIntegrationPromptPromise = undefined;
			recentAgentIntegrationPrompts = [];
			for (const spec of agentIntegrationSpecs) {
				await context.globalState.update(integrationPromptDismissalKey(spec.target), undefined);
				await context.globalState.update(`${agentSkillsBundleVersionPrefix}${spec.target}`, undefined);
			}
		},
	);
	const internalStateDisposable = vscode.commands.registerCommand(
		'observability-studio.internal.getRuntimeState',
		(): InternalRuntimeState => ({
			observerPort: observerLifecycleState.port,
			observerUrl: observerBaseUrl,
			panelHtml: observerPanel?.webview.html,
			panelVisible: observerPanel !== undefined,
			sharedMode: observerUsesSharedServer,
			statusBarCommand: getStatusBarCommandId(observerStatusBarItem),
			statusBarPresent: observerStatusBarItem !== undefined,
			statusBarText: observerStatusBarItem?.text,
			validatorSummaryUrl: observerBaseUrl === undefined
				? undefined
				: buildObserverValidatorSummaryUrl(observerBaseUrl),
		}),
	);

	context.subscriptions.push(openObserverDisposable);
	context.subscriptions.push(statusMenuDisposable);
	context.subscriptions.push(startDisposable);
	context.subscriptions.push(stopDisposable);
	context.subscriptions.push(restartDisposable);
	context.subscriptions.push(configureCodexDisposable);
	context.subscriptions.push(configureClaudeDisposable);
	context.subscriptions.push(configureCursorDisposable);
	context.subscriptions.push(internalConfigureDetectedAgentsDisposable);
	context.subscriptions.push(internalGetAgentIntegrationPromptsDisposable);
	context.subscriptions.push(internalClearAgentIntegrationPromptsDisposable);
	context.subscriptions.push(internalResetAgentIntegrationPromptStateDisposable);
	context.subscriptions.push(internalStateDisposable);
	context.subscriptions.push(observerStatusBarItem);
	context.subscriptions.push({
		dispose: () => {
			disposeObserverForExtensionUnload('Extension disposed');
		},
	});
}

export async function deactivate(): Promise<void> {
	await shutdownObserverForExtensionUnload('Extension deactivated');
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
	if (observerLifecycleState.status === 'running' && observerBaseUrl !== undefined) {
		logObserverLifecycle(`Start requested while observer is already running at ${observerBaseUrl}.`);
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
		if (observerOutputChannel === undefined) {
			throw new Error('Observer output channel is not initialized.');
		}

		const sharedObserverUrl = getConfiguredSharedObserverUrl();
		if (sharedObserverUrl !== undefined) {
			observerUsesSharedServer = true;
			observerBaseUrl = sharedObserverUrl;
			appendObserverOutputLine(`Using configured shared observer at ${sharedObserverUrl}`);
			syncObserverUi();
			await waitForObserverReady(sharedObserverUrl, { requireStableOtlp: false }, runId);
			const sharedPort = observerPortFromUrl(sharedObserverUrl);
			if (sharedPort === undefined) {
				throw new Error(`Observer URL does not resolve to a usable port: ${sharedObserverUrl}`);
			}
			if (completeObserverStart(observerLifecycleState, runId, sharedPort)) {
				syncObserverUi();
			}
			return;
		}

		const managedPort = getConfiguredManagedObserverPort();
		const managedObserverBaseUrl = buildManagedObserverBaseUrl(managedPort);
		const existingObserver = await probeObserver(managedObserverBaseUrl, 500, { requireStableOtlp: true });
		assertObserverRunCurrent(observerLifecycleState, runId);

		if (existingObserver.status === 'ready') {
			observerUsesSharedServer = true;
			observerBaseUrl = managedObserverBaseUrl;
			appendObserverOutputLine(`Reusing shared observer at ${managedObserverBaseUrl}`);
			if (completeObserverStart(observerLifecycleState, runId, managedPort)) {
				syncObserverUi();
			}
			return;
		}

		if (existingObserver.status === 'mismatch') {
			appendObserverOutputLine(`Observer health probe mismatch at ${managedObserverBaseUrl}: ${existingObserver.reason}`);
			logObserverLifecycle(`Run ${runId}: existing service on ${managedObserverBaseUrl} did not match observer health: ${existingObserver.reason}`);
			const wrappedError = new Error(
				`Cannot use ${managedObserverBaseUrl}: ${formatObserverProbeMismatchMessage(managedObserverBaseUrl, 'managed-reuse')} ` +
				`Stop the conflicting service or configure observability-studio.${managedObserverPortSetting} ` +
				`or observability-studio.${sharedObserverUrlSetting}.`,
			);
			Object.assign(wrappedError, { startupHint: getObserverProbeMismatchHint('managed-reuse') });
			throw wrappedError;
		}

		const backend = resolveBackend(context.extensionPath);
		let observerPort: number;
		try {
			observerPort = await ensurePortAvailable({
				port: managedPort,
				role: 'Observer UI',
				settingName: managedObserverPortSetting,
			});
		} catch (error) {
			const wrappedError = new Error(
				`Cannot use ${managedObserverBaseUrl}: ${getErrorMessage(error)} ` +
				`Configure observability-studio.${managedObserverPortSetting} or ` +
				`observability-studio.${sharedObserverUrlSetting}.`,
			);
			if (typeof error === 'object' && error !== null && typeof (error as StartupHintCarrier).startupHint === 'string') {
				Object.assign(wrappedError, { startupHint: (error as StartupHintCarrier).startupHint });
			}
			throw wrappedError;
		}
		logObserverLifecycle(`Run ${runId}: reserved UI port ${observerPort}.`);
		assertObserverRunCurrent(observerLifecycleState, runId);

		const otlpHttpPort = await ensurePortAvailable({
			port: observerOtlpHttpPort,
			role: 'OTLP/HTTP',
		});
		assertObserverRunCurrent(observerLifecycleState, runId);
		const otlpGrpcPort = await ensurePortAvailable({
			port: observerOtlpGrpcPort,
			role: 'OTLP/gRPC',
		});
		assertObserverRunCurrent(observerLifecycleState, runId);
		logObserverLifecycle(`Run ${runId}: OTLP ports ready (HTTP ${otlpHttpPort}, gRPC ${otlpGrpcPort}).`);
		observerUsesSharedServer = false;
		observerBaseUrl = managedObserverBaseUrl;

		appendObserverOutputLine(`Starting ${backend.label} on ${managedObserverBaseUrl}`);
		appendObserverOutputLine(`OTLP/HTTP receiver listening on ${observerOtlpHttpEndpoint}`);
		appendObserverOutputLine(`OTLP/gRPC receiver listening on ${observerOtlpGrpcEndpoint}`);

		try {
			startedProcess = cp.spawn(backend.command, backend.args, {
				cwd: backend.cwd,
				env: {
					...process.env,
					...backend.env,
					HOST: managedObserverHost,
					OTLP_HOST: managedObserverHost,
					OTLP_PORT: String(otlpHttpPort),
					OTLP_HTTP_PORT: String(otlpHttpPort),
					OTLP_GRPC_PORT: String(otlpGrpcPort),
					PORT: String(observerPort),
					// Pass the workspace root so the preview resolver locates
					// .observe/dashboards.preview.json relative to the open
					// workspace rather than the binary's install directory.
					...(vscode.workspace.workspaceFolders?.[0]?.uri.fsPath
						? { OBSTUDIO_WORKSPACE_ROOT: vscode.workspace.workspaceFolders[0].uri.fsPath }
						: {}),
				},
				stdio: ['ignore', 'pipe', 'pipe'],
			});
		} catch (error) {
			const startupFailure = describeObserverStartupFailure(error as NodeJS.ErrnoException, {
				arch: process.arch,
				binaryPath: backend.command,
				platform: process.platform,
			});
			const wrappedError = new Error(startupFailure.message);
			Object.assign(wrappedError, { startupHint: startupFailure.hint });
			throw wrappedError;
		}
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
				observerBaseUrl = undefined;
				observerUsesSharedServer = false;
				syncObserverUi();
			}
		});

		startedProcess.on('error', (error) => {
			const startupFailure = describeObserverStartupFailure(error, {
				arch: process.arch,
				binaryPath: backend.command,
				platform: process.platform,
			});
			const startupMessage = startupFailure.message;
			appendObserverOutputLine(`Failed to start observer: ${startupMessage}`);
			logObserverLifecycle(`Run ${runId}: observer process error: ${startupMessage}`);
			if (observerProcess === startedProcess) {
				observerProcess = undefined;
			}
			if (failObserverStart(observerLifecycleState, runId, startupMessage, startupFailure.hint)) {
				observerBaseUrl = undefined;
				observerUsesSharedServer = false;
				syncObserverUi();
				void vscode.window.showErrorMessage(`Splunk Observability Studio failed to start observer: ${startupMessage}`);
			}
		});

		await waitForObserverReady(managedObserverBaseUrl, { requireStableOtlp: true }, runId);
		logObserverLifecycle(`Run ${runId}: observer is accepting connections at ${managedObserverBaseUrl}.`);
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
		const startupMessage = getErrorMessage(error);
		const startupHint = typeof error === 'object'
			&& error !== null
			&& 'startupHint' in error
			&& typeof (error as { startupHint?: unknown }).startupHint === 'string'
			? (error as { startupHint: string }).startupHint
			: getObserverStartupHint('generic');
		if (failObserverStart(observerLifecycleState, runId, startupMessage, startupHint)) {
			observerBaseUrl = undefined;
			observerUsesSharedServer = false;
			logObserverLifecycle(`Run ${runId}: startup failed: ${startupMessage}`);
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
	if (proc === undefined && observerStartupPromise === undefined && observerBaseUrl === undefined) {
		logObserverLifecycle('Stop requested but observer is already idle.');
		return;
	}

	logObserverLifecycle(
		`Stopping observer (status=${observerLifecycleState.status}, pid=${proc?.pid ?? 'none'}, port=${observerLifecycleState.port ?? 'none'}, url=${observerBaseUrl ?? 'none'}).`,
	);
	stopObserverRun(observerLifecycleState);
	observerProcess = undefined;
	observerStartupPromise = undefined;
	observerBaseUrl = undefined;
	observerUsesSharedServer = false;
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

async function shutdownObserverForExtensionUnload(reason: string): Promise<void> {
	logObserverLifecycle(`${reason}; stopping observer process.`);
	try {
		await stopObserver();
	} catch (error) {
		logObserverLifecycle(`${reason}; observer shutdown failed: ${getErrorMessage(error)}`);
	}
}

function disposeObserverForExtensionUnload(reason: string): void {
	logObserverLifecycle(`${reason}; terminating observer process.`);
	const proc = observerProcess;
	stopObserverRun(observerLifecycleState);
	observerProcess = undefined;
	observerStartupPromise = undefined;
	observerStopPromise = undefined;
	observerBaseUrl = undefined;
	observerUsesSharedServer = false;
	syncObserverUi();
	terminateObserverProcess(proc, 'SIGTERM');
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
			'Observer – Telemetry Explorer',
			vscode.ViewColumn.One,
			{
				enableScripts: true,
				retainContextWhenHidden: true,
			},
		);
		configureObserverPanel(observerPanel, context);
	}
	applyObserverPanelPresentation(observerPanel, context);

	logObserverLifecycle('Revealing observer webview panel.');
	observerPanel.reveal(vscode.ViewColumn.One);

	// If already running, show the UI immediately.
	if (observerLifecycleState.status === 'running' && observerBaseUrl !== undefined) {
		refreshObserverPanel();
		return;
	}

	// Not running — show loading, auto-start, then show result.
	observerPanel.webview.html = getObserverLoadingWebviewHtml();
	try {
		await ensureObserverRunning(context);
		refreshObserverPanel();
		void maybeOfferDetectedAgentIntegrations(context);
	} catch {
		refreshObserverPanel();
	}
}

function configureObserverPanel(panel: vscode.WebviewPanel, context: vscode.ExtensionContext): void {
	panel.webview.options = {
		enableScripts: true,
	};
	applyObserverPanelPresentation(panel, context);
	panel.onDidDispose(() => {
		if (observerPanel === panel) {
			logObserverLifecycle('Observer webview panel disposed.');
			lastObserverPanelRenderKey = undefined;
			observerPanel = undefined;
		}
	}, undefined, context.subscriptions);
}

function applyObserverPanelPresentation(panel: vscode.WebviewPanel, context: vscode.ExtensionContext): void {
	const iconUri = vscode.Uri.joinPath(context.extensionUri, 'assets', 'observer-icon.png');
	panel.title = 'Observer – Telemetry Explorer';
	panel.iconPath = {
		light: iconUri,
		dark: iconUri,
	};
}

function refreshObserverPanel(): void {
	if (observerPanel === undefined) {
		return;
	}

	const renderKey = `${observerLifecycleState.status}:${observerLifecycleState.port ?? 'none'}:${observerLifecycleState.startupError ?? 'none'}:${observerLifecycleState.startupHint ?? 'none'}:${observerBaseUrl ?? 'none'}:${observerUsesSharedServer ? 'shared' : 'local'}`;
	if (renderKey !== lastObserverPanelRenderKey) {
		logObserverLifecycle(`Rendering observer panel state ${renderKey}.`);
		lastObserverPanelRenderKey = renderKey;
	}

	switch (observerLifecycleState.status) {
		case 'running':
			observerPanel.webview.html = observerLifecycleState.port === undefined || observerBaseUrl === undefined
				? getObserverLoadingWebviewHtml()
				: getObserverWebviewHtmlForUrl(observerBaseUrl);
			return;
		case 'error':
			observerPanel.webview.html = getObserverErrorWebviewHtml(
				observerLifecycleState.startupError ?? 'Observer could not start.',
				observerLifecycleState.startupHint ?? getObserverStartupHint('generic'),
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

async function ensurePortAvailable(reservation: PortReservation): Promise<number> {
	return new Promise((resolve, reject) => {
		const server = net.createServer();
		server.once('error', (error: NodeJS.ErrnoException) => {
			if (error.code === 'EADDRINUSE') {
				void identifyPortOwner(reservation.port).then((owner) => {
					const detail = formatPortConflictMessage({
						owner,
						port: reservation.port,
						role: reservation.role,
						settingName: reservation.settingName,
					});
					logObserverLifecycle(detail);
					const error = new Error(detail);
					Object.assign(error, { startupHint: getObserverStartupHint('port-conflict') });
					reject(error);
				});
				return;
			}
			logObserverLifecycle(`Port check failed for ${reservation.role} port ${reservation.port}: ${error.message}`);
			reject(error);
		});
		server.listen(reservation.port, '127.0.0.1', () => {
			server.close((error) => {
				if (error) { reject(error); return; }
				resolve(reservation.port);
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

async function waitForObserverReady(
	baseUrl: string,
	options: ObserverProbeOptions,
	runId: number,
): Promise<void> {
	const startupDeadline = Date.now() + 15_000;
	let lastError: Error | undefined;

	while (Date.now() < startupDeadline) {
		assertObserverRunCurrent(observerLifecycleState, runId);

		const probe = await probeObserver(baseUrl, 500, options);
		assertObserverRunCurrent(observerLifecycleState, runId);

		switch (probe.status) {
			case 'ready':
				return;
			case 'mismatch': {
				appendObserverOutputLine(`Observer health probe mismatch at ${baseUrl}: ${probe.reason}`);
				logObserverLifecycle(`Run ${runId}: observer health probe mismatch at ${baseUrl}: ${probe.reason}`);
				const mismatchContext = observerUsesSharedServer ? 'shared-reuse' : 'startup-reuse';
				const wrappedError = new Error(formatObserverProbeMismatchMessage(baseUrl, mismatchContext));
				Object.assign(wrappedError, { startupHint: getObserverProbeMismatchHint(mismatchContext) });
				throw wrappedError;
			}
			case 'unavailable':
				lastError = probe.error;
				if (!observerUsesSharedServer && observerProcess === undefined) {
					break;
				}
				await delay(100);
		}
	}

	if (lastError !== undefined) {
		const rawProbeDetail = getErrorMessage(lastError);
		appendObserverOutputLine(`Observer health probe unavailable at ${baseUrl}: ${rawProbeDetail}`);
		logObserverLifecycle(`Run ${runId}: observer readiness failed for ${baseUrl}: ${rawProbeDetail}`);
		const unavailableContext = observerUsesSharedServer ? 'shared-reuse' : 'startup';
		const wrappedError = new Error(formatObserverProbeUnavailableMessage(baseUrl, unavailableContext));
		Object.assign(wrappedError, { startupHint: getObserverProbeUnavailableHint(unavailableContext) });
		throw wrappedError;
	}
	const unavailableContext = observerUsesSharedServer ? 'shared-reuse' : 'startup';
	logObserverLifecycle(`Run ${runId}: observer readiness ended without a probe result at ${baseUrl}.`);
	const wrappedError = new Error(formatObserverProbeUnavailableMessage(baseUrl, unavailableContext));
	Object.assign(wrappedError, { startupHint: getObserverProbeUnavailableHint(unavailableContext) });
	throw wrappedError;
}

async function probeObserver(
	baseUrl: string,
	timeoutMs: number,
	options: ObserverProbeOptions,
): Promise<ObserverProbeResult> {
	return new Promise((resolve) => {
		const observerUrl = normalizeObserverBaseUrl(baseUrl);
		const target = new URL(buildObserverHealthUrl(observerUrl));
		const client = target.protocol === 'https:' ? https : http;
		let settled = false;

		const finish = (callback: () => void) => {
			if (settled) {
				return;
			}
			settled = true;
			callback();
		};

		const request = client.request(target, { method: 'GET' }, (response) => {
			let body = '';
			response.setEncoding('utf8');
			response.on('data', (chunk) => {
				body += chunk;
			});
			response.on('end', () => {
				if ((response.statusCode ?? 0) !== 200) {
					finish(() => resolve({
						status: 'mismatch',
						reason: `${target.toString()} returned status ${response.statusCode ?? 0}`,
					}));
					return;
				}

				let parsed: unknown;
				try {
					parsed = JSON.parse(body);
				} catch {
					finish(() => resolve({
						status: 'mismatch',
						reason: `${target.toString()} returned invalid JSON`,
					}));
					return;
				}

				const reason = validateObserverHealth(parsed, options);
				if (reason !== undefined) {
					finish(() => resolve({ status: 'mismatch', reason }));
					return;
				}

				finish(() => resolve({ status: 'ready', health: parsed as ObserverHealth }));
			});
		});

		request.setTimeout(timeoutMs, () => {
			request.destroy();
			finish(() => resolve({
				status: 'unavailable',
				error: new Error(`Timed out waiting for observer health on ${target.toString()}`),
			}));
		});
		request.once('error', (error: NodeJS.ErrnoException) => {
			if (error.code === 'ECONNREFUSED' || error.code === 'EHOSTUNREACH' || error.code === 'ENOTFOUND') {
				finish(() => resolve({ status: 'unavailable', error }));
				return;
			}
			finish(() => resolve({
				status: 'mismatch',
				reason: `Failed to query ${target.toString()}: ${error.message}`,
			}));
		});
		request.end();
	});
}

function validateObserverHealth(raw: unknown, options: ObserverProbeOptions): string | undefined {
	if (raw === null || typeof raw !== 'object') {
		return 'health response was not a JSON object';
	}

	const health = raw as ObserverHealth;
	if (health.kind !== observerKind) {
		return `expected kind=${observerKind}, got ${String(health.kind)}`;
	}
	if (health.apiVersion !== observerAPIVersion) {
		return `expected apiVersion=${observerAPIVersion}, got ${String(health.apiVersion)}`;
	}
	if (!options.requireStableOtlp) {
		return undefined;
	}
	if (health.endpoints?.otlpHttp !== observerOtlpHttpEndpoint) {
		return `expected OTLP/HTTP endpoint ${observerOtlpHttpEndpoint}, got ${String(health.endpoints?.otlpHttp)}`;
	}
	if (health.endpoints?.otlpGrpc !== observerOtlpGrpcEndpoint) {
		return `expected OTLP/gRPC endpoint ${observerOtlpGrpcEndpoint}, got ${String(health.endpoints?.otlpGrpc)}`;
	}
	return undefined;
}

async function restartObserver(context: vscode.ExtensionContext): Promise<void> {
	await stopObserver();
	try {
		await ensureObserverRunning(context);
		refreshObserverPanel();
		void maybeOfferDetectedAgentIntegrations(context);
	} catch (error) {
		if (isObserverLifecycleCancelled(error)) {
			refreshObserverPanel();
			return;
		}
		const message = getErrorMessage(error);
		void vscode.window.showErrorMessage(`Splunk Observability Studio could not start: ${message}`);
		refreshObserverPanel();
	}
}

function getObserverWebviewHtmlForUrl(observerUrl: string): string {
	const normalizedObserverUrl = normalizeObserverBaseUrl(observerUrl);

	return `<!DOCTYPE html>
<html lang="en">
<head>
	<meta charset="UTF-8">
	<meta
		http-equiv="Content-Security-Policy"
		content="default-src 'none'; frame-src ${normalizedObserverUrl}; style-src 'unsafe-inline'; worker-src 'none';"
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
	<iframe src="${normalizedObserverUrl}" title="Observer" sandbox="allow-scripts allow-same-origin allow-forms allow-popups"></iframe>
</body>
</html>`;
}

function delay(ms: number): Promise<void> {
	return new Promise((resolve) => { setTimeout(resolve, ms); });
}

function buildManagedObserverBaseUrl(port: number): string {
	return `http://${managedObserverHost}:${port}`;
}

function getConfiguredManagedObserverPort(): number {
	const configured = vscode.workspace.getConfiguration('observability-studio').get<number>(managedObserverPortSetting);
	if (typeof configured === 'number' && Number.isInteger(configured) && configured > 0 && configured <= 65_535) {
		if (configured === observerOtlpHttpPort || configured === observerOtlpGrpcPort) {
			const signal = configured === observerOtlpHttpPort ? 'OTLP/HTTP' : 'OTLP/gRPC';
			throw new Error(
				`observability-studio.${managedObserverPortSetting} cannot use port ${configured}; ` +
				`${signal} already uses that port.`,
			);
		}
		return configured;
	}
	return defaultManagedObserverPort;
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

function getConfiguredSharedObserverUrl(): string | undefined {
	const raw = vscode.workspace.getConfiguration('observability-studio').get<string>(sharedObserverUrlSetting);
	if (raw === undefined) {
		return undefined;
	}

	const trimmed = raw.trim();
	if (trimmed.length === 0) {
		return undefined;
	}
	return normalizeObserverBaseUrl(trimmed);
}

function getDetectedAgentIntegrations(): AgentIntegrationSpec[] {
	const home = os.homedir();
	return agentIntegrationSpecs.filter((spec) => spec.detectPaths(home).some((candidate) => fs.existsSync(candidate)));
}

function integrationPromptDismissalKey(target: AgentIntegrationTarget): string {
	return `${agentIntegrationPromptDismissedPrefix}${target}`;
}

function formatAgentLabelList(labels: string[]): string {
	if (labels.length === 0) {
		return '';
	}
	if (labels.length === 1) {
		return labels[0];
	}
	if (labels.length === 2) {
		return `${labels[0]} and ${labels[1]}`;
	}
	return `${labels.slice(0, -1).join(', ')}, and ${labels[labels.length - 1]}`;
}

function getAgentIntegrationConfigState(spec: AgentIntegrationSpec, mcpUrl: string): AgentIntegrationConfigState {
	const configPath = spec.configPath(os.homedir());
	if (!fs.existsSync(configPath)) {
		return 'missing';
	}

	try {
		if (spec.configFormat === 'json') {
			const config = JSON.parse(fs.readFileSync(configPath, 'utf8')) as {
				mcpServers?: Record<string, { type?: string; url?: string }>;
			};
			const server = config.mcpServers?.obstudio;
			if (server === undefined) {
				return 'missing';
			}
			return server.type === 'http' && server.url === mcpUrl ? 'matching' : 'different';
		}

		const content = fs.readFileSync(configPath, 'utf8');
		const section = getCodexObstudioSection(content);
		if (section === undefined) {
			return 'missing';
		}
		return section.includes(`url = "${mcpUrl}"`) ? 'matching' : 'different';
	} catch {
		return 'different';
	}
}

function getCodexObstudioSection(content: string): string | undefined {
	const lines = content.split(/\r?\n/);
	let section: string[] | undefined;
	for (const line of lines) {
		const trimmed = line.trim();
		if (trimmed.startsWith('[') && trimmed.endsWith(']')) {
			if (trimmed === '[mcp_servers.obstudio]') {
				section = [line];
				continue;
			}
			if (section !== undefined) {
				break;
			}
		}
		if (section !== undefined) {
			section.push(line);
		}
	}
	return section?.join('\n');
}

function hasInstalledAgentSkills(spec: AgentIntegrationSpec): boolean {
	return fs.existsSync(spec.skillsSentinelPath(os.homedir()));
}

function getBundleVersion(context: vscode.ExtensionContext): string {
	return context.extension.packageJSON.version as string ?? '0.0.0';
}

function getStoredSkillsBundleVersion(context: vscode.ExtensionContext, target: AgentIntegrationTarget): string | undefined {
	return context.globalState.get<string>(`${agentSkillsBundleVersionPrefix}${target}`);
}

async function recordSkillsBundleVersion(context: vscode.ExtensionContext, target: AgentIntegrationTarget): Promise<void> {
	await context.globalState.update(`${agentSkillsBundleVersionPrefix}${target}`, getBundleVersion(context));
}

function skillsBundleVersionChanged(context: vscode.ExtensionContext, target: AgentIntegrationTarget): boolean {
	const stored = getStoredSkillsBundleVersion(context, target);
	// Treat a missing stored version as "not changed": skills may have been
	// installed by an older extension version that predates this feature.
	// We only re-prompt on an explicit version change (stored → new value).
	if (stored === undefined) {
		return false;
	}
	return stored !== getBundleVersion(context);
}

function needsAgentIntegrationUpdate(spec: AgentIntegrationSpec, mcpUrl: string, context?: vscode.ExtensionContext): boolean {
	if (getAgentIntegrationConfigState(spec, mcpUrl) !== 'matching') {
		return true;
	}
	if (!hasInstalledAgentSkills(spec)) {
		return true;
	}
	// Re-install skills when the extension bundle version has changed since the
	// last successful install, so updated skill files are always deployed.
	if (context !== undefined && skillsBundleVersionChanged(context, spec.target)) {
		return true;
	}
	return false;
}

async function configureDetectedAgentIntegrations(
	context: vscode.ExtensionContext,
	specs = getDetectedAgentIntegrations(),
	showSuccessMessage = true,
	forceAll = false,
): Promise<string[]> {
	await ensureObserverRunning(context);
	if (observerBaseUrl === undefined) {
		throw new Error('Observer URL is not available.');
	}

	const mcpUrl = `${normalizeObserverBaseUrl(observerBaseUrl)}/mcp`;
	const configured: string[] = [];
	for (const spec of specs) {
		if (!forceAll && !needsAgentIntegrationUpdate(spec, mcpUrl, context)) {
			continue;
		}

		await configureAgentMCP(context, spec.target, spec.label, false);
		configured.push(spec.label);
	}

	if (showSuccessMessage && configured.length > 0) {
		const labelList = formatAgentLabelList(configured);
		const noun = configured.length === 1 ? 'integration' : 'integrations';
		void vscode.window.showInformationMessage(
			`${labelList} ${noun} enabled. Restart ${labelList} to load the bundled skills.`,
		);
	}
	return configured;
}

async function maybeOfferDetectedAgentIntegrations(context: vscode.ExtensionContext): Promise<void> {
	if (agentIntegrationPromptPromise !== undefined) {
		return agentIntegrationPromptPromise;
	}

	const promptPromise = (async () => {
		if (observerBaseUrl === undefined) {
			return;
		}

		const mcpUrl = `${normalizeObserverBaseUrl(observerBaseUrl)}/mcp`;
		const shownSpecs = getDetectedAgentIntegrations().filter((spec) => {
			const dismissed = context.globalState.get<boolean>(integrationPromptDismissalKey(spec.target)) === true;
			if (!dismissed) {
				return true;
			}
			return getAgentIntegrationConfigState(spec, mcpUrl) !== 'missing';
		});
		if (shownSpecs.length === 0) {
			return;
		}
		const needsUpdate = shownSpecs.some((spec) => needsAgentIntegrationUpdate(spec, mcpUrl, context));
		if (!needsUpdate) {
			return;
		}

		const labels = shownSpecs.map((spec) => spec.label);
		const labelList = formatAgentLabelList(labels);
		const promptMessage = shownSpecs.length === 1
			? `Enable ${labels[0]} integration for Splunk Observability Studio?`
			: 'Enable detected agent integrations for Splunk Observability Studio?';
		const promptDetail = shownSpecs.length === 1
			? `Install bundled skills and configure ${labels[0]} to use the local Observer at ${mcpUrl}.`
			: `Install bundled skills and configure ${labelList} to use the local Observer at ${mcpUrl}.`;
		recentAgentIntegrationPrompts = [...recentAgentIntegrationPrompts.slice(-9), {
			detail: promptDetail,
			message: promptMessage,
		}];
		const choice = await vscode.window.showInformationMessage(
			promptMessage,
			{ detail: promptDetail },
			'Enable',
			'Not Now',
		);
		if (choice === 'Enable') {
			await configureDetectedAgentIntegrations(context, shownSpecs, true, true);
			return;
		}
		if (choice === 'Not Now') {
			for (const spec of shownSpecs) {
				await context.globalState.update(integrationPromptDismissalKey(spec.target), true);
			}
			logObserverLifecycle(`${labelList} integration prompt dismissed.`);
		}
	})().catch((error) => {
		appendObserverOutputLine(`Automatic agent integration check failed: ${getErrorMessage(error)}`);
	}).finally(() => {
		if (agentIntegrationPromptPromise === promptPromise) {
			agentIntegrationPromptPromise = undefined;
		}
	});

	agentIntegrationPromptPromise = promptPromise;
	return promptPromise;
}

async function configureAgentMCP(
	context: vscode.ExtensionContext,
	target: AgentIntegrationTarget,
	label: string,
	showSuccessMessage = true,
): Promise<void> {
	if (observerOutputChannel === undefined) {
		throw new Error('Observer output channel is not initialized.');
	}

	try {
		await ensureObserverRunning(context);
		if (observerBaseUrl === undefined) {
			throw new Error('Observer URL is not available.');
		}

		const mcpUrl = `${normalizeObserverBaseUrl(observerBaseUrl)}/mcp`;
		const backend = resolveBackend(context.extensionPath);
		observerOutputChannel.appendLine(`Enabling ${label} integration for ${mcpUrl}`);
		await execFile(backend.command, ['install', '--target', target, '--shared-url', mcpUrl], backend.cwd);
		await context.globalState.update(integrationPromptDismissalKey(target), undefined);
		// Record the bundle version so that future version changes trigger a re-install.
		await recordSkillsBundleVersion(context, target);
		observerOutputChannel.appendLine(`${label} integration enabled for ${mcpUrl}`);
		if (showSuccessMessage) {
			void vscode.window.showInformationMessage(
				`${label} integration enabled. Restart ${label} to load the bundled skills.`,
			);
		}
	} catch (error) {
		const message = `${label} integration failed: ${getErrorMessage(error)}`;
		observerOutputChannel.appendLine(message);
		void vscode.window.showErrorMessage(message);
		throw error;
	}
}

function execFile(command: string, args: string[], cwd: string): Promise<void> {
	return new Promise((resolve, reject) => {
		cp.execFile(command, args, { cwd, env: { ...process.env } }, (error) => {
			if (error) {
				reject(error);
				return;
			}
			resolve();
		});
	});
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

function getStatusBarCommandId(item: vscode.StatusBarItem | undefined): string | undefined {
	const command = item?.command;
	if (typeof command === 'string') {
		return command;
	}
	return command?.command;
}
