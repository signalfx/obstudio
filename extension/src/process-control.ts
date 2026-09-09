import * as cp from 'node:child_process';
import * as fs from 'node:fs';
import * as path from 'node:path';

export type ForceTerminationPlan =
	| { kind: 'signal'; signal: 'SIGKILL' }
	| { args: string[]; command: string; kind: 'command' };

export type ProcessInspectionPlan = {
	args: string[];
	command: string;
};

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
	const plan = forceTerminationPlan(pid);
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
