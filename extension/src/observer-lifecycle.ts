export type ObserverLifecycleStatus = 'starting' | 'running' | 'stopped' | 'error';

export interface ObserverLifecycleState {
	activeRunId: number | undefined;
	currentRunId: number;
	port: number | undefined;
	startupError: string | undefined;
	startupHint: string | undefined;
	status: ObserverLifecycleStatus;
}

export class ObserverLifecycleCancelledError extends Error {
	constructor() {
		super('Observer lifecycle changed while startup was in progress.');
		this.name = 'ObserverLifecycleCancelledError';
	}
}

export class AsyncSingleFlight {
	private active: Promise<void> | undefined;

	get current(): Promise<void> | undefined {
		return this.active;
	}

	run(operation: () => Promise<void>): Promise<void> {
		if (this.active !== undefined) {
			return this.active;
		}

		const active = Promise.resolve()
			.then(operation)
			.finally(() => {
				if (this.active === active) {
					this.active = undefined;
				}
			});
		this.active = active;
		return active;
	}

	clear(): void {
		this.active = undefined;
	}
}

export class AsyncOperationQueue {
	private tail: Promise<void> = Promise.resolve();

	/** Run operations in invocation order without letting one rejection poison the queue. */
	run<T>(operation: () => Promise<T>): Promise<T> {
		const result = this.tail.then(operation);
		this.tail = result.then(
			() => undefined,
			() => undefined,
		);
		return result;
	}
}

export async function operationCompletesWithin(
	operation: Promise<void>,
	timeoutMs: number,
): Promise<boolean> {
	let timeout: NodeJS.Timeout | undefined;
	try {
		return await Promise.race([
			operation.then(() => true),
			new Promise<boolean>((resolve) => {
				timeout = setTimeout(() => resolve(false), timeoutMs);
			}),
		]);
	} finally {
		if (timeout !== undefined) {
			clearTimeout(timeout);
		}
	}
}

export function createObserverLifecycleState(): ObserverLifecycleState {
	return {
		activeRunId: undefined,
		currentRunId: 0,
		port: undefined,
		startupError: undefined,
		startupHint: undefined,
		status: 'stopped',
	};
}

export function beginObserverStart(state: ObserverLifecycleState): number {
	const runId = state.currentRunId + 1;

	state.activeRunId = runId;
	state.currentRunId = runId;
	state.port = undefined;
	state.startupError = undefined;
	state.startupHint = undefined;
	state.status = 'starting';

	return runId;
}

export function stopObserverRun(state: ObserverLifecycleState): void {
	state.activeRunId = undefined;
	state.currentRunId += 1;
	state.port = undefined;
	state.startupError = undefined;
	state.startupHint = undefined;
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
	state.startupHint = undefined;
	state.status = 'running';

	return true;
}

export function failObserverStart(
	state: ObserverLifecycleState,
	runId: number,
	errorMessage: string,
	startupHint?: string,
): boolean {
	if (!isObserverRunCurrent(state, runId)) {
		return false;
	}

	state.activeRunId = undefined;
	state.port = undefined;
	state.startupError = errorMessage;
	state.startupHint = startupHint;
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
	state.startupHint = undefined;
	state.status = 'stopped';

	return true;
}

export function isObserverLifecycleCancelled(error: unknown): boolean {
	return error instanceof ObserverLifecycleCancelledError;
}
