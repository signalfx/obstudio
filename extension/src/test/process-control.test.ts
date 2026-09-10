import * as assert from 'node:assert/strict';
import * as cp from 'node:child_process';
import { once } from 'node:events';
import * as fs from 'node:fs';
import * as net from 'node:net';
import * as os from 'node:os';
import * as path from 'node:path';
import test from 'node:test';
import { readSharedObserverDiscovery } from '../backend';
import {
	forceTerminateProcess,
	forceTerminationPlan,
	gracefulTerminationPlan,
	inspectListeningProcess,
	isObserverExecutablePath,
	listeningProcessInspectionPlan,
	normalizeLinuxExecutableLink,
	parseListeningProcessIds,
	processExecutablePathsEqual,
	processInspectionPlan,
	processIsRunning,
	readListeningProcess,
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

test('graceful termination uses SIGTERM on supported Unix platforms', () => {
	for (const platform of ['darwin', 'linux'] as const) {
		assert.deepEqual(gracefulTerminationPlan(4321, platform), {
			kind: 'signal',
			signal: 'SIGTERM',
		});
	}
});

test('graceful termination uses taskkill without force on the supported Windows platform', () => {
	const plan = gracefulTerminationPlan(4321, 'win32');
	assert.deepEqual(plan, {
		args: ['/PID', '4321', '/T'],
		command: 'C:\\Windows\\System32\\taskkill.exe',
		kind: 'command',
	});
	assert.equal(plan.args.includes('/F'), false);
});

test('termination plans reject invalid process IDs', () => {
	for (const pid of [Number.NaN, 0, -1, 1.5]) {
		assert.throws(() => forceTerminationPlan(pid, process.platform), /invalid process ID/);
		assert.throws(() => gracefulTerminationPlan(pid, process.platform), /invalid process ID/);
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

test('listener PID inspection uses native commands on every supported platform', () => {
	assert.deepEqual(listeningProcessInspectionPlan(39871, 'darwin'), {
		args: ['-nP', '-a', '-iTCP@127.0.0.1:39871', '-sTCP:LISTEN', '-Fp'],
		command: '/usr/sbin/lsof',
	});
	assert.deepEqual(listeningProcessInspectionPlan(39871, 'linux'), {
		args: ['-nP', '-a', '-iTCP@127.0.0.1:39871', '-sTCP:LISTEN', '-Fp'],
		command: '/usr/bin/lsof',
	});
	const windowsPlan = listeningProcessInspectionPlan(39871, 'win32');
	assert.equal(
		windowsPlan.command,
		'C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe',
	);
	assert.deepEqual(windowsPlan.args.slice(0, 3), ['-NoProfile', '-NonInteractive', '-Command']);
	assert.match(
		windowsPlan.args[3],
		/Get-NetTCPConnection -ErrorAction Stop/,
	);
	assert.match(windowsPlan.args[3], /\.State -eq 'Listen'/);
	assert.match(windowsPlan.args[3], /\.LocalAddress -eq '127\.0\.0\.1'/);
	assert.match(windowsPlan.args[3], /\.LocalPort -eq 39871/);
	assert.match(windowsPlan.args[3], /OwningProcess/);
});

test('listener PID inspection validates ports and accepts lsof or PowerShell output', () => {
	for (const port of [Number.NaN, 0, -1, 65_536, 1.5]) {
		assert.throws(() => listeningProcessInspectionPlan(port, process.platform), /invalid port/);
	}
	assert.deepEqual(parseListeningProcessIds('p4321\ncobstudio\np4321\n'), [4321]);
	assert.deepEqual(parseListeningProcessIds('4321\r\n5678\r\n'), [4321, 5678]);
	assert.deepEqual(parseListeningProcessIds('warning\np0\n'), []);
});

test('Observer executable matching is exact and platform-aware', () => {
	assert.equal(isObserverExecutablePath('/opt/obstudio', 'darwin'), true);
	assert.equal(isObserverExecutablePath('/opt/OBSTUDIO', 'darwin'), false);
	assert.equal(isObserverExecutablePath('/opt/obstudio-helper', 'linux'), false);
	assert.equal(isObserverExecutablePath('C:\\Tools\\obstudio.exe', 'win32'), true);
	assert.equal(isObserverExecutablePath('C:\\Tools\\OBSTUDIO.EXE', 'win32'), true);
	assert.equal(isObserverExecutablePath('C:\\Tools\\obstudio.cmd', 'win32'), false);
});

test('process executable path comparison follows platform path semantics', () => {
	assert.equal(processExecutablePathsEqual('/opt/obstudio', '/opt/obstudio', 'linux'), true);
	assert.equal(processExecutablePathsEqual('/opt/obstudio', '/opt/OBSTUDIO', 'linux'), false);
	assert.equal(
		processExecutablePathsEqual('C:\\Tools\\obstudio.exe', 'c:\\tools\\OBSTUDIO.EXE', 'win32'),
		true,
	);
	assert.equal(
		processExecutablePathsEqual('C:\\Tools\\obstudio.exe', 'C:\\Other\\obstudio.exe', 'win32'),
		false,
	);
});

test('listener PID inspection resolves a real loopback listener', { timeout: 10_000 }, async () => {
	const server = net.createServer();
	await new Promise<void>((resolve, reject) => {
		server.once('error', reject);
		server.listen(0, '127.0.0.1', resolve);
	});
	try {
		const address = server.address();
		assert.ok(address !== null && typeof address !== 'string');
		const listener = await readListeningProcess(address.port);
		assert.ok(listener !== undefined);
		assert.equal(listener.pid, process.pid);
		assert.ok(listener.executablePath !== undefined);
		const normalizePath = (value: string) => process.platform === 'win32'
			? path.resolve(value).toLowerCase()
			: path.resolve(value);
		assert.equal(normalizePath(listener.executablePath), normalizePath(fs.realpathSync(process.execPath)));
	} finally {
		await new Promise<void>((resolve, reject) => {
			server.close((error) => error === undefined ? resolve() : reject(error));
		});
	}
});

test('listener inspection distinguishes an unused loopback port from an unavailable inspection', { timeout: 10_000 }, async () => {
	const reservation = net.createServer();
	await new Promise<void>((resolve, reject) => {
		reservation.once('error', reject);
		reservation.listen(0, '127.0.0.1', resolve);
	});
	const address = reservation.address();
	assert.ok(address !== null && typeof address !== 'string');
	await new Promise<void>((resolve, reject) => {
		reservation.close((error) => error === undefined ? resolve() : reject(error));
	});
	assert.deepEqual(await inspectListeningProcess(address.port), { status: 'none' });
});

test('listener PID inspection ignores another process using the same port on IPv6', { timeout: 10_000 }, async (t) => {
	const ipv4Server = net.createServer();
	await new Promise<void>((resolve, reject) => {
		ipv4Server.once('error', reject);
		ipv4Server.listen(0, '127.0.0.1', resolve);
	});
	const address = ipv4Server.address();
	assert.ok(address !== null && typeof address !== 'string');
	const ipv6Child = cp.spawn(process.execPath, [
		'-e',
		`require('node:net').createServer().listen(${address.port}, '::1', () => process.stdout.write('ready\\n'))`,
	], {
		stdio: ['ignore', 'pipe', 'pipe'],
		windowsHide: true,
	});
	let childReady = false;
	try {
		const outcome = await Promise.race([
			once(ipv6Child.stdout!, 'data').then(() => 'ready' as const),
			once(ipv6Child, 'exit').then(() => 'exit' as const),
		]);
		if (outcome === 'exit') {
			t.skip('IPv6 loopback listeners are unavailable on this host');
			return;
		}
		childReady = true;
		const listener = await readListeningProcess(address.port);
		assert.ok(listener !== undefined);
		assert.equal(listener.pid, process.pid);
	} finally {
		await new Promise<void>((resolve, reject) => {
			ipv4Server.close((error) => error === undefined ? resolve() : reject(error));
		});
		if (childReady && ipv6Child.exitCode === null && ipv6Child.signalCode === null) {
			const exited = once(ipv6Child, 'exit');
			ipv6Child.kill('SIGKILL');
			await exited;
		}
	}
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
		const exitPromise = once(child, 'exit') as Promise<[number | null, NodeJS.Signals | null]>;
		await forceTerminateProcess(child.pid);
		const [exitCode, signal] = await exitPromise;
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
