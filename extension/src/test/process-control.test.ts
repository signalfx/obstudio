import * as assert from 'node:assert/strict';
import * as cp from 'node:child_process';
import { once } from 'node:events';
import * as fs from 'node:fs';
import * as os from 'node:os';
import * as path from 'node:path';
import test from 'node:test';
import {
	findOtherExtensionManagedObserver,
	findOtherExtensionObserverExecutable,
	readSharedObserverDiscovery,
} from '../backend';
import {
	forceTerminateProcess,
	forceTerminationPlan,
	normalizeLinuxExecutableLink,
	processInspectionPlan,
	processIsRunning,
	readProcessExecutablePath,
} from '../process-control';

test('deleted Linux executables are never trusted for PID termination', () => {
	assert.equal(normalizeLinuxExecutableLink('/opt/obstudio/obstudio (deleted)'), undefined);
	assert.equal(normalizeLinuxExecutableLink('   '), undefined);
	assert.equal(normalizeLinuxExecutableLink(' /opt/obstudio/obstudio '), '/opt/obstudio/obstudio');
});

test('force termination uses SIGKILL on supported Unix platforms', () => {
	for (const platform of ['darwin', 'linux'] as const) {
		assert.deepEqual(forceTerminationPlan(4321, platform), {
			kind: 'signal',
			signal: 'SIGKILL',
		});
	}
});

test('force termination uses taskkill for the supported Windows platform', () => {
	assert.deepEqual(forceTerminationPlan(4321, 'win32'), {
		args: ['/PID', '4321', '/T', '/F'],
		command: 'C:\\Windows\\System32\\taskkill.exe',
		kind: 'command',
	});
});

test('force termination rejects invalid process IDs', () => {
	for (const pid of [Number.NaN, 0, -1, 1.5]) {
		assert.throws(() => forceTerminationPlan(pid, process.platform), /invalid process ID/);
	}
});

test('PID inspection uses native commands on every supported platform', () => {
	assert.deepEqual(processInspectionPlan(4321, 'darwin'), {
		args: ['-p', '4321', '-o', 'comm='],
		command: '/bin/ps',
	});
	assert.deepEqual(processInspectionPlan(4321, 'linux'), {
		args: ['-p', '4321', '-o', 'comm='],
		command: '/bin/ps',
	});
	const windowsPlan = processInspectionPlan(4321, 'win32');
	assert.equal(
		windowsPlan.command,
		'C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe',
	);
	assert.deepEqual(windowsPlan.args.slice(0, 3), ['-NoProfile', '-NonInteractive', '-Command']);
	assert.match(windowsPlan.args[3], /Get-Process -Id 4321/);
	assert.match(windowsPlan.args[3], /\.Path/);
});

test('shared Observer state exposes a credential-free PID on the current platform', () => {
	const homeDir = fs.mkdtempSync(path.join(os.tmpdir(), 'obstudio-pid-state-'));
	try {
		const stateDirectory = path.join(homeDir, '.obstudio');
		const statePath = path.join(stateDirectory, 'shared-observer.json');
		fs.mkdirSync(stateDirectory, { recursive: true, mode: 0o700 });
		fs.writeFileSync(statePath, JSON.stringify({
			baseUrl: 'http://127.0.0.1:39871',
			healthUrl: 'http://127.0.0.1:39871/api/health',
			mcpUrl: 'http://127.0.0.1:39871/mcp',
			pid: 4321,
		}), { mode: 0o600 });
		if (process.platform !== 'win32') {
			fs.chmodSync(stateDirectory, 0o700);
			fs.chmodSync(statePath, 0o600);
		}
		assert.deepEqual(readSharedObserverDiscovery(homeDir), {
			baseUrl: 'http://127.0.0.1:39871',
			healthUrl: 'http://127.0.0.1:39871/api/health',
			mcpUrl: 'http://127.0.0.1:39871/mcp',
			pid: 4321,
		});
	} finally {
		fs.rmSync(homeDir, { force: true, recursive: true });
	}
});

test('the recorded PID is accepted only for its exact installed-extension binary', () => {
	const root = fs.mkdtempSync(path.join(os.tmpdir(), 'obstudio-pid-owner-'));
	try {
		const currentExtensionPath = path.join(root, 'splunk.observability-studio-current');
		const previousExtensionPath = path.join(root, 'splunk.observability-studio-previous');
		const binaryPath = path.join(
			previousExtensionPath,
			'dist',
			'observer',
			process.platform === 'win32' ? 'obstudio.exe' : 'obstudio',
		);
		fs.mkdirSync(currentExtensionPath, { recursive: true });
		fs.mkdirSync(path.dirname(binaryPath), { recursive: true });
		fs.writeFileSync(path.join(previousExtensionPath, 'package.json'), JSON.stringify({
			name: 'observability-studio',
			publisher: 'Splunk',
			version: 'previous',
		}));
		fs.writeFileSync(binaryPath, 'fixture');
		const processExecutablePath = process.platform === 'win32' ? binaryPath.toUpperCase() : binaryPath;
		assert.deepEqual(findOtherExtensionManagedObserver({
			currentExtensionPath,
			discovery: { baseUrl: 'http://127.0.0.1:39871', pid: 4321 },
			processExecutablePath,
		}), {
			binaryPath,
			pid: 4321,
			version: 'previous',
		});
		assert.equal(findOtherExtensionManagedObserver({
			currentExtensionPath,
			discovery: { baseUrl: 'http://127.0.0.1:39871', pid: 4321 },
			processExecutablePath: path.join(root, process.platform === 'win32' ? 'obstudio.exe' : 'obstudio'),
		}), undefined);
	} finally {
		fs.rmSync(root, { force: true, recursive: true });
	}
});

test('a missing previous extension package is recognized but is not trusted for termination', () => {
	const root = fs.mkdtempSync(path.join(os.tmpdir(), 'obstudio-stale-pid-owner-'));
	try {
		const currentExtensionPath = path.join(root, 'splunk.observability-studio-current');
		const previousExtensionPath = path.join(root, 'splunk.observability-studio-previous');
		const binaryPath = path.join(
			previousExtensionPath,
			'dist',
			'observer',
			process.platform === 'win32' ? 'obstudio.exe' : 'obstudio',
		);
		const processExecutablePath = process.platform === 'win32' ? binaryPath.toUpperCase() : binaryPath;
		assert.deepEqual(findOtherExtensionObserverExecutable({
			currentExtensionPath,
			discovery: { baseUrl: 'http://127.0.0.1:39871', pid: 4321 },
			processExecutablePath,
		}), {
			binaryPath: process.platform === 'win32' ? binaryPath.toUpperCase() : binaryPath,
			pid: 4321,
		});
		assert.equal(findOtherExtensionObserverExecutable({
			currentExtensionPath,
			discovery: { baseUrl: 'http://127.0.0.1:39871', pid: 4321 },
			processExecutablePath: path.join(currentExtensionPath, 'dist', 'observer', path.basename(binaryPath)),
		}), undefined);
		assert.equal(findOtherExtensionObserverExecutable({
			currentExtensionPath,
			discovery: { baseUrl: 'http://127.0.0.1:39871', pid: 4321 },
			processExecutablePath: path.join(root, 'other-extension', 'dist', 'observer', path.basename(binaryPath)),
		}), undefined);
	} finally {
		fs.rmSync(root, { force: true, recursive: true });
	}
});

test('force termination stops a real process on the current platform', { timeout: 10_000 }, async () => {
	const child = cp.spawn(process.execPath, ['-e', 'setInterval(() => {}, 1000)'], {
		stdio: 'ignore',
		windowsHide: true,
	});
	await once(child, 'spawn');
	assert.ok(child.pid !== undefined);

	try {
		assert.equal(processIsRunning(child.pid), true);
		const executablePath = await readProcessExecutablePath(child.pid);
		assert.ok(executablePath !== undefined);
		const normalizePath = (value: string) => process.platform === 'win32'
			? path.resolve(value).toLowerCase()
			: path.resolve(value);
		assert.equal(normalizePath(executablePath), normalizePath(fs.realpathSync(process.execPath)));
		await forceTerminateProcess(child.pid);
		const [exitCode, signal] = await once(child, 'exit') as [number | null, NodeJS.Signals | null];
		assert.equal(exitCode === null || exitCode !== 0, true);
		if (process.platform !== 'win32') {
			assert.equal(signal, 'SIGKILL');
		}
		assert.equal(processIsRunning(child.pid), false);
	} finally {
		if (child.exitCode === null && child.signalCode === null) {
			child.kill('SIGKILL');
		}
	}
});
