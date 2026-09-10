import * as cp from 'node:child_process';
import * as fs from 'node:fs';
import * as path from 'node:path';

export type ForceTerminationPlan =
	| { kind: 'signal'; signal: 'SIGKILL' }
	| { args: string[]; command: string; kind: 'command' };

export type GracefulTerminationPlan =
	| { kind: 'signal'; signal: 'SIGTERM' }
	| { args: string[]; command: string; kind: 'command' };

export type ProcessInspectionPlan = {
	args: string[];
	command: string;
};

export type ListeningProcessInspectionPlan = {
	args: string[];
	command: string;
};

export type ListeningProcess = {
	executablePath?: string;
	pid: number;
};

export function listeningProcessInspectionPlan(
	port: number,
	platform: NodeJS.Platform = process.platform,
): ListeningProcessInspectionPlan {
	if (!Number.isSafeInteger(port) || port <= 0 || port > 65_535) {
		throw new Error(`Cannot inspect invalid port ${port}.`);
	}
	if (platform === 'win32') {
		return {
			command: windowsSystemTool('WindowsPowerShell', 'v1.0', 'powershell.exe'),
			args: [
				'-NoProfile',
				'-NonInteractive',
				'-Command',
				`Get-NetTCPConnection -State Listen -LocalPort ${port} -ErrorAction SilentlyContinue `
					+ '| Select-Object -ExpandProperty OwningProcess -Unique '
					+ '| ForEach-Object { [Console]::Out.WriteLine($_) }',
			],
		};
	}
	if (platform === 'darwin' || platform === 'linux') {
		return {
			command: platform === 'darwin' ? '/usr/sbin/lsof' : '/usr/bin/lsof',
			args: ['-nP', '-a', `-iTCP:${port}`, '-sTCP:LISTEN', '-Fp'],
		};
	}
	throw new Error(`Cannot inspect listening processes on unsupported platform ${platform}.`);
}

export function parseListeningProcessIds(output: string): number[] {
	const processIds = new Set<number>();
	for (const rawLine of output.split(/\r?\n/)) {
		const match = /^(?:p)?([0-9]+)$/.exec(rawLine.trim());
		if (match === null) {
			continue;
		}
		const pid = Number(match[1]);
		if (Number.isSafeInteger(pid) && pid > 0) {
			processIds.add(pid);
		}
	}
	return [...processIds];
}

export function isObserverExecutablePath(
	executablePath: string,
	platform: NodeJS.Platform = process.platform,
): boolean {
	const expectedName = platform === 'win32' ? 'obstudio.exe' : 'obstudio';
	const basename = platform === 'win32' ? path.win32.basename(executablePath) : path.basename(executablePath);
	return platform === 'win32' ? basename.toLowerCase() === expectedName : basename === expectedName;
}

export function processExecutablePathsEqual(
	firstPath: string,
	secondPath: string,
	platform: NodeJS.Platform = process.platform,
): boolean {
	const normalize = (value: string) => {
		const resolved = platform === 'win32' ? path.win32.normalize(value) : path.resolve(value);
		return platform === 'win32' ? resolved.toLowerCase() : resolved;
	};
	return normalize(firstPath) === normalize(secondPath);
}

export async function readListeningProcess(port: number): Promise<ListeningProcess | undefined> {
	let plan: ListeningProcessInspectionPlan;
	try {
		plan = listeningProcessInspectionPlan(port);
	} catch {
		return undefined;
	}
	const processIds = await new Promise<number[]>((resolve) => {
		try {
			cp.execFile(plan.command, plan.args, {
				encoding: 'utf8',
				maxBuffer: 64 * 1024,
				timeout: 10_000,
				windowsHide: true,
			}, (error, stdout) => {
				if (error !== null) {
					resolve([]);
					return;
				}
				resolve(parseListeningProcessIds(stdout));
			});
		} catch {
			resolve([]);
		}
	});
	if (processIds.length !== 1) {
		return undefined;
	}
	const pid = processIds[0];
	return {
		executablePath: await readProcessExecutablePath(pid),
		pid,
	};
}

export function processInspectionPlan(
	pid: number,
	platform: NodeJS.Platform = process.platform,
): ProcessInspectionPlan {
	if (!Number.isSafeInteger(pid) || pid <= 0) {
		throw new Error(`Cannot inspect invalid process ID ${pid}.`);
	}
	if (platform === 'win32') {
		return {
			command: windowsSystemTool('WindowsPowerShell', 'v1.0', 'powershell.exe'),
			args: [
				'-NoProfile',
				'-NonInteractive',
				'-Command',
				`$p = Get-Process -Id ${pid} -ErrorAction SilentlyContinue; if ($null -ne $p -and $null -ne $p.Path) { [Console]::Out.Write($p.Path) }`,
			],
		};
	}
	return {
		command: '/bin/ps',
		args: ['-p', String(pid), '-o', 'comm='],
	};
}

export async function readProcessExecutablePath(pid: number): Promise<string | undefined> {
	if (!Number.isSafeInteger(pid) || pid <= 0) {
		return undefined;
	}
	if (process.platform === 'linux') {
		try {
			return normalizeLinuxExecutableLink(fs.readlinkSync(`/proc/${pid}/exe`));
		} catch {}
	}
	const plan = processInspectionPlan(pid);
	return new Promise((resolve) => {
		try {
			cp.execFile(plan.command, plan.args, {
				encoding: 'utf8',
				maxBuffer: 64 * 1024,
				timeout: 10_000,
				windowsHide: true,
			}, (error, stdout) => {
				if (error !== null) {
					resolve(undefined);
					return;
				}
				resolve(stdout.trim() || undefined);
			});
		} catch {
			resolve(undefined);
		}
	});
}

export function normalizeLinuxExecutableLink(value: string): string | undefined {
	const executablePath = value.trim();
	if (executablePath === '' || executablePath.endsWith(' (deleted)')) {
		return undefined;
	}
	return executablePath;
}

export function processIsRunning(pid: number): boolean {
	if (!Number.isSafeInteger(pid) || pid <= 0) {
		return false;
	}
	try {
		process.kill(pid, 0);
		return true;
	} catch (error) {
		return (error as NodeJS.ErrnoException).code !== 'ESRCH';
	}
}

export function forceTerminationPlan(
	pid: number,
	platform: NodeJS.Platform = process.platform,
): ForceTerminationPlan {
	if (!Number.isSafeInteger(pid) || pid <= 0) {
		throw new Error(`Cannot terminate invalid process ID ${pid}.`);
	}
	if (platform === 'win32') {
		return {
			args: ['/PID', String(pid), '/T', '/F'],
			command: windowsSystemTool('taskkill.exe'),
			kind: 'command',
		};
	}
	return { kind: 'signal', signal: 'SIGKILL' };
}

export function gracefulTerminationPlan(
	pid: number,
	platform: NodeJS.Platform = process.platform,
): GracefulTerminationPlan {
	if (!Number.isSafeInteger(pid) || pid <= 0) {
		throw new Error(`Cannot terminate invalid process ID ${pid}.`);
	}
	if (platform === 'win32') {
		return {
			args: ['/PID', String(pid), '/T'],
			command: windowsSystemTool('taskkill.exe'),
			kind: 'command',
		};
	}
	return { kind: 'signal', signal: 'SIGTERM' };
}

function windowsSystemTool(...segments: string[]): string {
	const windowsDirectory = process.env.SystemRoot?.trim()
		|| process.env.WINDIR?.trim()
		|| 'C:\\Windows';
	if (!path.win32.isAbsolute(windowsDirectory)) {
		throw new Error('Windows system directory is not absolute.');
	}
	return path.win32.join(windowsDirectory, 'System32', ...segments);
}

export async function forceTerminateProcess(pid: number): Promise<void> {
	await executeTerminationPlan(pid, forceTerminationPlan(pid));
}

export async function gracefullyTerminateProcess(pid: number): Promise<void> {
	await executeTerminationPlan(pid, gracefulTerminationPlan(pid));
}

async function executeTerminationPlan(
	pid: number,
	plan: ForceTerminationPlan | GracefulTerminationPlan,
): Promise<void> {
	if (plan.kind === 'signal') {
		process.kill(pid, plan.signal);
		return;
	}

	await new Promise<void>((resolve, reject) => {
		cp.execFile(
			plan.command,
			plan.args,
			{ timeout: 5_000, windowsHide: true },
			(error) => {
				if (error !== null) {
					reject(error);
					return;
				}
				resolve();
			},
		);
	});
}
