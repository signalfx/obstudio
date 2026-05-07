export type ObserverPortRole = 'Observer UI' | 'OTLP/HTTP' | 'OTLP/gRPC';
export type ObserverStartupFailureKind = 'generic' | 'not-executable' | 'port-conflict' | 'wrong-platform';
export type ObserverStartupFailure = {
	hint: string;
	kind: ObserverStartupFailureKind;
	message: string;
};

export type PortConflictDetails = {
	owner?: string;
	port: number;
	role: ObserverPortRole;
	settingName?: string;
};

export type ObserverProbeMismatchContext = 'managed-reuse' | 'shared-reuse' | 'startup-reuse';
export type ObserverProbeUnavailableContext = 'shared-reuse' | 'startup';

const observerOwnerPattern = /\bobstudio(?:\.exe)?\b/i;

export function currentVsCodeTarget(
	platform: NodeJS.Platform | string = process.platform,
	arch: string = process.arch,
): string {
	if (platform === 'darwin' && arch === 'arm64') {
		return 'darwin-arm64';
	}
	if (platform === 'darwin' && arch === 'x64') {
		return 'darwin-x64';
	}
	if (platform === 'linux' && arch === 'x64') {
		return 'linux-x64';
	}
	if (platform === 'win32' && arch === 'x64') {
		return 'win32-x64';
	}
	return `${platform}-${arch}`;
}

export function formatPortConflictMessage(details: PortConflictDetails): string {
	const ownerText = details.owner
		? ` is already in use by "${details.owner}".`
		: ' is already in use.';
	const staleObserver = details.owner !== undefined && observerOwnerPattern.test(details.owner);
	const staleObserverHint = staleObserver
		? ' Another Splunk Observability Studio instance or a stale observer process may still be running.'
		: '';

	if (staleObserver) {
		const resolution = details.settingName
			? ` Close the other VS Code window or terminate the stale observer process, or change observability-studio.${details.settingName}.`
			: ' Close the other VS Code window or terminate the stale observer process before restarting Splunk Observability Studio.';
		return `${details.role} port ${details.port}${ownerText}${staleObserverHint}${resolution}`;
	}

	const resolution = details.settingName
		? ` Stop the other process or change observability-studio.${details.settingName}.`
		: ` Stop the other process that is using the fixed ${details.role} endpoint before starting Splunk Observability Studio.`;
	return `${details.role} port ${details.port}${ownerText}${resolution}`;
}

export function getObserverStartupHint(kind: ObserverStartupFailureKind = 'generic'): string {
	switch (kind) {
		case 'port-conflict':
			return 'Use the Command Palette (Cmd+Shift+P) and run Splunk Observability Studio: Restart Observer after freeing the conflicting port.';
		case 'wrong-platform':
			return 'Install the platform-specific extension package for this machine or configure observability-studio.sharedObserverUrl, then run Splunk Observability Studio: Restart Observer.';
		case 'not-executable':
			return 'Reinstall the extension or restore execute permissions, then run Splunk Observability Studio: Restart Observer.';
		case 'generic':
			return 'Open the Splunk Observability Studio output log, fix the startup problem, then run Splunk Observability Studio: Restart Observer.';
	}
}

export function formatObserverProbeMismatchMessage(
	baseUrl: string,
	context: ObserverProbeMismatchContext,
): string {
	switch (context) {
		case 'managed-reuse':
			return `the service already using ${baseUrl} is not Splunk Observability Studio.`;
		case 'shared-reuse':
			return `the configured shared observer at ${baseUrl} did not respond like Splunk Observability Studio. Verify observability-studio.sharedObserverUrl.`;
		case 'startup-reuse':
			return `a different service responded at ${baseUrl} while Splunk Observability Studio was starting.`;
	}
}

export function getObserverProbeMismatchHint(context: ObserverProbeMismatchContext): string {
	switch (context) {
		case 'managed-reuse':
		case 'startup-reuse':
			return getObserverStartupHint('port-conflict');
		case 'shared-reuse':
			return 'Verify observability-studio.sharedObserverUrl, make sure the shared observer is reachable, then run Splunk Observability Studio: Restart Observer.';
	}
}

export function formatObserverProbeUnavailableMessage(
	baseUrl: string,
	context: ObserverProbeUnavailableContext,
): string {
	switch (context) {
		case 'shared-reuse':
			return `could not reach the configured shared observer at ${baseUrl}. Verify observability-studio.sharedObserverUrl and make sure Splunk Observability Studio is running there.`;
		case 'startup':
			return `Splunk Observability Studio did not become ready at ${baseUrl}.`;
	}
}

export function getObserverProbeUnavailableHint(context: ObserverProbeUnavailableContext): string {
	switch (context) {
		case 'shared-reuse':
			return 'Verify observability-studio.sharedObserverUrl, make sure the shared observer is reachable, then run Splunk Observability Studio: Restart Observer.';
		case 'startup':
			return getObserverStartupHint('generic');
	}
}

export function describeObserverStartupFailure(
	error: NodeJS.ErrnoException | Error | string,
	options: {
		arch?: string;
		binaryPath?: string;
		platform?: NodeJS.Platform | string;
	} = {},
): ObserverStartupFailure {
	const errorMessage = error instanceof Error ? error.message : String(error);
	const code = typeof error === 'object' && error !== null && 'code' in error
		? String((error as NodeJS.ErrnoException).code)
		: undefined;

	if (code === 'ENOEXEC' || /\bENOEXEC\b/i.test(errorMessage)) {
		const target = currentVsCodeTarget(options.platform, options.arch);
		const binaryPath = options.binaryPath ?? 'the bundled observer binary';
		return {
			hint: getObserverStartupHint('wrong-platform'),
			kind: 'wrong-platform',
			message: `${binaryPath} cannot run on ${target} (${errorMessage}). ` +
				'The installed extension package likely contains a binary built for a different operating system or CPU architecture. ' +
				`Install the ${target} extension package or configure observability-studio.sharedObserverUrl.`,
		};
	}

	if (code === 'EACCES' || /\bEACCES\b/i.test(errorMessage)) {
		const binaryPath = options.binaryPath ?? 'the bundled observer binary';
		return {
			hint: getObserverStartupHint('not-executable'),
			kind: 'not-executable',
			message: `${binaryPath} is not executable (${errorMessage}). Reinstall the extension or restore execute permissions.`,
		};
	}

	return {
		hint: getObserverStartupHint('generic'),
		kind: 'generic',
		message: errorMessage,
	};
}
