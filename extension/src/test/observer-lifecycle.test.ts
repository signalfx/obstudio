import * as assert from 'node:assert/strict';
import test from 'node:test';
import {
	assertObserverRunCurrent,
	beginObserverStart,
	completeObserverStart,
	createObserverLifecycleState,
	finishObserverRun,
	isObserverLifecycleCancelled,
	stopObserverRun,
} from '../observer-lifecycle';

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
