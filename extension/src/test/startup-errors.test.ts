import * as assert from 'node:assert/strict';
import test from 'node:test';
import {
	currentVsCodeTarget,
	describeObserverStartupFailure,
	getObserverProbeMismatchHint,
	getObserverProbeUnavailableHint,
	formatObserverProbeMismatchMessage,
	formatObserverProbeUnavailableMessage,
	formatPortConflictMessage,
	getObserverStartupHint,
} from '../startup-errors';

test('currentVsCodeTarget maps supported runtime pairs to VS Code targets', () => {
	assert.equal(currentVsCodeTarget('darwin', 'arm64'), 'darwin-arm64');
	assert.equal(currentVsCodeTarget('darwin', 'x64'), 'darwin-x64');
	assert.equal(currentVsCodeTarget('linux', 'x64'), 'linux-x64');
	assert.equal(currentVsCodeTarget('win32', 'x64'), 'win32-x64');
});

test('formatPortConflictMessage names the managed UI setting for configurable ports', () => {
	assert.equal(
		formatPortConflictMessage({
			owner: 'nginx (PID 42)',
			port: 3000,
			role: 'Observer UI',
			settingName: 'managedObserverPort',
		}),
		'Observer UI port 3000 is already in use by "nginx (PID 42)". Stop the other process or change observability-studio.managedObserverPort.',
	);
});

test('formatPortConflictMessage explains stale observer ownership for fixed OTLP ports', () => {
	assert.equal(
		formatPortConflictMessage({
			owner: 'obstudio (PID 99)',
			port: 4318,
			role: 'OTLP/HTTP',
		}),
		'OTLP/HTTP port 4318 is already in use by "obstudio (PID 99)". Another Splunk Observability Studio instance or a stale observer process may still be running. Close the other VS Code window or terminate the stale observer process before restarting Splunk Observability Studio.',
	);
});

test('formatObserverProbeMismatchMessage hides internal health endpoint details', () => {
	assert.equal(
		formatObserverProbeMismatchMessage('http://127.0.0.1:63575', 'managed-reuse'),
		'the service already using http://127.0.0.1:63575 is not Splunk Observability Studio.',
	);
	assert.equal(
		formatObserverProbeMismatchMessage('http://127.0.0.1:63575', 'shared-reuse'),
		'the configured shared observer at http://127.0.0.1:63575 did not respond like Splunk Observability Studio. Verify observability-studio.sharedObserverUrl.',
	);
	assert.equal(
		formatObserverProbeMismatchMessage('http://127.0.0.1:63575', 'startup-reuse'),
		'a different service responded at http://127.0.0.1:63575 while Splunk Observability Studio was starting.',
	);
	assert.match(
		getObserverProbeMismatchHint('managed-reuse'),
		/freeing the conflicting port/i,
	);
	assert.match(
		getObserverProbeMismatchHint('startup-reuse'),
		/freeing the conflicting port/i,
	);
	assert.match(
		getObserverProbeMismatchHint('shared-reuse'),
		/observability-studio\.sharedObserverUrl/i,
	);
});

test('formatObserverProbeUnavailableMessage hides raw probe transport details', () => {
	assert.equal(
		formatObserverProbeUnavailableMessage('http://127.0.0.1:63575', 'shared-reuse'),
		'could not reach the configured shared observer at http://127.0.0.1:63575. Verify observability-studio.sharedObserverUrl and make sure Splunk Observability Studio is running there.',
	);
	assert.equal(
		formatObserverProbeUnavailableMessage('http://127.0.0.1:63575', 'startup'),
		'Splunk Observability Studio did not become ready at http://127.0.0.1:63575.',
	);
	assert.match(
		getObserverProbeUnavailableHint('shared-reuse'),
		/observability-studio\.sharedObserverUrl/i,
	);
	assert.match(
		getObserverProbeUnavailableHint('startup'),
		/output log/i,
	);
});

test('describeObserverStartupFailure explains wrong-platform ENOEXEC failures', () => {
	const failure = describeObserverStartupFailure(
		Object.assign(new Error('spawn ENOEXEC'), { code: 'ENOEXEC' }),
		{
			arch: 'arm64',
			binaryPath: '/tmp/obstudio',
			platform: 'darwin',
		},
	);

	assert.equal(failure.kind, 'wrong-platform');
	assert.match(failure.message, /\/tmp\/obstudio cannot run on darwin-arm64/);
	assert.match(failure.message, /different operating system or CPU architecture/);
	assert.match(failure.message, /observability-studio\.sharedObserverUrl/);
	assert.match(failure.hint, /platform-specific extension package/i);
});

test('describeObserverStartupFailure explains permission failures', () => {
	const failure = describeObserverStartupFailure(
		Object.assign(new Error('spawn EACCES'), { code: 'EACCES' }),
		{ binaryPath: '/tmp/obstudio' },
	);

	assert.equal(
		failure.message,
		'/tmp/obstudio is not executable (spawn EACCES). Reinstall the extension or restore execute permissions.',
	);
	assert.equal(failure.kind, 'not-executable');
});

test('getObserverStartupHint returns guidance by failure kind', () => {
	assert.match(
		getObserverStartupHint('port-conflict'),
		/freeing the conflicting port/i,
	);
	assert.match(
		getObserverStartupHint('wrong-platform'),
		/platform-specific extension package/i,
	);
	assert.match(
		getObserverStartupHint('not-executable'),
		/restore execute permissions/i,
	);
	assert.match(getObserverStartupHint('generic'), /output log/i);
});
