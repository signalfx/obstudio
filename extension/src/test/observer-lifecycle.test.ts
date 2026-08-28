import * as assert from 'node:assert/strict';
import test from 'node:test';
import {
	AsyncOperationQueue,
	AsyncSingleFlight,
	assertObserverRunCurrent,
	beginObserverStart,
	completeObserverStart,
	createObserverLifecycleState,
	finishObserverRun,
	isObserverLifecycleCancelled,
	operationCompletesWithin,
	stopObserverRun,
} from '../observer-lifecycle';

test('operation queue commits a cloud mutation before a queued lifecycle transition', async () => {
	const queue = new AsyncOperationQueue();
	const events: string[] = [];
	let releaseConfiguration: (() => void) | undefined;
	const configurationBlocked = new Promise<void>((resolve) => {
		releaseConfiguration = resolve;
	});

	const mutation = queue.run(async () => {
		events.push('configure-observer');
		await configurationBlocked;
		events.push('store-secret');
	});
	await Promise.resolve();
	const lifecycle = queue.run(async () => {
		events.push('stop-observer');
	});
	await Promise.resolve();

	assert.deepEqual(events, ['configure-observer']);
	releaseConfiguration?.();
	await Promise.all([mutation, lifecycle]);
	assert.deepEqual(events, ['configure-observer', 'store-secret', 'stop-observer']);

	await assert.rejects(
		queue.run(async () => { throw new Error('mutation failed'); }),
		/mutation failed/,
	);
	await queue.run(async () => {
		events.push('restart-observer');
	});
	assert.equal(events.at(-1), 'restart-observer');
});

test('operation deadline bounds extension unload without cancelling normal queue work', async () => {
	assert.equal(await operationCompletesWithin(Promise.resolve(), 50), true);

	let release: (() => void) | undefined;
	const blocked = new Promise<void>((resolve) => {
		release = resolve;
	});
	assert.equal(await operationCompletesWithin(blocked, 10), false);
	release?.();
	await blocked;

	await assert.rejects(
		operationCompletesWithin(Promise.reject(new Error('shutdown failed')), 50),
		/shutdown failed/,
	);
});

test('single-flight guard is visible before an asynchronous operation starts', async () => {
	const singleFlight = new AsyncSingleFlight();
	let release: (() => void) | undefined;
	const blocked = new Promise<void>((resolve) => {
		release = resolve;
	});
	let runs = 0;

	const first = singleFlight.run(async () => {
		runs += 1;
		await blocked;
	});
	const second = singleFlight.run(async () => {
		runs += 1;
	});

	assert.equal(first, second);
	assert.equal(singleFlight.current, first);
	await Promise.resolve();
	assert.equal(runs, 1);
	release?.();
	await Promise.all([first, second]);
	assert.equal(singleFlight.current, undefined);
});

test('stale startup completion after stop is ignored', () => {
	const state = createObserverLifecycleState();
	const runId = beginObserverStart(state);

	stopObserverRun(state);

	assert.equal(completeObserverStart(state, runId, 4318), false);
	assert.equal(state.status, 'stopped');
	assert.equal(state.port, undefined);
	assert.equal(state.startupError, undefined);
});

test('stale startup completion does not clobber a newer run', () => {
	const state = createObserverLifecycleState();
	const firstRun = beginObserverStart(state);

	stopObserverRun(state);
	const secondRun = beginObserverStart(state);

	assert.equal(completeObserverStart(state, firstRun, 3100), false);
	assert.equal(completeObserverStart(state, secondRun, 3200), true);
	assert.equal(state.status, 'running');
	assert.equal(state.port, 3200);
});

test('stale exit from an older run does not stop the current observer', () => {
	const state = createObserverLifecycleState();
	const firstRun = beginObserverStart(state);

	assert.equal(completeObserverStart(state, firstRun, 3100), true);

	stopObserverRun(state);
	const secondRun = beginObserverStart(state);

	assert.equal(completeObserverStart(state, secondRun, 3200), true);
	assert.equal(finishObserverRun(state, firstRun), false);
	assert.equal(state.status, 'running');
	assert.equal(state.port, 3200);
});

test('stopped startup attempts fail with a cancellation error', () => {
	const state = createObserverLifecycleState();
	const runId = beginObserverStart(state);

	stopObserverRun(state);

	assert.throws(
		() => assertObserverRunCurrent(state, runId),
		(error: unknown) => isObserverLifecycleCancelled(error),
	);
});
