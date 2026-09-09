import * as cp from 'node:child_process';
import * as crypto from 'node:crypto';
import * as fs from 'node:fs';
import * as http from 'node:http';
import * as https from 'node:https';
import * as net from 'node:net';
import * as os from 'node:os';
import * as path from 'node:path';
import * as vscode from 'vscode';
import {
	createAgentIntegrationConfigFingerprint,
	codexObstudioHasNoAuthorization,
	getCodexObstudioSection,
	getCodexObstudioUrl,
	hasNoAuthorizationHeader,
	shouldRefreshOwnedAgentIntegrationConfig,
	type AgentIntegrationConfigFingerprint,
	type AgentIntegrationManagedConfig,
} from './agent-integration-config';
import {
	buildObserverHealthUrl,
	buildObserverValidatorSummaryUrl,
	findOtherExtensionManagedObserver,
	findOtherExtensionObserverExecutable,
	isLoopbackObserverHost,
	type ObserverHealth,
	type SharedObserverDiscovery,
	normalizeObserverBaseUrl,
	normalizeSharedObserverBaseUrl,
	normalizeSharedObserverHealthUrl,
	normalizeSharedObserverMCPUrl,
	observerPortFromUrl,
	readSharedObserverDiscovery,
	resolveBackend,
} from './backend';
import {
	AsyncOperationQueue,
	AsyncSingleFlight,
	assertObserverRunCurrent,
	beginObserverStart,
	completeObserverStart,
	createObserverLifecycleState,
	failObserverStart,
	finishObserverRun,
	isObserverLifecycleCancelled,
	isObserverRunCurrent,
	operationCompletesWithin,
	stopObserverRun,
} from './observer-lifecycle';
import {
	getObserverErrorWebviewHtml,
	getObserverLoadingWebviewHtml,
	getObserverStoppedWebviewHtml,
	getObserverWebviewHtml,
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
import {
	auditReportUrl,
	cloudBridgeActionRequiresLifecycleSerialization,
	cloudStatusConnected,
	connectSplunkCloudWithStorage,
	forgetSplunkCloudWithStorage,
	freeAccountSubmissionFailureIsOutcomeUnknown,
	initializeSplunkCloudStatus,
	isSupportedFreeAccountRegion,
	maxCloudDestinationBytes,
	observerCloudResponseError,
	parseFreeAccountSubmissionResult,
	parseObserverCloudResponseBody,
	parseStoredSplunkCloudConnection,
	restoreSplunkCloudConnectionFromStorage,
	setSplunkCloudExportEnabledWithStorage,
	skillDocsUrl,
	ObserverCloudResponseError,
	SplunkCloudConnectionStore,
	SplunkCloudExportPreferenceStore,
	splunkCloudConnectionSecretKey,
	verifyStoredSplunkCloudConnection,
	writeSplunkCloudStatePair,
	type CloudBridgeAction,
	type StoredSplunkCloudConnection,
} from './cloud-bridge';
import {
	collectObserverHostHTTPResponse,
	isObserverHostCancelEnvelope,
	isObserverHostRequestEnvelope,
	isObserverHostTelemetryEnvelope,
	observerHostResponseByteLimit,
	type ObserverHostCloudPayload,
	type ObserverHostRequest,
	type ObserverHostResponseEnvelope,
} from './observer-webview-host';
import { ObserverWebviewTelemetry } from './observer-webview-telemetry';
import {
	forceTerminateProcess,
	processIsRunning,
	readProcessExecutablePath,
} from './process-control';
import {
	authorizeWithSISCIMD,
	computeSISCIMDSessionStatus,
	deleteSISCIMDOAuthSession,
	loadStoredSISCIMDOAuthSession,
	registerClientWithSIS,
	sisCIMDOAuthRedirectUri,
	storeSISCIMDOAuthSession,
	type SISCIMDOAuthConfiguration,
	type SISCIMDOAuthSession,
	type SISCIMDSessionStatus,
} from './sis-cimd-oauth';

// Extension-global observer state. The extension hosts one local observer process
// and optionally one WebView panel that embeds its UI.
let observerProcess: cp.ChildProcess | undefined;
let observerOutputChannel: vscode.OutputChannel | undefined;
let observerPanel: vscode.WebviewPanel | undefined;
let observerEndpoints: ObserverEndpointRoles | undefined;
let observerBaseUrl: string | undefined;
let observerStartupPromise: Promise<void> | undefined;
let observerConfigurationRestartOperation: Promise<void> | undefined;
const observerStopOperation = new AsyncSingleFlight();
const observerCloudLifecycleOperations = new AsyncOperationQueue();
const splunkCloudConnectionStore = new SplunkCloudConnectionStore();
const splunkCloudExportPreferenceStore = new SplunkCloudExportPreferenceStore();
let observerStatusBarItem: vscode.StatusBarItem | undefined;
let observerUsesSharedServer = false;
let observerWebviewRootUri: vscode.Uri | undefined;
let observerPanelTelemetry: ObserverWebviewTelemetry | undefined;
let observerDeactivationStarted = false;
const observerHostRequestCancellations = new Map<string, () => void>();
let sisCIMDOAuthFlowPromise: Promise<boolean> | undefined;
let sisCIMDOAuthAbortController: AbortController | undefined;
let agentIntegrationPromptPromise: Promise<void> | undefined;
let agentIntegrationPromptGeneration = 0;
const agentIntegrationPromptInstallOperations = new Set<Promise<string[]>>();
const agentIntegrationConfigurationQueue = new AsyncOperationQueue();
const agentIntegrationConfigurationOperations = new Set<Promise<boolean>>();
const agentIntegrationConfigFingerprints = new Map<AgentIntegrationTarget, AgentIntegrationConfigFingerprint>();
let agentIntegrationPromptMcpUrl: string | undefined;
let agentIntegrationRefreshOperation: { key: string; promise: Promise<string[]> } | undefined;
let recentAgentIntegrationPrompts: Array<{ detail?: string; message: string }> = [];
const observerLifecycleState = createObserverLifecycleState();
let lastObserverPanelRenderKey: string | undefined;

const observerPanelViewType = 'observabilityStudioObserver';
const sharedObserverUrlSetting = 'sharedObserverUrl';
const managedObserverPortSetting = 'managedObserverPort';
const sisCimdRegistrationEnabledSetting = 'sisCimdRegistrationEnabled';
const sisCimdOAuthIssuerSetting = 'sisCimdOAuthIssuer';
const sisCimdOAuthClientIdSetting = 'sisCimdOAuthClientId';
const sisCimdOAuthRedirectUriSetting = 'sisCimdOAuthRedirectUri';
const sisCimdOAuthScopeSetting = 'sisCimdOAuthScope';
const sisCimdOAuthDevelopmentCaBundlePathSetting = 'sisCimdOAuthDevelopmentCaBundlePath';
// TODO(CIMD PoC): This is a single hardcoded default issuer/client-id pair, good enough for
// one local SIS instance and one demo tenant. Evaluate whether we need a real discovery step
// (realm/tenant selection, geo-IP-based realm resolution per the PRD) before this goes beyond PoC.
const sisCimdOAuthDefaultIssuer = 'https://127.0.0.1:9090/test-tenant/sis/v1/rg/cimd-demo';
const sisCimdOAuthDefaultClientId = 'https://127.0.0.1:9192/oauth/client-metadata.json';
const managedObserverHost = '127.0.0.1';
const defaultManagedObserverPort = 3000;
const managedObserverStateFileName = 'managed-control.json';
const observerKind = 'obstudio';
const observerAPIVersion = 'v1';
const sharedObserverStartupWindowMs = 15_000;
const observerCloudRequestTimeoutMs = 15_000;
const observerCloudRollbackTokenHeader = 'X-Obstudio-Cloud-Rollback-Token';
const observerShutdownTerminationTimeoutMs = 2_000;
const observerShutdownPostExitDelayMs = 300;
const observerExtensionUnloadDeadlineMs = 4_500;
const outdatedExtensionObserverShutdownTimeoutMs = 5_000;
const outdatedExtensionObserverForceShutdownTimeoutMs = 2_000;
const agentIntegrationPromptDismissedPrefix = 'agentIntegrationPromptDismissed.';
const agentSkillsBundleVersionPrefix = 'agentSkillsBundleVersion.';
const agentIntegrationConfigFingerprintPrefix = 'agentIntegrationConfigFingerprint.v1.';
const splunkCloudExportEnabledStateKey = 'splunkCloudExportEnabled.v1';
const freeAccountRequestTimeoutMs = 30_000;

// The extension exposes a stable OTLP endpoint so instrumented apps can target a
// predictable localhost port.
const defaultObserverOtlpHttpPort = 4318;
const defaultObserverOtlpGrpcPort = 4317;
let observerOtlpHttpPort = defaultObserverOtlpHttpPort;
let observerOtlpGrpcPort = defaultObserverOtlpGrpcPort;
let observerOtlpHttpEndpoint = `http://${managedObserverHost}:${observerOtlpHttpPort}`;
let observerOtlpGrpcEndpoint = `${managedObserverHost}:${observerOtlpGrpcPort}`;
const splunkFreeEditionUrl = 'https://www.splunk.com/en_us/download/observability-cloud-free-edition.html';
const splunkFreeEditionTermsUrl = 'https://www.splunk.com/en_us/legal/splunk-observability-free-edition-terms.html';
const splunkRealmHelpUrl = 'https://help.splunk.com/en/splunk-observability-cloud/administer/org-reference-info/view-your-realm-api-endpoints-and-organization';
const splunkIngestTokenHelpUrl = 'https://help.splunk.com/en/splunk-observability-cloud/administer/authentication-and-security/authentication-tokens/org-access-tokens';
const splunkObservabilityDocsUrl = 'https://docs.splunk.com/Observability/get-started/welcome.html#nav-Welcome-to-Splunk-Observability-Cloud';
const splunkObservabilityCloudDemoUrl = 'https://www.splunk.com/en_us/resources/videos/watch-splunks-observability-cloud-demo.html';
const splunkObservabilityDataCourseUrl = 'https://education.splunk.com/elearning/getting-data-into-splunk-observability-cloud-elearning';

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

type AgentIntegrationTarget = 'claude-code' | 'codex' | 'cursor' | 'kiro';

type AgentIntegrationConfigFormat = 'json' | 'toml';

type AgentIntegrationSpec = {
	configFormat: AgentIntegrationConfigFormat;
	configPath: (home: string) => string;
	detectPaths: (home: string) => string[];
	jsonRemoteIncompatibleFields?: ReadonlyArray<'args' | 'command'>;
	jsonRemoteType?: 'http';
	label: string;
	skillsSentinelPath: (home: string) => string;
	target: AgentIntegrationTarget;
};

type AgentIntegrationConfigState = 'different' | 'matching' | 'missing';

type ObserverEndpointRoles = {
	healthUrl: string;
	mcpUrl: string;
	restBaseUrl: string;
};

function observerEndpointRolesForBase(baseUrl: string): ObserverEndpointRoles {
	const restBaseUrl = normalizeSharedObserverBaseUrl(baseUrl);
	return {
		restBaseUrl,
		healthUrl: normalizeSharedObserverHealthUrl(buildObserverHealthUrl(restBaseUrl)),
		mcpUrl: normalizeSharedObserverMCPUrl(`${restBaseUrl}/mcp`),
	};
}

function observerEndpointRolesForDiscovery(
	discovery: SharedObserverDiscovery,
	restBaseUrl = discovery.baseUrl,
): ObserverEndpointRoles {
	const defaults = observerEndpointRolesForBase(restBaseUrl);
	return {
		...defaults,
		...(discovery.healthUrl === undefined ? {} : { healthUrl: discovery.healthUrl }),
		...(discovery.mcpUrl === undefined ? {} : { mcpUrl: discovery.mcpUrl }),
	};
}

function sharedDiscoveryMatchesRestBase(
	discovery: SharedObserverDiscovery,
	restBaseUrl: string,
): boolean {
	const discoveredBaseUrl = normalizeSharedObserverBaseUrl(discovery.baseUrl);
	const intendedBaseUrl = normalizeSharedObserverBaseUrl(restBaseUrl);
	if (discoveredBaseUrl === intendedBaseUrl) {
		return true;
	}
	const discovered = new URL(discoveredBaseUrl);
	const intended = new URL(intendedBaseUrl);
	const localAlias = (hostname: string) => hostname === 'localhost' || hostname === '127.0.0.1';
	const effectivePort = (value: URL) => value.port || (value.protocol === 'https:' ? '443' : '80');
	return localAlias(discovered.hostname)
		&& localAlias(intended.hostname)
		&& discovered.protocol === intended.protocol
		&& effectivePort(discovered) === effectivePort(intended)
		&& discovered.pathname === intended.pathname;
}

function readManagedObserverDiscovery(): SharedObserverDiscovery | undefined {
	const homeDir = os.homedir();
	return readSharedObserverDiscovery(
		homeDir,
		path.join(homeDir, '.obstudio', managedObserverStateFileName),
	);
}

function preferredObserverDiscoveryForBase(
	restBaseUrl: string,
	...discoveries: Array<SharedObserverDiscovery | undefined>
): SharedObserverDiscovery | undefined {
	const matching = discoveries.filter(
		(discovery): discovery is SharedObserverDiscovery => discovery !== undefined
			&& sharedDiscoveryMatchesRestBase(discovery, restBaseUrl),
	);
	return matching[0];
}

function setObserverEndpoints(endpoints: ObserverEndpointRoles | undefined): void {
	observerEndpoints = endpoints;
	observerBaseUrl = endpoints?.restBaseUrl;
}

type ObserverProbeOptions = {
	requireStableOtlp: boolean;
};

type ObserverProbeResult =
	| {
		health: ObserverHealth;
		status: 'ready';
	}
	| { error: Error; status: 'unavailable' }
	| { reason: string; status: 'mismatch' };

type PortReservation = {
	port: number;
	role: ObserverPortRole;
	settingName?: string;
};

type StartupHintCarrier = {
	startupHint?: string;
	startupTitle?: string;
};

type OtherExtensionObserverRetirement =
	| { status: 'not-applicable' }
	| { pid: number; port?: number; status: 'restart-required'; version?: string }
	| { status: 'retired' };

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
		jsonRemoteType: 'http',
		skillsSentinelPath: (home) => path.join(home, '.claude', 'skills', 'otel-instrument', 'SKILL.md'),
	},
	{
		target: 'cursor',
		label: 'Cursor',
		configFormat: 'json',
		configPath: (home) => path.join(home, '.cursor', 'mcp.json'),
		detectPaths: (home) => [path.join(home, '.cursor')],
		jsonRemoteType: 'http',
		skillsSentinelPath: (home) => path.join(home, '.cursor', 'skills', 'otel-instrument', 'SKILL.md'),
	},
	{
		target: 'kiro',
		label: 'Kiro',
		configFormat: 'json',
		configPath: (home) => path.join(home, '.kiro', 'settings', 'mcp.json'),
		detectPaths: (home) => [path.join(home, '.kiro')],
		jsonRemoteIncompatibleFields: ['command', 'args'],
		skillsSentinelPath: (home) => path.join(home, '.kiro', 'skills', 'otel-instrument', 'SKILL.md'),
	},
];

export async function activate(context: vscode.ExtensionContext) {
	observerDeactivationStarted = false;
	observerOutputChannel = vscode.window.createOutputChannel('Splunk Observability Studio');
	context.subscriptions.push(observerOutputChannel);
	logObserverLifecycle(`Extension ${getBundleVersion(context)} activated.`);

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
		void enqueueObserverConfigurationRestart(context).catch((error) => {
			logObserverLifecycle(`Observer configuration restart failed: ${getErrorMessage(error)}`);
		});
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
		await settleObserverConfigurationRestart();
		if (observerLifecycleState.status === 'running') {
			void vscode.window.showInformationMessage('Observer is already running.');
		}
		if (observerLifecycleState.status === 'starting') {
			void vscode.window.showInformationMessage('Observer is already starting.');
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
		await settleObserverConfigurationRestart();
		if (
			observerProcess === undefined
			&& observerStartupPromise === undefined
			&& observerBaseUrl === undefined
		) {
			void vscode.window.showInformationMessage('Observer is not running.');
			return;
		}
		await stopObserver();
		void vscode.window.showInformationMessage('Observer stopped.');
	});

	const restartDisposable = vscode.commands.registerCommand('observability-studio.restartObserver', async () => {
		await settleObserverConfigurationRestart();
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

	const signInToSISWithCIMDDisposable = vscode.commands.registerCommand(
		'observability-studio.signInToSISWithCIMD',
		() => runSISCIMDOAuthCommand(context),
	);

	const clearSISSessionDisposable = vscode.commands.registerCommand(
		'observability-studio.clearSISSession',
		() => clearSISSession(context),
	);

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
	const configureKiroDisposable = vscode.commands.registerCommand(
		'observability-studio.configureKiroMCP',
		() => configureAgentMCP(context, 'kiro', 'Kiro'),
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
			agentIntegrationPromptGeneration += 1;
			while (agentIntegrationPromptInstallOperations.size > 0) {
				await Promise.allSettled([...agentIntegrationPromptInstallOperations]);
			}
			await waitForAgentIntegrationConfigurationCompletion();
			await waitForObserverConfigurationRestartCompletion().catch(() => undefined);
			agentIntegrationPromptGeneration += 1;
			while (agentIntegrationPromptInstallOperations.size > 0) {
				await Promise.allSettled([...agentIntegrationPromptInstallOperations]);
			}
			await waitForAgentIntegrationConfigurationCompletion();
			await waitForAgentIntegrationRefreshCompletion().catch(() => undefined);
			await waitForAgentIntegrationConfigurationCompletion();
			agentIntegrationPromptPromise = undefined;
			agentIntegrationPromptMcpUrl = undefined;
			recentAgentIntegrationPrompts = [];
			agentIntegrationConfigFingerprints.clear();
			for (const spec of agentIntegrationSpecs) {
				await context.globalState.update(integrationPromptDismissalKey(spec.target), undefined);
				await context.globalState.update(`${agentSkillsBundleVersionPrefix}${spec.target}`, undefined);
				await context.globalState.update(agentIntegrationConfigFingerprintKey(spec.target), undefined);
			}
		},
	);
	const internalWaitForAgentIntegrationRefreshDisposable = vscode.commands.registerCommand(
		'observability-studio.internal.waitForAgentIntegrationRefresh',
		async () => {
			await waitForAgentIntegrationRefreshCompletion();
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
	const internalTestDisposables = context.extensionMode === vscode.ExtensionMode.Test
		? [
			vscode.commands.registerCommand(
				'observability-studio.internal.createFreeAccountForTest',
				() => performCloudBridgeAction(context, {
					action: 'create-free-account',
					payload: {
						email: 'ada@example.com',
						firstName: 'Ada',
						lastName: 'Lovelace',
						region: 'us',
						termsAccepted: true,
					},
				}),
			),
			vscode.commands.registerCommand(
				'observability-studio.internal.resolveCloudRealmForTest',
				() => performCloudBridgeAction(context, {
					action: 'resolve-realm',
					payload: { destination: 'https://app.us1.signalfx.com' },
				}),
			),
			vscode.commands.registerCommand(
				'observability-studio.internal.setObserverOtlpPortsForTest',
				(value?: { grpc?: unknown; http?: unknown }) => {
					if (observerLifecycleState.status !== 'stopped' || observerStartupPromise !== undefined) {
						throw new Error('Observer must be stopped before changing test OTLP ports.');
					}
					const nextHttpPort = parseInternalTestPort(value?.http, defaultObserverOtlpHttpPort);
					const nextGrpcPort = parseInternalTestPort(value?.grpc, defaultObserverOtlpGrpcPort);
					if (nextHttpPort === nextGrpcPort) {
						throw new Error('Observer test OTLP ports must be distinct.');
					}
					observerOtlpHttpPort = nextHttpPort;
					observerOtlpGrpcPort = nextGrpcPort;
					observerOtlpHttpEndpoint = `http://${managedObserverHost}:${observerOtlpHttpPort}`;
					observerOtlpGrpcEndpoint = `${managedObserverHost}:${observerOtlpGrpcPort}`;
				},
			),
		]
		: [];

	context.subscriptions.push(openObserverDisposable);
	context.subscriptions.push(statusMenuDisposable);
	context.subscriptions.push(startDisposable);
	context.subscriptions.push(stopDisposable);
	context.subscriptions.push(restartDisposable);
	context.subscriptions.push(signInToSISWithCIMDDisposable);
	context.subscriptions.push(clearSISSessionDisposable);
	context.subscriptions.push(configureCodexDisposable);
	context.subscriptions.push(configureClaudeDisposable);
	context.subscriptions.push(configureCursorDisposable);
	context.subscriptions.push(configureKiroDisposable);
	context.subscriptions.push(internalConfigureDetectedAgentsDisposable);
	context.subscriptions.push(internalGetAgentIntegrationPromptsDisposable);
	context.subscriptions.push(internalClearAgentIntegrationPromptsDisposable);
	context.subscriptions.push(internalResetAgentIntegrationPromptStateDisposable);
	context.subscriptions.push(internalWaitForAgentIntegrationRefreshDisposable);
	context.subscriptions.push(internalStateDisposable);
	context.subscriptions.push(...internalTestDisposables);
	context.subscriptions.push(observerStatusBarItem);
	context.subscriptions.push({
		dispose: () => {
			sisCIMDOAuthAbortController?.abort();
			disposeObserverForExtensionUnload('Extension disposed');
		},
	});
}

export async function deactivate(): Promise<void> {
	observerDeactivationStarted = true;
	sisCIMDOAuthAbortController?.abort();
	await shutdownObserverForExtensionUnload('Extension deactivated');
}

function isSISCIMDRegistrationEnabled(): boolean {
	return vscode.workspace.getConfiguration('observability-studio')
		.get<boolean>(sisCimdRegistrationEnabledSetting) === true;
}

function getSISCIMDOAuthConfiguration(): SISCIMDOAuthConfiguration {
	const configuration = vscode.workspace.getConfiguration('observability-studio');
	const issuer = configuration.get<string>(sisCimdOAuthIssuerSetting)?.trim() || sisCimdOAuthDefaultIssuer;
	const clientId = configuration.get<string>(sisCimdOAuthClientIdSetting)?.trim() || sisCimdOAuthDefaultClientId;
	const scope = configuration.get<string>(sisCimdOAuthScopeSetting)?.trim() ?? '';
	const redirectUri = configuration.get<string>(sisCimdOAuthRedirectUriSetting)?.trim()
		|| sisCIMDOAuthRedirectUri;
	const developmentCaBundlePath = configuration
		.get<string>(sisCimdOAuthDevelopmentCaBundlePathSetting)?.trim() || undefined;

	if (scope === '') {
		throw new Error('Set observability-studio.sisCimdOAuthScope to at least one SIS-supported scope.');
	}
	if (redirectUri !== sisCIMDOAuthRedirectUri) {
		throw new Error(`CIMD requires the fixed callback ${sisCIMDOAuthRedirectUri}.`);
	}

	return {
		clientId,
		developmentCaBundlePath,
		issuer,
		redirectUri,
		scope,
	};
}

// Thin delegators to sis-cimd-oauth.ts's vscode-independent session-storage functions,
// supplying the pieces only the extension host has (context.secrets, the configured
// SIS endpoints, whether a sign-in is currently pending) -- see that module for the
// actual storage/restore/redaction logic and its tests.
async function loadCurrentSISCIMDOAuthSession(
	context: vscode.ExtensionContext,
): Promise<SISCIMDOAuthSession | undefined> {
	return loadStoredSISCIMDOAuthSession(context.secrets, getSISCIMDOAuthConfiguration());
}

async function hasCurrentSISSession(context: vscode.ExtensionContext): Promise<boolean> {
	return await loadCurrentSISCIMDOAuthSession(context) !== undefined;
}

async function currentSISCIMDSessionStatus(context: vscode.ExtensionContext): Promise<SISCIMDSessionStatus> {
	return computeSISCIMDSessionStatus(
		context.secrets,
		getSISCIMDOAuthConfiguration(),
		sisCIMDOAuthFlowPromise !== undefined,
	);
}

async function signInToSISWithCIMD(context: vscode.ExtensionContext): Promise<boolean> {
	if (sisCIMDOAuthFlowPromise !== undefined) {
		return sisCIMDOAuthFlowPromise;
	}

	const abortController = new AbortController();
	sisCIMDOAuthAbortController = abortController;
	sisCIMDOAuthFlowPromise = performSISCIMDOAuthSignIn(context, abortController);
	try {
		return await sisCIMDOAuthFlowPromise;
	} finally {
		abortController.abort();
		if (sisCIMDOAuthAbortController === abortController) {
			sisCIMDOAuthAbortController = undefined;
		}
		sisCIMDOAuthFlowPromise = undefined;
	}
}

async function performSISCIMDOAuthSignIn(
	context: vscode.ExtensionContext,
	abortController: AbortController,
): Promise<boolean> {
	if (await hasCurrentSISSession(context)) {
		return true;
	}

	const session = await vscode.window.withProgress(
		{
			cancellable: true,
			location: vscode.ProgressLocation.Notification,
			title: 'Setting up SIS sign-in with CIMD',
		},
		async (progress, cancellationToken) => {
			const cancellationDisposable = cancellationToken.onCancellationRequested(() => abortController.abort());
			progress.report({ message: 'Validating client metadata and SIS discovery...' });
			try {
				return await authorizeWithSISCIMD(getSISCIMDOAuthConfiguration(), async (authorizationUrl) => {
					progress.report({ message: 'Complete authorization in your browser...' });
					return vscode.env.openExternal(vscode.Uri.parse(authorizationUrl.toString()));
				}, abortController.signal);
			} finally {
				cancellationDisposable.dispose();
			}
		},
	);
	if (abortController.signal.aborted) {
		throw new Error('CIMD setup was cancelled.');
	}

	await storeSISCIMDOAuthSession(context.secrets, session);
	return true;
}

async function runSISCIMDOAuthCommand(context: vscode.ExtensionContext): Promise<boolean> {
	try {
		const ready = await signInToSISWithCIMD(context);
		if (ready) {
			refreshObserverPanel();
			void vscode.window.showInformationMessage(
				'CIMD SIS session ready. Splunk Observability Cloud export remains disconnected.',
			);
		}
		return ready;
	} catch (error) {
		void vscode.window.showErrorMessage(`CIMD setup failed: ${getErrorMessage(error)}`);
		return false;
	}
}

async function clearSISSession(context: vscode.ExtensionContext): Promise<boolean> {
	if (sisCIMDOAuthFlowPromise !== undefined) {
		void vscode.window.showWarningMessage('Finish or cancel the current CIMD setup before clearing its session.');
		return false;
	}

	await deleteSISCIMDOAuthSession(context.secrets);
	refreshObserverPanel();
	void vscode.window.showInformationMessage(
		'Local CIMD SIS session cleared. Splunk Observability Cloud export is unchanged.',
	);
	return true;
}

// ---------------------------------------------------------------------------
// Observer process lifecycle
// ---------------------------------------------------------------------------

async function ensureObserverRunning(context: vscode.ExtensionContext): Promise<void> {
	if (observerStartupPromise !== undefined) {
		logObserverLifecycle('Start requested while startup is already in progress; waiting for existing startup.');
		return observerStartupPromise;
	}
	if (observerStopOperation.current !== undefined) {
		logObserverLifecycle('Start requested while stop is in progress; waiting for observer shutdown.');
		await observerStopOperation.current;
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
		const discoveredState = readSharedObserverDiscovery(
			os.homedir(),
			process.env.OBSTUDIO_SHARED_OBSERVER_STATE_PATH,
		);
		const managedState = readManagedObserverDiscovery();

		const sharedObserverUrl = getConfiguredSharedObserverUrl();
		if (sharedObserverUrl !== undefined) {
			observerUsesSharedServer = true;
			appendObserverOutputLine(`Using configured shared observer at ${sharedObserverUrl}`);
			const configuredDiscovery = preferredObserverDiscoveryForBase(
				sharedObserverUrl,
				discoveredState,
				managedState,
			);
			const configuredEndpoints = configuredDiscovery === undefined
				? observerEndpointRolesForBase(sharedObserverUrl)
				: observerEndpointRolesForDiscovery(configuredDiscovery, sharedObserverUrl);
			setObserverEndpoints(configuredEndpoints);
			syncObserverUi();
			await waitForObserverReady(configuredEndpoints, { requireStableOtlp: false }, runId);
			const sharedPort = observerPortFromUrl(configuredEndpoints.restBaseUrl);
			if (sharedPort === undefined) {
				throw new Error(`Observer URL does not resolve to a usable port: ${sharedObserverUrl}`);
			}
			if (completeObserverStart(observerLifecycleState, runId, sharedPort)) {
				syncObserverUi();
			}
			return;
		}

		const discoveredObserver = discoveredState === undefined
			? undefined
			: preferredObserverDiscoveryForBase(
				discoveredState.baseUrl,
				discoveredState,
				managedState,
			);
		if (discoveredObserver !== undefined) {
			const discoveredEndpoints = observerEndpointRolesForDiscovery(discoveredObserver);
			let discoveryProbe = await probeObserver(
				discoveredEndpoints,
				500,
				{ requireStableOtlp: true },
			);
			assertObserverRunCurrent(observerLifecycleState, runId);
			while (
				discoveryProbe.status === 'unavailable'
				&& discoveredObserver.updatedAtMs !== undefined
				&& discoveredObserver.updatedAtMs <= Date.now()
				&& Date.now() - discoveredObserver.updatedAtMs < sharedObserverStartupWindowMs
			) {
				await delay(100);
				assertObserverRunCurrent(observerLifecycleState, runId);
				discoveryProbe = await probeObserver(
					discoveredEndpoints,
					500,
					{ requireStableOtlp: true },
				);
				assertObserverRunCurrent(observerLifecycleState, runId);
			}
			const retirement = await retireOtherExtensionManagedObserver(
				context,
				discoveredObserver,
				discoveryProbe.status === 'ready',
			);
			assertObserverRunCurrent(observerLifecycleState, runId);
			if (retirement.status === 'restart-required') {
				const portLabel = retirement.port === undefined
					? 'an unknown localhost port'
					: `localhost port ${retirement.port}`;
				const restartMessage = retirement.version === undefined
					? `Observer on ${portLabel} (PID ${retirement.pid}) could not be verified for automatic replacement. `
						+ 'Cloud controls are unavailable until it is stopped.'
					: `Observer ${retirement.version} on ${portLabel} (PID ${retirement.pid}) is still running `
						+ 'from a previous extension installation. Cloud controls are unavailable until it is stopped.';
				const restartError = new Error(restartMessage);
				Object.assign(restartError, {
					startupHint: 'Restart VS Code to stop the previous Observer, then run Splunk Observability Studio: Start Observer. '
						+ 'If it remains running, stop the displayed PID and retry.',
					startupTitle: 'Restart required',
				});
				throw restartError;
			}
			let discoveryDetail: string;
			if (retirement.status === 'retired') {
				discoveryDetail = 'the running Observer belonged to a different installed extension copy';
			} else if (discoveryProbe.status === 'ready') {
				setObserverEndpoints(discoveredEndpoints);
				const discoveredPort = observerPortFromUrl(discoveredEndpoints.restBaseUrl);
				if (discoveredPort !== undefined) {
					observerUsesSharedServer = true;
					appendObserverOutputLine(`Reusing discovered shared observer at ${discoveredObserver.baseUrl}`);
					if (completeObserverStart(observerLifecycleState, runId, discoveredPort)) {
						syncObserverUi();
					}
					return;
				}
				discoveryDetail = 'the discovered URL did not contain a usable port';
			} else if (discoveryProbe.status === 'mismatch') {
				discoveryDetail = discoveryProbe.reason;
			} else {
				discoveryDetail = getErrorMessage(discoveryProbe.error);
			}
			appendObserverOutputLine(
				`Ignoring stale or incompatible shared observer state for ${discoveredObserver.baseUrl}: ${discoveryDetail}`,
			);
		}

		const managedPort = getConfiguredManagedObserverPort();
		const managedObserverBaseUrl = buildManagedObserverBaseUrl(managedPort);
		const managedEndpoints = observerEndpointRolesForBase(managedObserverBaseUrl);
		const managedDiscovery = managedState;
		if (
			managedDiscovery !== undefined
			&& sharedDiscoveryMatchesRestBase(managedDiscovery, managedObserverBaseUrl)
		) {
			const managedObserverEndpoints = observerEndpointRolesForDiscovery(
				managedDiscovery,
				managedObserverBaseUrl,
			);
			const managedProbe = await probeObserver(
				managedObserverEndpoints,
				500,
				{ requireStableOtlp: true },
			);
			assertObserverRunCurrent(observerLifecycleState, runId);
			if (managedProbe.status === 'ready') {
				setObserverEndpoints(managedObserverEndpoints);
				observerUsesSharedServer = true;
				appendObserverOutputLine(
					`Reusing CLI-managed observer at ${managedObserverEndpoints.restBaseUrl}`,
				);
				if (completeObserverStart(observerLifecycleState, runId, managedPort)) {
					syncObserverUi();
				}
				return;
			}
			const managedDetail = managedProbe.status === 'mismatch'
				? managedProbe.reason
				: getErrorMessage(managedProbe.error);
			appendObserverOutputLine(
				`Ignoring stale or incompatible CLI-managed Observer state for ${managedObserverBaseUrl}: ${managedDetail}`,
			);
		}
		const existingObserver = await probeObserver(managedEndpoints, 500, { requireStableOtlp: true });
		assertObserverRunCurrent(observerLifecycleState, runId);

		if (existingObserver.status === 'ready') {
			observerUsesSharedServer = true;
			setObserverEndpoints(managedEndpoints);
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
		setObserverEndpoints(managedEndpoints);

		appendObserverOutputLine(`Starting ${backend.label} on ${managedObserverBaseUrl}`);
		appendObserverOutputLine(`OTLP/HTTP receiver listening on ${observerOtlpHttpEndpoint}`);
		appendObserverOutputLine(`OTLP/gRPC receiver listening on ${observerOtlpGrpcEndpoint}`);
		const managedObserverEnvironment: NodeJS.ProcessEnv = {
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
		};
		// Never pass obsolete remote-control credentials or public endpoints to
		// the loopback-only Observer, even if VS Code inherited them.
		delete managedObserverEnvironment.OBSTUDIO_CONTROL_TOKEN;
		delete managedObserverEnvironment.OBSTUDIO_HEALTH_PROOF_SECRET;
		delete managedObserverEnvironment.OBSTUDIO_PUBLIC_MCP_URL;
		try {
			startedProcess = cp.spawn(backend.command, backend.args, {
				cwd: backend.cwd,
				env: managedObserverEnvironment,
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
				setObserverEndpoints(undefined);
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
				setObserverEndpoints(undefined);
				observerUsesSharedServer = false;
				syncObserverUi();
				void vscode.window.showErrorMessage(`Splunk Observability Studio failed to start observer: ${startupMessage}`);
			}
		});

		await waitForObserverReady(managedEndpoints, { requireStableOtlp: true }, runId);
		logObserverLifecycle(`Run ${runId}: observer is accepting connections at ${managedObserverBaseUrl}.`);
		const startupCompleted = await observerCloudLifecycleOperations.run(async () => {
			if (!completeObserverStart(observerLifecycleState, runId, observerPort)) {
				if (observerProcess === startedProcess) {
					observerProcess = undefined;
				}
				logObserverLifecycle(`Run ${runId}: startup completed after the run was superseded; terminating stale process.`);
				terminateObserverProcess(startedProcess, 'SIGTERM');
				return false;
			}

			await restoreManagedObserverCloudConnection(context);
			return true;
		});
		if (!startupCompleted) {
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
		const startupTitle = typeof error === 'object'
			&& error !== null
			&& 'startupTitle' in error
			&& typeof (error as { startupTitle?: unknown }).startupTitle === 'string'
			? (error as { startupTitle: string }).startupTitle
			: undefined;
		if (failObserverStart(observerLifecycleState, runId, startupMessage, startupHint, startupTitle)) {
			setObserverEndpoints(undefined);
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

async function retireOtherExtensionManagedObserver(
	context: vscode.ExtensionContext,
	discovery: SharedObserverDiscovery,
	observerHealthVerified: boolean,
): Promise<OtherExtensionObserverRetirement> {
	const pid = discovery.pid;
	if (pid === undefined || pid === process.pid) {
		return { status: 'not-applicable' };
	}
	const processExecutablePath = await readProcessExecutablePath(pid);
	if (processExecutablePath === undefined) {
		if (!processIsRunning(pid)) {
			return { status: 'not-applicable' };
		}
		appendObserverOutputLine(
			`Observer PID ${pid} could not be inspected; refusing to stop it automatically.`,
		);
		return {
			pid,
			port: observerPortFromUrl(discovery.baseUrl),
			status: 'restart-required',
		};
	}
	const otherExtensionObserver = findOtherExtensionManagedObserver({
		currentExtensionPath: context.extensionPath,
		discovery,
		processExecutablePath,
	});
	if (otherExtensionObserver === undefined) {
		const unverifiedObserver = findOtherExtensionObserverExecutable({
			currentExtensionPath: context.extensionPath,
			discovery,
			processExecutablePath,
		});
		if (unverifiedObserver === undefined) {
			return { status: 'not-applicable' };
		}
		appendObserverOutputLine(
			`Observer PID ${unverifiedObserver.pid} appears to belong to a previous extension installation, `
			+ 'but its installed package can no longer be verified; refusing to stop it automatically.',
		);
		return {
			pid: unverifiedObserver.pid,
			port: observerPortFromUrl(discovery.baseUrl),
			status: 'restart-required',
		};
	}
	const restartRequired = (): OtherExtensionObserverRetirement => ({
		pid: otherExtensionObserver.pid,
		port: observerPortFromUrl(discovery.baseUrl),
		status: 'restart-required',
		version: otherExtensionObserver.version,
	});
	if (!observerHealthVerified) {
		appendObserverOutputLine(
			`Observer from installed extension ${otherExtensionObserver.version} could not be verified at `
			+ `${discovery.baseUrl}; refusing to stop it automatically.`,
		);
		return restartRequired();
	}

	const preStopExecutablePath = await readProcessExecutablePath(otherExtensionObserver.pid);
	const preStopObserver = preStopExecutablePath === undefined
		? undefined
		: findOtherExtensionManagedObserver({
			currentExtensionPath: context.extensionPath,
			discovery,
			processExecutablePath: preStopExecutablePath,
		});
	if (
		preStopObserver === undefined
		|| path.resolve(preStopObserver.binaryPath) !== path.resolve(otherExtensionObserver.binaryPath)
	) {
		appendObserverOutputLine(
			`Could not reverify Observer from installed extension ${otherExtensionObserver.version}; refusing to stop it.`,
		);
		return restartRequired();
	}

	appendObserverOutputLine(
		`Replacing Observer from installed extension ${otherExtensionObserver.version} (PID ${otherExtensionObserver.pid}) `
		+ `with bundled Observer ${getBundleVersion(context)}.`,
	);
	try {
		process.kill(otherExtensionObserver.pid, 'SIGTERM');
	} catch (error) {
		if ((error as NodeJS.ErrnoException).code === 'ESRCH') {
			return { status: 'retired' };
		}
		appendObserverOutputLine(
			`Could not stop Observer from installed extension ${otherExtensionObserver.version}: ${getErrorMessage(error)}`,
		);
		return restartRequired();
	}

	if (await waitForProcessExit(
		otherExtensionObserver.pid,
		outdatedExtensionObserverShutdownTimeoutMs,
	)) {
		appendObserverOutputLine(`Stopped Observer from installed extension ${otherExtensionObserver.version}.`);
		return { status: 'retired' };
	}
	appendObserverOutputLine(
		`Observer from installed extension ${otherExtensionObserver.version} did not stop after `
		+ `${outdatedExtensionObserverShutdownTimeoutMs}ms; forcing it to stop.`,
	);
	const currentProcessExecutablePath = await readProcessExecutablePath(otherExtensionObserver.pid);
	const reverifiedObserver = currentProcessExecutablePath === undefined
		? undefined
		: findOtherExtensionManagedObserver({
			currentExtensionPath: context.extensionPath,
			discovery,
			processExecutablePath: currentProcessExecutablePath,
		});
	if (
		reverifiedObserver === undefined
		|| path.resolve(reverifiedObserver.binaryPath) !== path.resolve(otherExtensionObserver.binaryPath)
	) {
		appendObserverOutputLine(
			`Could not reverify Observer from installed extension ${otherExtensionObserver.version}; refusing a forced stop.`,
		);
		return restartRequired();
	}
	try {
		await forceTerminateProcess(otherExtensionObserver.pid);
	} catch (error) {
		if (!processIsRunning(otherExtensionObserver.pid)) {
			return { status: 'retired' };
		}
		appendObserverOutputLine(
			`Could not force-stop Observer from installed extension ${otherExtensionObserver.version}: ${getErrorMessage(error)}`,
		);
		return restartRequired();
	}
	if (await waitForProcessExit(
		otherExtensionObserver.pid,
		outdatedExtensionObserverForceShutdownTimeoutMs,
	)) {
		appendObserverOutputLine(`Force-stopped Observer from installed extension ${otherExtensionObserver.version}.`);
		return { status: 'retired' };
	}
	appendObserverOutputLine(
		`Observer from installed extension ${otherExtensionObserver.version} is still running after a forced stop.`,
	);
	return restartRequired();
}

async function waitForProcessExit(pid: number, timeoutMs: number): Promise<boolean> {
	const deadline = Date.now() + timeoutMs;
	while (Date.now() < deadline) {
		if (!processIsRunning(pid)) {
			return true;
		}
		await delay(50);
	}
	return !processIsRunning(pid);
}

async function stopObserver(): Promise<void> {
	if (observerStopOperation.current !== undefined) {
		logObserverLifecycle('Stop requested while shutdown is already in progress; waiting for existing shutdown.');
		return observerStopOperation.current;
	}

	const queuedStop = observerCloudLifecycleOperations.run(async () => {
		const proc = observerProcess;
		if (proc === undefined && observerStartupPromise === undefined && observerBaseUrl === undefined) {
			if (observerLifecycleState.status !== 'stopped') {
				stopObserverRun(observerLifecycleState);
				observerUsesSharedServer = false;
				syncObserverUi();
			}
			logObserverLifecycle('Stop requested but observer is already idle.');
			return;
		}
		logObserverLifecycle(
			`Stopping observer (status=${observerLifecycleState.status}, pid=${proc?.pid ?? 'none'}, port=${observerLifecycleState.port ?? 'none'}, url=${observerBaseUrl ?? 'none'}).`,
		);
		stopObserverRun(observerLifecycleState);
		observerProcess = undefined;
		observerStartupPromise = undefined;
		setObserverEndpoints(undefined);
		observerUsesSharedServer = false;
		syncObserverUi();

		if (proc === undefined) {
			logObserverLifecycle('No observer process existed; shutdown completed after clearing in-flight startup state.');
			return;
		}

		const exitPromise = new Promise<void>((resolve) => {
			const timeout = setTimeout(() => {
				terminateObserverProcess(proc, 'SIGKILL');
				resolve();
			}, observerShutdownTerminationTimeoutMs);
			proc.once('exit', () => {
				clearTimeout(timeout);
				resolve();
			});
		});

		terminateObserverProcess(proc, 'SIGTERM');
		await exitPromise;
		await delay(observerShutdownPostExitDelayMs);
	});
	return observerStopOperation.run(() => queuedStop);
}

async function shutdownObserverForExtensionUnload(
	reason: string,
): Promise<void> {
	logObserverLifecycle(`${reason}; stopping observer process.`);
	try {
		const stopped = await operationCompletesWithin(
			stopObserver(),
			observerExtensionUnloadDeadlineMs,
		);
		if (!stopped) {
			forceDisposeObserverForExtensionUnload(`${reason}; shutdown deadline exceeded`, 'SIGKILL');
		}
	} catch (error) {
		logObserverLifecycle(`${reason}; observer shutdown failed: ${getErrorMessage(error)}`);
		forceDisposeObserverForExtensionUnload(`${reason}; shutdown failed`, 'SIGKILL');
	}
}

function disposeObserverForExtensionUnload(reason: string): void {
	if (observerDeactivationStarted) {
		logObserverLifecycle(`${reason}; asynchronous deactivation already owns observer shutdown.`);
		return;
	}
	forceDisposeObserverForExtensionUnload(reason);
}

function forceDisposeObserverForExtensionUnload(
	reason: string,
	signal: NodeJS.Signals = 'SIGTERM',
): void {
	logObserverLifecycle(`${reason}; terminating observer process.`);
	const proc = observerProcess;
	stopObserverRun(observerLifecycleState);
	observerProcess = undefined;
	observerStartupPromise = undefined;
	observerStopOperation.clear();
	setObserverEndpoints(undefined);
	observerUsesSharedServer = false;
	syncObserverUi();
	terminateObserverProcess(proc, signal);
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
	const webviewRoot = vscode.Uri.joinPath(context.extensionUri, 'dist', 'webview');
	observerWebviewRootUri = webviewRoot;
	panel.webview.options = {
		enableScripts: true,
		localResourceRoots: [webviewRoot],
	};
	applyObserverPanelPresentation(panel, context);
	panel.webview.onDidReceiveMessage((message: unknown) => {
		void handleObserverWebviewMessage(panel, context, message);
	}, undefined, context.subscriptions);
	panel.onDidDispose(() => {
		if (observerPanel === panel) {
			logObserverLifecycle('Observer webview panel disposed.');
			lastObserverPanelRenderKey = undefined;
			disposeObserverPanelRuntime();
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

	const renderKey = `${observerLifecycleState.status}:${observerLifecycleState.port ?? 'none'}:${observerLifecycleState.startupError ?? 'none'}:${observerLifecycleState.startupHint ?? 'none'}:${observerLifecycleState.startupTitle ?? 'none'}:${observerBaseUrl ?? 'none'}:${observerUsesSharedServer ? 'shared' : 'local'}`;
	if (renderKey === lastObserverPanelRenderKey) {
		return;
	}
	logObserverLifecycle(`Rendering observer panel state ${renderKey}.`);
	lastObserverPanelRenderKey = renderKey;
	disposeObserverPanelRuntime();

	switch (observerLifecycleState.status) {
		case 'running':
			if (observerLifecycleState.port === undefined || observerBaseUrl === undefined) {
				observerPanel.webview.html = getObserverLoadingWebviewHtml();
			} else {
				const panel = observerPanel;
				observerPanelTelemetry = new ObserverWebviewTelemetry(
					observerBaseUrl,
					(message) => panel === observerPanel
						? panel.webview.postMessage(message)
						: Promise.resolve(false),
					(message) => appendObserverOutputLine(`[webview] ${message}`),
				);
				panel.webview.html = getObserverWebviewHtmlForPanel(panel);
			}
			return;
		case 'error':
			observerPanel.webview.html = getObserverErrorWebviewHtml(
				observerLifecycleState.startupError ?? 'Observer could not start.',
				observerLifecycleState.startupHint ?? getObserverStartupHint('generic'),
				observerLifecycleState.startupTitle ?? 'Observer could not start',
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

type CloudActionResult = {
	cimdRegistrationEnabled?: boolean;
	cimdRegistrationVerified?: boolean;
	cimdSession?: SISCIMDSessionStatus;
	freeAccount?: unknown;
	message?: string;
	realm?: string;
	region?: string;
	status?: unknown;
	warning?: string;
};

class ObserverCloudRequestError extends Error {
	constructor(
		message: string,
		readonly code?: string,
		readonly retrySafe?: boolean,
	) {
		super(message);
		this.name = 'ObserverCloudRequestError';
	}
}

async function handleObserverWebviewMessage(
	panel: vscode.WebviewPanel,
	context: vscode.ExtensionContext,
	message: unknown,
): Promise<void> {
	if (panel !== observerPanel) {
		return;
	}
	if (isObserverHostTelemetryEnvelope(message)) {
		observerPanelTelemetry?.handle(message.command);
		return;
	}
	if (isObserverHostCancelEnvelope(message)) {
		observerHostRequestCancellations.get(message.requestId)?.();
		return;
	}
	if (!isObserverHostRequestEnvelope(message)) {
		return;
	}
	if (observerHostRequestCancellations.has(message.requestId)) {
		await postObserverHostResponse(panel, message.requestId, false, undefined, 'Duplicate IDE request id.');
		return;
	}

	const freeAccountSignup = isFreeAccountSignupRequest(message.request);
	const controller = new AbortController();
	let cancelled = false;
	observerHostRequestCancellations.set(message.requestId, () => {
		cancelled = true;
		// Read-only HTTP requests are safe to abort. Cloud mutations deliberately
		// finish after the panel closes; lifecycle transitions share their queue so
		// Observer state and IDE secure storage remain on the same committed version.
		if (message.request.kind === 'http') {
			controller.abort();
		}
	});
	try {
		const result = await performObserverHostRequest(context, message.request, controller.signal);
		let delivered = false;
		if (!cancelled && panel === observerPanel) {
			delivered = await postObserverHostResponse(panel, message.requestId, true, result).catch(() => false);
		}
		if (!delivered && !observerDeactivationStarted && freeAccountSignup) {
			void vscode.window.showInformationMessage(freeAccountSetupIsPending(result)
				? 'Splunk received your Free Edition request but needs extra time to finish setting up the account. ' +
					'If a confirmation email does not arrive within 24 hours, contact Splunk Support.'
				: 'Thank you for registering. Your free edition account is on its way. ' +
					'You will receive an email within 10 minutes; check your spam folder if it does not arrive.');
		}
	} catch (error) {
		let delivered = false;
		if (!cancelled && panel === observerPanel) {
			delivered = await postObserverHostResponse(
				panel,
				message.requestId,
				false,
				undefined,
				getErrorMessage(error),
				cloudBridgeErrorMetadata(error),
			).catch(() => false);
		}
		if (!delivered && !observerDeactivationStarted && freeAccountSignup) {
			const metadata = cloudBridgeErrorMetadata(error);
			if (metadata.code === 'outcome_unknown' || metadata.retrySafe === false) {
				void vscode.window.showWarningMessage(getErrorMessage(error));
			} else {
				void vscode.window.showErrorMessage(`Free Edition signup failed: ${getErrorMessage(error)}`);
			}
		}
	} finally {
		observerHostRequestCancellations.delete(message.requestId);
	}
}

function isFreeAccountSignupRequest(request: ObserverHostRequest): boolean {
	return request.kind === 'cloud' && request.action === 'create-free-account';
}

function freeAccountSetupIsPending(value: unknown): boolean {
	if (typeof value !== 'object' || value === null) {
		return false;
	}
	const freeAccount = (value as { freeAccount?: unknown }).freeAccount;
	return typeof freeAccount === 'object'
		&& freeAccount !== null
		&& (freeAccount as { accountSetupPending?: unknown }).accountSetupPending === true;
}

async function performObserverHostRequest(
	context: vscode.ExtensionContext,
	request: ObserverHostRequest,
	signal: AbortSignal,
): Promise<unknown> {
	if (request.kind === 'http') {
		return requestObserverHostHTTP(request.method, request.path, request.body, signal);
	}
	return performCloudBridgeAction(context, request);
}

async function postObserverHostResponse(
	panel: vscode.WebviewPanel,
	requestId: string,
	ok: boolean,
	result?: unknown,
	error?: string,
	errorMetadata: { code?: string; retrySafe?: boolean } = {},
): Promise<boolean> {
	return panel.webview.postMessage({
		...errorMetadata,
		error,
		ok,
		requestId,
		result,
		type: 'obstudio.host.response',
	} satisfies ObserverHostResponseEnvelope);
}

async function performCloudBridgeAction(
	context: vscode.ExtensionContext,
	request: { action: CloudBridgeAction; payload?: ObserverHostCloudPayload },
): Promise<CloudActionResult> {
	if (cloudBridgeActionRequiresLifecycleSerialization(request.action)) {
		return observerCloudLifecycleOperations.run(
			() => performCloudBridgeActionExclusive(context, request),
		);
	}
	return performCloudBridgeActionExclusive(context, request);
}

async function performCloudBridgeActionExclusive(
	context: vscode.ExtensionContext,
	request: { action: CloudBridgeAction; payload?: ObserverHostCloudPayload },
): Promise<CloudActionResult> {
	switch (request.action) {
		case 'initialize': {
			// Registration (registerClientWithSIS) is a stateless probe with nothing
			// persisted to restore, unlike a login session -- cimdRegistrationVerified
			// only ever becomes true as the direct result of a 'setup-cimd' response
			// within this webview session. The login session itself DOES persist
			// (context.secrets), so cimdSession is restored here, on both the happy
			// and the recoverable-error path below.
			const cimdRegistrationEnabled = isSISCIMDRegistrationEnabled();
			try {
				const [status, cimdSession] = await Promise.all([
					refreshSplunkCloudConnection(context),
					currentSISCIMDSessionStatus(context),
					]);
					return { cimdRegistrationEnabled, cimdSession, status };
				} catch (error) {
					const [status, cimdSession] = await Promise.all([
					getObserverCloudJSON('/api/splunk/export'),
					currentSISCIMDSessionStatus(context),
				]);
				return {
					cimdRegistrationEnabled,
					cimdSession,
					status,
					warning: getErrorMessage(error),
				};
			}
		}
		case 'open-free-edition':
			await openCloudExternalUrl(splunkFreeEditionUrl);
			return {};
		case 'open-free-edition-terms':
			await openCloudExternalUrl(splunkFreeEditionTermsUrl);
			return {};
		case 'open-ingest-token-help':
			await openCloudExternalUrl(splunkIngestTokenHelpUrl);
			return {};
		case 'open-realm-help':
			await openCloudExternalUrl(splunkRealmHelpUrl);
			return {};
		case 'open-observability-cloud-demo':
			await openCloudExternalUrl(splunkObservabilityCloudDemoUrl);
			return {};
		case 'open-observability-data-course':
			await openCloudExternalUrl(splunkObservabilityDataCourseUrl);
			return {};
		case 'open-observability-docs':
			await openCloudExternalUrl(splunkObservabilityDocsUrl);
			return {};
		case 'detect-free-account-region':
			return {
				region: freeAccountRegionFromResponse(
					await requestObserverFreeAccountJSON(
						'/api/splunk/free-account/region',
						undefined,
						observerCloudRequestTimeoutMs,
					),
				),
			};
		case 'create-free-account': {
			const payload = request.payload;
			if (
				payload === undefined
				|| typeof payload.firstName !== 'string'
				|| typeof payload.lastName !== 'string'
				|| typeof payload.email !== 'string'
				|| typeof payload.region !== 'string'
				|| !isSupportedFreeAccountRegion(payload.region)
				|| payload.termsAccepted !== true
			) {
				throw new ObserverCloudRequestError(
					'Free Edition signup details are missing.',
					'validation',
					true,
				);
			}
			const freeAccount = parseFreeAccountSubmissionResult(
				await requestObserverFreeAccountJSON(
					'/api/splunk/free-account',
					{
						email: payload.email,
						firstName: payload.firstName,
						lastName: payload.lastName,
						region: payload.region,
						termsAccepted: true,
					},
					freeAccountRequestTimeoutMs,
				),
			);
			if (freeAccount === undefined) {
				throw new ObserverCloudRequestError(
					'The signup outcome is unknown. Check your email before trying again.',
					'outcome_unknown',
					false,
				);
			}
			if (!freeAccount.intakeAcknowledged) {
				throw new ObserverCloudRequestError(
					'Splunk did not acknowledge the Free Edition signup intake.',
					'signup_not_acknowledged',
					true,
				);
			}
			return { freeAccount };
		}
		case 'open-skill-docs': {
			const url = skillDocsUrl(request.payload?.skill);
			if (url === undefined) {
				throw new Error('Unknown skill documentation request.');
			}
			await openCloudExternalUrl(url);
			return {};
		}
		case 'open-audit-report': {
			// Keep external navigation in the host so the Observer webview remains
			// open and cannot choose an arbitrary destination.
			const url = auditReportUrl(observerBaseUrl);
			if (url === undefined) {
				throw new Error('The Observer is not running, so the audit report cannot be opened.');
			}
			await openCloudExternalUrl(url);
			return {};
		}
		case 'resolve-realm': {
			const destination = request.payload?.destination?.trim() ?? '';
			if (destination === '' || Buffer.byteLength(destination, 'utf8') > maxCloudDestinationBytes) {
				throw new Error('Enter a valid Splunk Observability Cloud URL.');
			}
			return {
				realm: splunkRealmFromResponse(
					await postObserverCloudJSON('/api/splunk/export/realm', { destination }),
				),
			};
		}
		case 'setup-cimd': {
			const setupConfig = getSISCIMDOAuthConfiguration();
			appendObserverOutputLine(
				`[sis-cimd] registering with issuer=${setupConfig.issuer} clientId=${setupConfig.clientId} `
					+ `caBundle=${setupConfig.developmentCaBundlePath ?? '(none)'}`,
			);
			let registration;
			try {
				registration = await registerClientWithSIS(setupConfig);
			} catch (error) {
				const err = error as NodeJS.ErrnoException;
				appendObserverOutputLine(
					`[sis-cimd] registration failed: ${err?.message} `
						+ `(code=${err?.code ?? 'none'}, cause=${String((err as { cause?: unknown })?.cause ?? 'none')})`,
				);
				throw error;
			}
			appendObserverOutputLine(
				`[sis-cimd] registration verified: SIS redirected to ${registration.location} `
					+ `(session cookie max-age ${registration.cookieMaxAgeSeconds}s).`,
			);
			return {
				cimdRegistrationVerified: true,
				message: 'CIMD client registration verified with SIS. Splunk Observability Cloud export remains disconnected.',
			};
		}
		case 'login-cimd': {
			await signInToSISWithCIMD(context);
			return { cimdSession: await currentSISCIMDSessionStatus(context) };
		}
		case 'disconnect-cimd': {
			await clearSISSession(context);
			return { cimdSession: await currentSISCIMDSessionStatus(context) };
		}
		case 'connect': {
			const connection = cloudConnectionFromRequest(request);
			const expectedVersion = cloudExpectedVersionFromRequest(request);
			const rollbackToken = crypto.randomBytes(32).toString('base64url');
			return {
				status: await connectSplunkCloudWithStorage({
					configureObserver: () => postObserverCloudJSON(
						'/api/splunk/export',
						{ ...connection, expectedVersion },
						rollbackToken,
					),
					readStoredState: () => readStoredCloudConnectionState(context),
					rollbackObserver: async (rollbackToken) => {
						await postObserverCloudJSON('/api/splunk/export/rollback', { rollbackToken });
					},
					rollbackToken,
					restoreStoredState: (state) => restoreStoredCloudConnectionState(
						context,
						state.connectionValue,
						state.exportEnabled,
					),
					storeConnectedState: async () => {
						await writeSplunkCloudConnectionValue(context, JSON.stringify(connection));
						await writeSplunkCloudExportPreference(context, false);
					},
				}),
			};
		}
		case 'set-enabled': {
			if (typeof request.payload?.enabled !== 'boolean') {
				throw new Error('Remote export state is missing.');
			}
			const expectedVersion = cloudExpectedVersionFromRequest(request);
			const rollbackToken = crypto.randomBytes(32).toString('base64url');
			return {
				status: await setSplunkCloudExportEnabledWithStorage({
					enabled: request.payload.enabled,
					readStoredState: () => readStoredCloudConnectionState(context),
					rollbackObserver: async (rollbackToken) => {
						await postObserverCloudJSON('/api/splunk/export/rollback', { rollbackToken });
					},
					rollbackToken,
					restoreStoredExportEnabled: async (enabled) => {
						await writeSplunkCloudExportPreference(context, enabled);
					},
					setObserverEnabled: (enabled) => postObserverCloudJSON(
						'/api/splunk/export/enabled',
						{ enabled, expectedVersion },
						rollbackToken,
					),
					storeExportEnabled: async (enabled) => {
						await writeSplunkCloudExportPreference(context, enabled);
					},
				}),
			};
		}
		case 'forget':
			return {
				status: await forgetSplunkCloudConnection(
					context,
					cloudExpectedVersionFromRequest(request),
				),
			};
	}
}

async function openCloudExternalUrl(url: string): Promise<void> {
	const opened = await vscode.env.openExternal(vscode.Uri.parse(url));
	if (!opened) {
		throw new Error('VS Code could not open the external page.');
	}
}

function cloudConnectionFromRequest(
	request: { action: CloudBridgeAction; payload?: ObserverHostCloudPayload },
): StoredSplunkCloudConnection {
	const accessToken = request.payload?.accessToken?.trim() ?? '';
	const realm = request.payload?.realm?.trim().toLowerCase() ?? '';
	const parsed = parseStoredSplunkCloudConnection(JSON.stringify({ accessToken, realm }));
	if (parsed === undefined) {
		throw new Error('Enter a valid Splunk Observability Cloud realm and access token.');
	}
	return parsed;
}

function cloudExpectedVersionFromRequest(
	request: { action: CloudBridgeAction; payload?: ObserverHostCloudPayload },
): string | undefined {
	const expectedVersion = request.payload?.expectedVersion;
	return typeof expectedVersion === 'string' ? expectedVersion : undefined;
}

async function refreshSplunkCloudConnection(context: vscode.ExtensionContext): Promise<unknown> {
	const usesSharedObserver = observerUsesSharedServer;
	return restoreSplunkCloudConnectionFromStorage({
		configure: (connection, expectedVersion) => verifyStoredSplunkCloudConnection(
			() => postObserverCloudJSON('/api/splunk/export', { ...connection, expectedVersion }),
		),
		readConnection: async () => parseStoredSplunkCloudConnection(
			await readSplunkCloudConnectionValue(context),
		),
		readExportEnabled: () => readSplunkCloudExportPreference(context),
		refresh: () => initializeSplunkCloudStatus({
			isManagedObserver: !usesSharedObserver,
			readStatus: () => getObserverCloudJSON('/api/splunk/export'),
			refreshManagedStatus: () => refreshObserverCloudStatus(),
		}),
		restoreStoredConnection: !usesSharedObserver,
		setEnabled: (enabled, expectedVersion) => postObserverCloudJSON(
			'/api/splunk/export/enabled',
			{ enabled, expectedVersion },
		),
	});
}

async function refreshObserverCloudStatus(): Promise<unknown> {
	return postObserverCloudJSON('/api/splunk/export/refresh', {});
}

async function restoreManagedObserverCloudConnection(context: vscode.ExtensionContext): Promise<void> {
	try {
		const status = await refreshSplunkCloudConnection(context);
		if (cloudStatusConnected(status)) {
			appendObserverOutputLine('[splunk-export] restored cloud connection.');
		}
	} catch (error) {
		appendObserverOutputLine(
			`[splunk-export] could not restore cloud connection: ${getErrorMessage(error)}`,
		);
	}
}

async function forgetSplunkCloudConnection(
	context: vscode.ExtensionContext,
	expectedVersion: string | undefined,
): Promise<unknown> {
	const rollbackToken = crypto.randomBytes(32).toString('base64url');
	return forgetSplunkCloudWithStorage({
		clearStoredState: async () => {
			await writeSplunkCloudConnectionValue(context, undefined);
			await writeSplunkCloudExportPreference(context, undefined);
		},
		forgetObserver: () => postObserverCloudJSON(
			'/api/splunk/export/forget',
			{ expectedVersion },
			rollbackToken,
		),
		readStoredState: () => readStoredCloudConnectionState(context),
		rollbackObserver: async (rollbackToken) => {
			await postObserverCloudJSON('/api/splunk/export/rollback', { rollbackToken });
		},
		rollbackToken,
		restoreStoredState: (state) => restoreStoredCloudConnectionState(
			context,
			state.connectionValue,
			state.exportEnabled,
		),
	});
}

async function readStoredCloudConnectionState(context: vscode.ExtensionContext) {
	return {
		connectionValue: await readSplunkCloudConnectionValue(context),
		exportEnabled: readSplunkCloudExportPreference(context),
	};
}

async function restoreStoredCloudConnectionState(
	context: vscode.ExtensionContext,
	storedValue: string | undefined,
	storedExportEnabled: boolean | undefined,
): Promise<void> {
	await writeSplunkCloudStatePair({
		state: { connectionValue: storedValue, exportEnabled: storedExportEnabled },
		writeConnection: (value) => writeSplunkCloudConnectionValue(context, value),
		writeExportEnabled: (value) => writeSplunkCloudExportPreference(context, value),
	});
}

function readSplunkCloudConnectionValue(
	context: vscode.ExtensionContext,
): Promise<string | undefined> {
	return splunkCloudConnectionStore.read(
		() => Promise.resolve(context.secrets.get(splunkCloudConnectionSecretKey)),
	);
}

function writeSplunkCloudConnectionValue(
	context: vscode.ExtensionContext,
	value: string | undefined,
): Promise<void> {
	return splunkCloudConnectionStore.write(value, async (current) => {
		if (current === undefined) {
			await context.secrets.delete(splunkCloudConnectionSecretKey);
		} else {
			await context.secrets.store(splunkCloudConnectionSecretKey, current);
		}
	});
}

function readSplunkCloudExportPreference(context: vscode.ExtensionContext): boolean | undefined {
	return splunkCloudExportPreferenceStore.read(
		() => context.globalState.get<boolean>(splunkCloudExportEnabledStateKey),
	);
}

function writeSplunkCloudExportPreference(
	context: vscode.ExtensionContext,
	enabled: boolean | undefined,
): Promise<void> {
	return splunkCloudExportPreferenceStore.write(
		enabled,
		(value) => Promise.resolve(context.globalState.update(splunkCloudExportEnabledStateKey, value)),
	);
}

async function requestObserverHostHTTP(
	method: 'GET' | 'POST',
	pathname: string,
	body: string | undefined,
	signal: AbortSignal,
): Promise<{
	body: string;
	headers?: Record<string, string>;
	status: number;
	statusText: string;
}> {
	if (observerBaseUrl === undefined || observerLifecycleState.status !== 'running') {
		throw new Error('Observer is not running.');
	}
	if (signal.aborted) {
		throw new Error('Observer request was cancelled.');
	}

	const url = buildObserverApiUrl(pathname);
	if (url.protocol !== 'http:' && url.protocol !== 'https:') {
		throw new Error('Observer requests require HTTP or HTTPS.');
	}
	if (!isLoopbackObserverHost(url.hostname)) {
		throw new Error('Observer requests require a loopback Observer.');
	}

	const payload = body === undefined ? undefined : Buffer.from(body, 'utf8');
	const responseByteLimit = observerHostResponseByteLimit(url);
	const headers: http.OutgoingHttpHeaders = { Accept: 'application/json' };
	if (payload !== undefined) {
		headers['Content-Length'] = String(payload.length);
		headers['Content-Type'] = 'application/json';
	}
	const transport = url.protocol === 'https:' ? https : http;
	return new Promise((resolve, reject) => {
		let settled = false;
		const finish = (callback: () => void) => {
			if (settled) {
				return;
			}
			settled = true;
			signal.removeEventListener('abort', onAbort);
			callback();
		};
		const request = transport.request(url, { headers, method }, (response) => {
			void collectObserverHostHTTPResponse(response, request, responseByteLimit).then(
				(result) => finish(() => resolve(result)),
				(error: Error) => finish(() => reject(error)),
			);
		});
		const onAbort = () => request.destroy(new Error('Observer request was cancelled.'));
		signal.addEventListener('abort', onAbort, { once: true });
		request.setTimeout(15_000, () => {
			request.destroy(new Error('Observer request timed out.'));
		});
		request.once('error', (error) => finish(() => reject(error)));
		request.end(payload);
	});
}

async function getObserverCloudJSON(
	pathname: string,
	timeoutMs = observerCloudRequestTimeoutMs,
): Promise<unknown> {
	if (observerBaseUrl === undefined || observerLifecycleState.status !== 'running') {
		throw new Error('Observer is not running.');
	}

	const url = buildObserverApiUrl(pathname);
	if (!isLoopbackObserverHost(url.hostname)) {
		throw new Error('Observer cloud requests require a loopback Observer.');
	}

	const response = await requestObserverCloudJSON(url, undefined, timeoutMs);
	if (response.statusCode >= 200 && response.statusCode < 300) {
		return response.body;
	}
	throw observerCloudResponseError(response.statusCode, response.body);
}

async function requestObserverFreeAccountJSON(
	pathname: string,
	body: Record<string, unknown> | undefined,
	timeoutMs: number,
): Promise<unknown> {
	if (observerBaseUrl === undefined || observerLifecycleState.status !== 'running') {
		throw new ObserverCloudRequestError(
			'Observer is not running.',
			'observer_unavailable',
			true,
		);
	}
	const url = buildObserverApiUrl(pathname);
	if (!isLoopbackObserverHost(url.hostname)) {
		throw new ObserverCloudRequestError(
			'Free Edition signup requires a loopback Observer.',
			'insecure_observer',
			true,
		);
	}

	try {
		const response = await requestObserverCloudJSON(url, body, timeoutMs);
		if (response.statusCode >= 200 && response.statusCode < 300) {
			return response.body;
		}
		throw observerCloudResponseError(response.statusCode, response.body);
	} catch (error) {
		if (error instanceof ObserverCloudRequestError) {
			throw error;
		}
		if (error instanceof ObserverCloudResponseError) {
			if (body === undefined || !freeAccountSubmissionFailureIsOutcomeUnknown(error)) {
				throw error;
			}
			throw new ObserverCloudRequestError(
				'The signup outcome is unknown. Check your email before trying again.',
				'outcome_unknown',
				false,
			);
		}
		throw new ObserverCloudRequestError(
			body === undefined
				? getErrorMessage(error)
				: 'The signup outcome is unknown. Check your inbox before submitting again.',
			body === undefined ? 'region_detection_failed' : 'outcome_unknown',
			body === undefined,
		);
	}
}

async function postObserverCloudJSON(
	pathname: string,
	body: Record<string, unknown>,
	rollbackToken?: string,
): Promise<unknown> {
	if (observerBaseUrl === undefined || observerLifecycleState.status !== 'running') {
		throw new Error('Observer is not running.');
	}

	const url = buildObserverApiUrl(pathname);
	if (!isLoopbackObserverHost(url.hostname)) {
		throw new Error('Cloud connection changes require a loopback Observer.');
	}
	const response = await requestObserverCloudJSON(
		url,
		body,
		observerCloudRequestTimeoutMs,
		rollbackToken,
	);
	if (response.statusCode >= 200 && response.statusCode < 300) {
		return response.body;
	}
	throw observerCloudResponseError(response.statusCode, response.body);
}

async function requestObserverCloudJSON(
	url: URL,
	body: Record<string, unknown> | undefined,
	timeoutMs = observerCloudRequestTimeoutMs,
	rollbackToken?: string,
): Promise<{ body: unknown; statusCode: number }> {
	const payload = body === undefined ? undefined : Buffer.from(JSON.stringify(body), 'utf8');
	const headers: http.OutgoingHttpHeaders = {
		Accept: 'application/json',
	};
	if (rollbackToken !== undefined) {
		headers[observerCloudRollbackTokenHeader] = rollbackToken;
	}
	if (payload !== undefined) {
		headers['Content-Length'] = String(payload.length);
		headers['Content-Type'] = 'application/json';
	}
	const transport = url.protocol === 'https:' ? https : http;
	return new Promise((resolve, reject) => {
		let settled = false;
		let timeout: NodeJS.Timeout | undefined;
		const finish = (callback: () => void) => {
			if (settled) {
				return;
			}
			settled = true;
			if (timeout !== undefined) {
				clearTimeout(timeout);
			}
			callback();
		};
		const request = transport.request(url, {
			headers,
			method: payload === undefined ? 'GET' : 'POST',
		}, (response) => {
			void collectObserverHostHTTPResponse(response, request, 1024 * 1024).then((result) => {
				try {
					const parsedBody = parseObserverCloudResponseBody(result.status, result.body);
					finish(() => resolve({ body: parsedBody, statusCode: result.status }));
				} catch (error) {
					finish(() => reject(error));
				}
			}, (error: Error) => finish(() => reject(error)));
		});
		timeout = setTimeout(() => {
			const error = new Error('Observer cloud request timed out.');
			request.destroy(error);
			finish(() => reject(error));
		}, timeoutMs);
		request.once('error', (error) => finish(() => reject(error)));
		request.end(payload);
	});
}

function freeAccountRegionFromResponse(value: unknown): string {
	const region = typeof value === 'object' && value !== null
		? (value as Record<string, unknown>).region
		: undefined;
	if (typeof region !== 'string' || !isSupportedFreeAccountRegion(region)) {
		throw new ObserverCloudRequestError(
			'Observer returned an invalid Free Edition region.',
			'invalid_response',
			true,
		);
	}
	return region;
}

function splunkRealmFromResponse(value: unknown): string {
	const realm = typeof value === 'object' && value !== null
		? (value as Record<string, unknown>).realm
		: undefined;
	if (typeof realm !== 'string' || !/^[a-z]{2,12}[0-9]+$/.test(realm)) {
		throw new Error('Observer returned an invalid Splunk Observability Cloud realm.');
	}
	return realm;
}

function cloudBridgeErrorMetadata(error: unknown): { code?: string; retrySafe?: boolean } {
	if (error instanceof ObserverCloudRequestError || error instanceof ObserverCloudResponseError) {
		return { code: error.code, retrySafe: error.retrySafe };
	}
	return {};
}

function buildObserverApiUrl(pathname: string): URL {
	if (observerBaseUrl === undefined) {
		throw new Error('Observer is not running.');
	}
	const normalizedBase = `${normalizeObserverBaseUrl(observerBaseUrl)}/`;
	const relativePath = pathname.replace(/^\/+/, '');
	return new URL(relativePath, normalizedBase);
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
	endpoints: ObserverEndpointRoles,
	options: ObserverProbeOptions,
	runId: number,
): Promise<Extract<ObserverProbeResult, { status: 'ready' }>> {
	const startupDeadline = Date.now() + 15_000;
	// A freshly-built, not-yet-scanned binary's very first connections can get an empty
	// response from local security/network-filtering software (observed with Cisco Secure
	// Endpoint's content filter) rather than from a genuinely different service. Two
	// closely-spaced retries were not enough to reliably outlast that window, so this
	// allows several, spaced further apart, while staying well inside startupDeadline.
	const maxMismatchAttempts = 6;
	const mismatchRetryDelayMs = 250;
	let lastError: Error | undefined;
	let mismatchAttempts = 0;

	while (Date.now() < startupDeadline) {
		assertObserverRunCurrent(observerLifecycleState, runId);

		const probe = await probeObserver(endpoints, 500, options);
		assertObserverRunCurrent(observerLifecycleState, runId);

		switch (probe.status) {
			case 'ready':
				return probe;
			case 'mismatch': {
				mismatchAttempts += 1;
				appendObserverOutputLine(`Observer health probe mismatch at ${endpoints.healthUrl}: ${probe.reason}`);
				logObserverLifecycle(`Run ${runId}: observer health probe mismatch at ${endpoints.healthUrl}: ${probe.reason}`);
				if (mismatchAttempts < maxMismatchAttempts) {
					logObserverLifecycle(
						`Run ${runId}: retrying after mismatch (attempt ${mismatchAttempts} of ${maxMismatchAttempts}).`,
					);
					await delay(mismatchRetryDelayMs);
					break;
				}
				const mismatchContext = observerUsesSharedServer ? 'shared-reuse' : 'startup-reuse';
				const wrappedError = new Error(formatObserverProbeMismatchMessage(endpoints.restBaseUrl, mismatchContext));
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
		appendObserverOutputLine(`Observer health probe unavailable at ${endpoints.healthUrl}: ${rawProbeDetail}`);
		logObserverLifecycle(`Run ${runId}: observer readiness failed for ${endpoints.healthUrl}: ${rawProbeDetail}`);
		const unavailableContext = observerUsesSharedServer ? 'shared-reuse' : 'startup';
		const wrappedError = new Error(formatObserverProbeUnavailableMessage(endpoints.restBaseUrl, unavailableContext));
		Object.assign(wrappedError, { startupHint: getObserverProbeUnavailableHint(unavailableContext) });
		throw wrappedError;
	}
	const unavailableContext = observerUsesSharedServer ? 'shared-reuse' : 'startup';
	logObserverLifecycle(`Run ${runId}: observer readiness ended without a probe result at ${endpoints.healthUrl}.`);
	const wrappedError = new Error(formatObserverProbeUnavailableMessage(endpoints.restBaseUrl, unavailableContext));
	Object.assign(wrappedError, { startupHint: getObserverProbeUnavailableHint(unavailableContext) });
	throw wrappedError;
}

async function probeObserver(
	endpoints: ObserverEndpointRoles,
	timeoutMs: number,
	options: ObserverProbeOptions,
): Promise<ObserverProbeResult> {
	return new Promise((resolve) => {
		const target = new URL(endpoints.healthUrl);
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
					const contentType = response.headers['content-type'] ?? '(none)';
					finish(() => resolve({
						status: 'mismatch',
						reason: `${target.toString()} returned invalid JSON `
							+ `(content-type: ${contentType}, length: ${body.length})`,
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

function enqueueObserverConfigurationRestart(context: vscode.ExtensionContext): Promise<void> {
	const previousRestart = observerConfigurationRestartOperation;
	let restartOperation: Promise<void>;
	restartOperation = (previousRestart === undefined
		? restartObserver(context)
		: previousRestart.catch(() => undefined).then(() => restartObserver(context))
	).finally(() => {
		if (observerConfigurationRestartOperation === restartOperation) {
			observerConfigurationRestartOperation = undefined;
		}
	});
	observerConfigurationRestartOperation = restartOperation;
	return restartOperation;
}

async function waitForObserverConfigurationRestartCompletion(): Promise<void> {
	let firstError: unknown;
	while (observerConfigurationRestartOperation !== undefined) {
		const operation = observerConfigurationRestartOperation;
		try {
			await operation;
		} catch (error) {
			firstError ??= error;
		}
		if (observerConfigurationRestartOperation === operation) {
			observerConfigurationRestartOperation = undefined;
		}
	}
	if (firstError !== undefined) {
		throw firstError;
	}
}

async function settleObserverConfigurationRestart(): Promise<void> {
	try {
		await waitForObserverConfigurationRestartCompletion();
	} catch (error) {
		logObserverLifecycle(`Prior Observer configuration restart failed: ${getErrorMessage(error)}`);
	}
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

function getObserverWebviewHtmlForPanel(panel: vscode.WebviewPanel): string {
	if (observerWebviewRootUri === undefined) {
		throw new Error('Observer webview assets are not configured.');
	}
	const scriptUri = panel.webview.asWebviewUri(
		vscode.Uri.joinPath(observerWebviewRootUri, 'main.js'),
	).toString();
	const styleUri = panel.webview.asWebviewUri(
		vscode.Uri.joinPath(observerWebviewRootUri, 'main.css'),
	).toString();
	return getObserverWebviewHtml(
		panel.webview.cspSource,
		scriptUri,
		styleUri,
	);
}

function disposeObserverPanelRuntime(): void {
	observerPanelTelemetry?.dispose();
	observerPanelTelemetry = undefined;
	for (const cancel of observerHostRequestCancellations.values()) {
		cancel();
	}
	observerHostRequestCancellations.clear();
}

function delay(ms: number): Promise<void> {
	return new Promise((resolve) => { setTimeout(resolve, ms); });
}

function buildManagedObserverBaseUrl(port: number): string {
	return `http://${managedObserverHost}:${port}`;
}

function parseInternalTestPort(value: unknown, fallback: number): number {
	if (value === undefined) {
		return fallback;
	}
	if (typeof value !== 'number' || !Number.isSafeInteger(value) || value <= 0 || value > 65_535) {
		throw new Error('Observer test OTLP ports must be integers between 1 and 65535.');
	}
	return value;
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
	return normalizeSharedObserverBaseUrl(trimmed);
}

function getDetectedAgentIntegrations(): AgentIntegrationSpec[] {
	const home = os.homedir();
	return agentIntegrationSpecs.filter((spec) => spec.detectPaths(home).some((candidate) => fs.existsSync(candidate)));
}

function integrationPromptDismissalKey(target: AgentIntegrationTarget): string {
	return `${agentIntegrationPromptDismissedPrefix}${target}`;
}

function agentIntegrationConfigFingerprintKey(target: AgentIntegrationTarget): string {
	return `${agentIntegrationConfigFingerprintPrefix}${target}`;
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

async function waitForAgentIntegrationRefreshCompletion(): Promise<void> {
	let firstError: unknown;
	while (agentIntegrationRefreshOperation !== undefined) {
		const operation = agentIntegrationRefreshOperation;
		try {
			await operation.promise;
		} catch (error) {
			firstError ??= error;
		}
		if (agentIntegrationRefreshOperation?.promise === operation.promise) {
			agentIntegrationRefreshOperation = undefined;
		}
	}
	if (firstError !== undefined) {
		throw firstError;
	}
}

async function waitForAgentIntegrationConfigurationCompletion(): Promise<void> {
	while (agentIntegrationConfigurationOperations.size > 0) {
		await Promise.allSettled([...agentIntegrationConfigurationOperations]);
	}
}

function getStoredAgentIntegrationConfigFingerprint(
	context: vscode.ExtensionContext,
	target: AgentIntegrationTarget,
): unknown {
	return agentIntegrationConfigFingerprints.get(target)
		?? context.globalState.get<unknown>(agentIntegrationConfigFingerprintKey(target));
}

function sortJSONValue(value: unknown): unknown {
	if (Array.isArray(value)) {
		return value.map(sortJSONValue);
	}
	if (typeof value !== 'object' || value === null) {
		return value;
	}
	return Object.fromEntries(
		Object.entries(value as Record<string, unknown>)
			.sort(([left], [right]) => left.localeCompare(right))
			.map(([key, child]) => [key, sortJSONValue(child)]),
	);
}

function readAgentIntegrationManagedConfig(spec: AgentIntegrationSpec): AgentIntegrationManagedConfig | undefined {
	const configPath = spec.configPath(os.homedir());
	if (!fs.existsSync(configPath)) {
		return undefined;
	}

	try {
		if (spec.configFormat === 'json') {
			const parsed: unknown = JSON.parse(fs.readFileSync(configPath, 'utf8'));
			if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
				return undefined;
			}
			const servers = (parsed as Record<string, unknown>).mcpServers;
			if (typeof servers !== 'object' || servers === null || Array.isArray(servers)) {
				return undefined;
			}
			const server = (servers as Record<string, unknown>).obstudio;
			if (typeof server !== 'object' || server === null || Array.isArray(server)) {
				return undefined;
			}
			const mcpUrl = (server as Record<string, unknown>).url;
			if (typeof mcpUrl !== 'string') {
				return undefined;
			}
			return {
				fingerprintMaterial: JSON.stringify(sortJSONValue(server)),
				mcpUrl,
			};
		}

		const section = getCodexObstudioSection(fs.readFileSync(configPath, 'utf8'));
		if (section === undefined) {
			return undefined;
		}
		const mcpUrl = getCodexObstudioUrl(section);
		if (mcpUrl === undefined) {
			return undefined;
		}
		return { fingerprintMaterial: section, mcpUrl };
	} catch {
		return undefined;
	}
}

function getAgentIntegrationConfigState(
	spec: AgentIntegrationSpec,
	mcpUrl: string,
): AgentIntegrationConfigState {
	const configPath = spec.configPath(os.homedir());
	if (!fs.existsSync(configPath)) {
		return 'missing';
	}

	try {
		if (spec.configFormat === 'json') {
			const config = JSON.parse(fs.readFileSync(configPath, 'utf8')) as {
				mcpServers?: Record<string, {
					args?: unknown;
					command?: unknown;
					headers?: Record<string, unknown>;
					type?: string;
					url?: string;
				}>;
			};
			const server = config.mcpServers?.obstudio;
			if (server === undefined) {
				return 'missing';
			}
			const remoteTypeMatches = spec.jsonRemoteType === undefined
				? server.type === undefined
				: server.type === spec.jsonRemoteType;
			const hasIncompatibleRemoteFields = spec.jsonRemoteIncompatibleFields?.some(
				(field) => server[field] !== undefined,
			) ?? false;
			return remoteTypeMatches
				&& server.url === mcpUrl
				&& !hasIncompatibleRemoteFields
				&& hasNoAuthorizationHeader(server.headers)
				? 'matching'
				: 'different';
		}

		const content = fs.readFileSync(configPath, 'utf8');
		const section = getCodexObstudioSection(content);
		if (section === undefined) {
			return 'missing';
		}
		return getCodexObstudioUrl(section) === mcpUrl
			&& codexObstudioHasNoAuthorization(section)
			? 'matching'
			: 'different';
	} catch {
		return 'different';
	}
}

function hasInstalledAgentSkills(spec: AgentIntegrationSpec): boolean {
	return fs.existsSync(spec.skillsSentinelPath(os.homedir()));
}

function getBundleVersion(context: vscode.ExtensionContext): string {
	const v: unknown = context.extension.packageJSON.version;
	return typeof v === 'string' && v.length > 0 ? v : '0.0.0';
}

function getStoredSkillsBundleVersion(context: vscode.ExtensionContext, target: AgentIntegrationTarget): string | undefined {
	return context.globalState.get<string>(`${agentSkillsBundleVersionPrefix}${target}`);
}

async function recordSkillsBundleVersion(context: vscode.ExtensionContext, target: AgentIntegrationTarget): Promise<void> {
	await context.globalState.update(`${agentSkillsBundleVersionPrefix}${target}`, getBundleVersion(context));
}

function skillsBundleVersionChanged(context: vscode.ExtensionContext, target: AgentIntegrationTarget): boolean {
	const stored = getStoredSkillsBundleVersion(context, target);
	// A missing stored version means this install predates bundle-version tracking.
	// Treat it as "not changed" so we don't re-prompt on the first activation after
	// this feature was added — but stamp the current version so that future upgrades
	// correctly trigger re-installs via the explicit version-change path.
	if (stored === undefined) {
		void recordSkillsBundleVersion(context, target);
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

async function recordAgentIntegrationConfigFingerprint(
	context: vscode.ExtensionContext,
	spec: AgentIntegrationSpec,
	mcpUrl: string,
	expectedConfig: AgentIntegrationManagedConfig,
): Promise<void> {
	if (getAgentIntegrationConfigState(spec, mcpUrl) !== 'matching') {
		throw new Error(`${spec.label} MCP configuration could not be verified after installation.`);
	}
	const managedConfig = readAgentIntegrationManagedConfig(spec);
	if (managedConfig === undefined) {
		throw new Error(`${spec.label} MCP configuration could not be fingerprinted after installation.`);
	}
	if (managedConfig.mcpUrl !== expectedConfig.mcpUrl
		|| managedConfig.fingerprintMaterial !== expectedConfig.fingerprintMaterial) {
		throw new Error(`${spec.label} MCP configuration changed before installation could be recorded.`);
	}
	const fingerprint = createAgentIntegrationConfigFingerprint(managedConfig);
	await context.globalState.update(
		agentIntegrationConfigFingerprintKey(spec.target),
		fingerprint,
	);
	agentIntegrationConfigFingerprints.set(spec.target, fingerprint);
}

async function configureDetectedAgentIntegrations(
	context: vscode.ExtensionContext,
	specs = getDetectedAgentIntegrations(),
	showSuccessMessage = true,
	forceAll = false,
	shouldContinue: () => boolean = () => true,
	shouldConfigure: (spec: AgentIntegrationSpec) => boolean = () => true,
): Promise<string[]> {
	await ensureObserverRunning(context);
	if (observerEndpoints === undefined) {
		throw new Error('Observer MCP URL is not available.');
	}

	const mcpUrl = observerEndpoints.mcpUrl;
	const configured: string[] = [];
	for (const spec of specs) {
		if (!shouldContinue()) {
			break;
		}
		if (!shouldConfigure(spec)) {
			continue;
		}
		if (!forceAll && !needsAgentIntegrationUpdate(spec, mcpUrl, context)) {
			continue;
		}

		try {
			const completed = await configureAgentMCP(
				context,
				spec.target,
				spec.label,
				false,
				() => shouldContinue()
					&& observerEndpoints?.mcpUrl === mcpUrl
					&& shouldConfigure(spec),
			);
			if (completed) {
				configured.push(spec.label);
			}
		} catch {
			continue;
		}
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

function refreshOwnedAgentIntegrationConfig(
	context: vscode.ExtensionContext,
	specs: AgentIntegrationSpec[],
	mcpUrl: string,
): Promise<string[]> {
	const operationKey = crypto.createHash('sha256')
		.update(`${mcpUrl}\0${specs.map((spec) => spec.target).join(',')}`)
		.digest('hex');
	if (agentIntegrationRefreshOperation !== undefined) {
		if (agentIntegrationRefreshOperation.key === operationKey) {
			return agentIntegrationRefreshOperation.promise;
		}
	}

	const previousRefresh = agentIntegrationRefreshOperation?.promise;
	const runRefresh = async (): Promise<string[]> => {
		if (observerEndpoints?.mcpUrl !== mcpUrl) {
			return [];
		}
		const shouldRefresh = (spec: AgentIntegrationSpec): boolean => (
			getAgentIntegrationConfigState(spec, mcpUrl) === 'different'
			&& shouldRefreshOwnedAgentIntegrationConfig(
				getStoredAgentIntegrationConfigFingerprint(context, spec.target),
				readAgentIntegrationManagedConfig(spec),
				mcpUrl,
			)
		);
		const refreshable = specs.filter(shouldRefresh);
		if (refreshable.length === 0) {
			return [];
		}

		const refreshed = await configureDetectedAgentIntegrations(
			context,
			refreshable,
			false,
			true,
			() => observerEndpoints?.mcpUrl === mcpUrl,
			shouldRefresh,
		);
		if (refreshed.length > 0) {
			const labelList = formatAgentLabelList(refreshed);
			void vscode.window.showInformationMessage(
				`${labelList} Observer configuration refreshed. Restart ${labelList} before starting a new task.`,
			);
		}
		return refreshed;
	};
	let refreshPromise: Promise<string[]>;
	refreshPromise = (previousRefresh === undefined
		? runRefresh()
		: previousRefresh.catch(() => []).then(runRefresh)
	).finally(() => {
		if (agentIntegrationRefreshOperation?.promise === refreshPromise) {
			agentIntegrationRefreshOperation = undefined;
		}
	});

	agentIntegrationRefreshOperation = { key: operationKey, promise: refreshPromise };
	return refreshPromise;
}

async function maybeOfferDetectedAgentIntegrations(context: vscode.ExtensionContext): Promise<void> {
	if (observerEndpoints === undefined) {
		return;
	}

	const offerGeneration = agentIntegrationPromptGeneration;
	const mcpUrl = observerEndpoints.mcpUrl;
	const detectedSpecs = getDetectedAgentIntegrations();
	try {
		await refreshOwnedAgentIntegrationConfig(context, detectedSpecs, mcpUrl);
	} catch (error) {
		appendObserverOutputLine(`Automatic agent configuration refresh failed: ${getErrorMessage(error)}`);
	}
	if (
		offerGeneration !== agentIntegrationPromptGeneration
		|| observerEndpoints?.mcpUrl !== mcpUrl
	) {
		return;
	}
	if (agentIntegrationPromptPromise !== undefined) {
		if (agentIntegrationPromptMcpUrl === mcpUrl) {
			return agentIntegrationPromptPromise;
		}
		agentIntegrationPromptGeneration += 1;
		agentIntegrationPromptPromise = undefined;
		agentIntegrationPromptMcpUrl = undefined;
	}

	const promptGeneration = agentIntegrationPromptGeneration + 1;
	agentIntegrationPromptGeneration = promptGeneration;
	const promptPromise = (async () => {
		const shownSpecs = detectedSpecs.filter((spec) => {
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
		if (
			promptGeneration !== agentIntegrationPromptGeneration
			|| observerEndpoints?.mcpUrl !== mcpUrl
		) {
			return;
		}
		if (choice === 'Enable') {
			let promptInstall: Promise<string[]>;
			promptInstall = configureDetectedAgentIntegrations(
				context,
				shownSpecs,
				true,
				true,
				() => promptGeneration === agentIntegrationPromptGeneration
					&& observerEndpoints?.mcpUrl === mcpUrl,
			).finally(() => {
				agentIntegrationPromptInstallOperations.delete(promptInstall);
			});
			agentIntegrationPromptInstallOperations.add(promptInstall);
			await promptInstall;
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
			agentIntegrationPromptMcpUrl = undefined;
		}
	});

	agentIntegrationPromptPromise = promptPromise;
	agentIntegrationPromptMcpUrl = mcpUrl;
	return promptPromise;
}

async function configureAgentMCP(
	context: vscode.ExtensionContext,
	target: AgentIntegrationTarget,
	label: string,
	showSuccessMessage = true,
	shouldContinue: () => boolean = () => true,
): Promise<boolean> {
	const operation = agentIntegrationConfigurationQueue.run(async () => {
		if (!shouldContinue()) {
			return false;
		}
		return configureAgentMCPNow(context, target, label, showSuccessMessage, shouldContinue);
	});
	agentIntegrationConfigurationOperations.add(operation);
	try {
		return await operation;
	} finally {
		agentIntegrationConfigurationOperations.delete(operation);
	}
}

async function configureAgentMCPNow(
	context: vscode.ExtensionContext,
	target: AgentIntegrationTarget,
	label: string,
	showSuccessMessage: boolean,
	shouldContinue: () => boolean = () => true,
): Promise<boolean> {
	const outputChannel = observerOutputChannel;
	if (outputChannel === undefined) {
		throw new Error('Observer output channel is not initialized.');
	}

	try {
		await ensureObserverRunning(context);
		if (!shouldContinue()) {
			return false;
		}
		if (observerEndpoints === undefined) {
			throw new Error('Observer MCP URL is not available.');
		}

		const spec = agentIntegrationSpecs.find((candidate) => candidate.target === target);
		if (spec === undefined) {
			throw new Error(`Unsupported agent integration target: ${target}`);
		}
		const backend = resolveBackend(context.extensionPath);
		if (!shouldContinue()) {
			return false;
		}
		const mcpUrl = observerEndpoints.mcpUrl;
		outputChannel.appendLine(`Enabling ${label} integration for ${mcpUrl}`);
		const installOutput = await execFile(
			backend.command,
			['install', '--target', target, '--shared-url', mcpUrl],
			backend.cwd,
			backend.env,
		);
		if (installOutput.length > 0) {
			outputChannel.append(installOutput);
			if (!installOutput.endsWith('\n')) {
				outputChannel.appendLine('');
			}
		}
		if (!shouldContinue() || observerEndpoints?.mcpUrl !== mcpUrl) {
			throw new Error('Observer MCP endpoint changed during integration setup; retry with the active Observer.');
		}
		if (getAgentIntegrationConfigState(spec, mcpUrl) !== 'matching') {
			throw new Error(`${spec.label} MCP configuration could not be verified after installation.`);
		}
		const installedConfig = readAgentIntegrationManagedConfig(spec);
		if (installedConfig === undefined) {
			throw new Error(`${spec.label} MCP configuration could not be fingerprinted after installation.`);
		}
		await recordAgentIntegrationConfigFingerprint(context, spec, mcpUrl, installedConfig);
		await context.globalState.update(integrationPromptDismissalKey(target), undefined);
		// Record the bundle version so that future version changes trigger a re-install.
		await recordSkillsBundleVersion(context, target);
		outputChannel.appendLine(`${label} integration enabled for ${mcpUrl}`);
		if (showSuccessMessage) {
			void vscode.window.showInformationMessage(
				`${label} integration enabled. Restart ${label} to load the bundled skills.`,
			);
		}
		return true;
	} catch (error) {
		const message = `${label} integration failed: ${getErrorMessage(error)}`;
		outputChannel.appendLine(message);
		if (showSuccessMessage) {
			void vscode.window.showErrorMessage(message);
		}
		throw error;
	}
}

function execFile(
	command: string,
	args: string[],
	cwd: string,
	envOverrides: NodeJS.ProcessEnv = {},
): Promise<string> {
	return new Promise((resolve, reject) => {
		cp.execFile(command, args, {
			cwd,
			encoding: 'utf8',
			env: { ...process.env, ...envOverrides },
		}, (error, stdout) => {
			if (error) {
				reject(error);
				return;
			}
			resolve(stdout);
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
