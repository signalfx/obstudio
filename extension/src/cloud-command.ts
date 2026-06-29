import * as cp from 'node:child_process';
import type { ObserverBackend } from './backend';
import type { O11yOAuthConnection } from './o11y-oauth';
import { parseO11yOAuthConnection } from './o11y-oauth';

const maxCommandOutputBytes = 64 * 1024;

export type CloudLoginCommandOptions = {
	clientId: string;
	issuerUrl: string;
	requiredScope: string;
	scope: string;
	timeoutMs?: number;
	tokenName: string;
};

type CommandResult = {
	stderr: string;
	stdout: string;
};

export function defaultCloudClientId(appName: string): string {
	return appName.toLowerCase().includes('cursor') ? 'obstudio-cursor' : 'obstudio-vscode';
}

export async function persistCloudConnectionOrRevoke(
	connection: O11yOAuthConnection,
	persist: () => Promise<void>,
	revoke: () => Promise<void>,
): Promise<void> {
	try {
		await persist();
	} catch (storageError) {
		try {
			await revoke();
		} catch (revocationError) {
			throw new Error(
				`IDE secure storage failed and the issued token could not be revoked: storage error: ${errorMessage(storageError)}; revocation error: ${errorMessage(revocationError)}`,
			);
		}
		throw new Error(`IDE secure storage failed; the issued token was revoked: ${errorMessage(storageError)}`);
	}
}

export async function runCloudLoginCommand(
	backend: ObserverBackend,
	options: CloudLoginCommandOptions,
): Promise<O11yOAuthConnection> {
	const timeoutMs = options.timeoutMs ?? 5 * 60 * 1000;
	const result = await runBackendCommand(
		backend,
		[
			'cloud',
			'login',
			'--issuer', options.issuerUrl,
			'--client-id', options.clientId,
			'--scope', options.scope,
			'--required-scope', options.requiredScope,
			'--token-name', options.tokenName,
			'--timeout', `${timeoutMs}ms`,
			'--no-store',
			'--output=json',
			'--show-token',
		],
		undefined,
		timeoutMs + 30_000,
	);
	return parseCloudConnectionOutput(result.stdout);
}

export async function runCloudRevokeCommand(
	backend: ObserverBackend,
	connection: O11yOAuthConnection,
): Promise<void> {
	await runBackendCommand(
		backend,
		['cloud', 'logout', '--connection-stdin', '--output=json'],
		JSON.stringify(connection),
		30_000,
	);
}

export function parseCloudConnectionOutput(raw: string): O11yOAuthConnection {
	let parsed: unknown;
	try {
		parsed = JSON.parse(raw);
	} catch {
		throw new Error('Bundled obstudio cloud login returned invalid JSON.');
	}
	const connection = parseO11yOAuthConnection(parsed);
	if (connection === undefined) {
		throw new Error('Bundled obstudio cloud login returned an invalid connection.');
	}
	return connection;
}

function runBackendCommand(
	backend: ObserverBackend,
	args: string[],
	input: string | undefined,
	timeoutMs: number,
): Promise<CommandResult> {
	return new Promise((resolve, reject) => {
		const child = cp.spawn(backend.command, [...backend.args, ...args], {
			cwd: backend.cwd,
			env: { ...process.env, ...backend.env },
			stdio: ['pipe', 'pipe', 'pipe'],
		});
		const stdout: Buffer[] = [];
		const stderr: Buffer[] = [];
		let stdoutBytes = 0;
		let stderrBytes = 0;
		let settled = false;
		let timer: ReturnType<typeof setTimeout> | undefined;

		const finish = (error?: Error, code?: number | null): void => {
			if (settled) {
				return;
			}
			settled = true;
			if (timer !== undefined) {
				clearTimeout(timer);
			}
			if (error !== undefined) {
				reject(error);
				return;
			}
			const stdoutText = Buffer.concat(stdout).toString('utf8');
			const stderrText = Buffer.concat(stderr).toString('utf8').trim();
			if (code !== 0) {
				reject(new Error(stderrText || `Bundled obstudio cloud command exited with code ${code ?? 'unknown'}.`));
				return;
			}
			resolve({ stderr: stderrText, stdout: stdoutText });
		};
		timer = setTimeout(() => {
			child.kill();
			finish(new Error('Bundled obstudio cloud command timed out.'));
		}, timeoutMs);

		child.stdout.on('data', (chunk: Buffer) => {
			stdoutBytes += chunk.byteLength;
			if (stdoutBytes > maxCommandOutputBytes) {
				child.kill();
				finish(new Error('Bundled obstudio cloud command returned too much output.'));
				return;
			}
			stdout.push(chunk);
		});
		child.stderr.on('data', (chunk: Buffer) => {
			stderrBytes += chunk.byteLength;
			if (stderrBytes > maxCommandOutputBytes) {
				child.kill();
				finish(new Error('Bundled obstudio cloud command returned too much error output.'));
				return;
			}
			stderr.push(chunk);
		});
		child.once('error', (error) => finish(error));
		child.once('close', (code) => finish(undefined, code));
		child.stdin.once('error', (error: NodeJS.ErrnoException) => {
			if (error.code !== 'EPIPE') {
				finish(error);
			}
		});
		if (input === undefined) {
			child.stdin.end();
		} else {
			child.stdin.end(input);
		}
	});
}

function errorMessage(error: unknown): string {
	return error instanceof Error ? error.message : String(error);
}
