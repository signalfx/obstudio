export type ObserverLifecycleStatus = 'starting' | 'running' | 'stopped' | 'error';

export interface ObserverLifecycleState {
	activeRunId: number | undefined;
	currentRunId: number;
	port: number | undefined;
	startupError: string | undefined;
	status: ObserverLifecycleStatus;
}

export class ObserverLifecycleCancelledError extends Error {
	constructor() {
		super('Observer lifecycle changed while startup was in progress.');
		this.name = 'ObserverLifecycleCancelledError';
	}
}

export function createObserverLifecycleState(): ObserverLifecycleState {
	return {
		activeRunId: undefined,
		currentRunId: 0,
		port: undefined,
		startupError: undefined,
		status: 'stopped',
	};
}

export function beginObserverStart(state: ObserverLifecycleState): number {
	const runId = state.currentRunId + 1;

	state.activeRunId = runId;
	state.currentRunId = runId;
	state.port = undefined;
	state.startupError = undefined;
	state.status = 'starting';

	return runId;
}

export function stopObserverRun(state: ObserverLifecycleState): void {
	state.activeRunId = undefined;
	state.currentRunId += 1;
	state.port = undefined;
	state.startupError = undefined;
	state.status = 'stopped';
}

export function isObserverRunCurrent(state: ObserverLifecycleState, runId: number): boolean {
	return state.activeRunId === runId;
}

export function assertObserverRunCurrent(state: ObserverLifecycleState, runId: number): void {
	if (!isObserverRunCurrent(state, runId)) {
		throw new ObserverLifecycleCancelledError();
	}
}

export function completeObserverStart(
	state: ObserverLifecycleState,
	runId: number,
	port: number,
): boolean {
	if (!isObserverRunCurrent(state, runId)) {
		return false;
	}

	state.port = port;
	state.startupError = undefined;
	state.status = 'running';

	return true;
}

export function failObserverStart(
	state: ObserverLifecycleState,
	runId: number,
	errorMessage: string,
): boolean {
	if (!isObserverRunCurrent(state, runId)) {
		return false;
	}

	state.activeRunId = undefined;
	state.port = undefined;
	state.startupError = errorMessage;
	state.status = 'error';

	return true;
}

export function finishObserverRun(state: ObserverLifecycleState, runId: number): boolean {
	if (!isObserverRunCurrent(state, runId)) {
		return false;
	}

	state.activeRunId = undefined;
	state.port = undefined;
	state.startupError = undefined;
	state.status = 'stopped';

	return true;
}

export function isObserverLifecycleCancelled(error: unknown): boolean {
	return error instanceof ObserverLifecycleCancelledError;
}
