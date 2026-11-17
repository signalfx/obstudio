import * as http from 'node:http';
import * as net from 'node:net';
import { performance } from 'node:perf_hooks';

export function uniqueLoopbackPorts(ports: readonly number[]): number[] {
	return [...new Set(ports)];
}

export class LoopbackPortReservations {
	private readonly reservations: Array<{ server: net.Server; sockets: Set<net.Socket> }> = [];

	async reserve(port: number, deadline: number): Promise<boolean> {
		const remainingMs = Math.max(0, deadline - performance.now());
		if (remainingMs <= 0) {
			return false;
		}
		const server = net.createServer();
		const sockets = new Set<net.Socket>();
		this.reservations.push({ server, sockets });
		server.on('connection', (socket) => {
			sockets.add(socket);
			socket.once('close', () => sockets.delete(socket));
			// Exporters commonly reconnect to a briefly available OTLP port. Do not
			// let an accepted probe-time connection keep server.close() pending.
			socket.destroy();
		});
		return new Promise<boolean>((resolve) => {
			let settled = false;
			const abortController = new AbortController();
			let timeout: NodeJS.Timeout | undefined;
			const finish = (value: boolean) => {
				if (settled) {
					return;
				}
				settled = true;
				if (timeout !== undefined) {
					clearTimeout(timeout);
				}
				if (!value) {
					abortController.abort();
				}
				resolve(value);
			};
			timeout = setTimeout(() => finish(false), Math.min(250, remainingMs));
			server.once('error', () => finish(false));
			server.listen({
				host: '127.0.0.1',
				port,
				signal: abortController.signal,
			}, () => finish(true));
		});
	}

	async close(): Promise<void> {
		const reservations = this.reservations.splice(0);
		await Promise.all(reservations.map(({ server, sockets }) => new Promise<void>((resolve) => {
			for (const socket of sockets) {
				socket.destroy();
			}
			if (!server.listening) {
				resolve();
				return;
			}
			try {
				server.close(() => resolve());
			} catch {
				resolve();
			}
		})));
	}
}

export async function loopbackPortsAreSimultaneouslyAvailable(
	ports: readonly number[],
	deadline: number,
): Promise<boolean> {
	const reservations = new LoopbackPortReservations();
	try {
		for (const port of uniqueLoopbackPorts(ports)) {
			if (!await reservations.reserve(port, deadline)) {
				return false;
			}
		}
		return true;
	} finally {
		await reservations.close();
	}
}

export const observerWorkspacePath = '/api/workspace';

export type ObserverWorkspaceRegistration =
	| { status: 'registered'; name: string }
	| { status: 'skipped'; reason: string }
	| { status: 'failed'; reason: string };

// Tells a shared loopback Splunk Observability Studio to read .observe
// artifacts from this window's workspace. The singleton keeps whichever root it
// started with, so without this a second window attaches but its Dashboards and
// Overview tabs keep showing the first repo. Failure only affects that view.
export function registerObserverWorkspace(
	restBaseUrl: string | undefined,
	workspaceRoot: string | undefined,
	timeoutMs = 2_000,
): Promise<ObserverWorkspaceRegistration> {
	if (!restBaseUrl || !workspaceRoot) {
		return Promise.resolve({ status: 'skipped', reason: 'no running observer or open workspace folder' });
	}
	let target: URL;
	try {
		target = new URL(observerWorkspacePath, restBaseUrl);
	} catch {
		return Promise.resolve({ status: 'skipped', reason: `invalid observer URL ${restBaseUrl}` });
	}
	const hostname = target.hostname.replace(/^\[|\]$/g, '');
	if (target.protocol !== 'http:' || !(hostname === 'localhost' || isLoopbackAddress(hostname))) {
		return Promise.resolve({ status: 'skipped', reason: `${target.origin} is not a local observer` });
	}
	const body = JSON.stringify({ root: workspaceRoot });
	return new Promise((resolve) => {
		const request = http.request(target, {
			method: 'POST',
			timeout: timeoutMs,
			headers: { 'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(body) },
		}, (response) => {
			let text = '';
			response.setEncoding('utf8');
			response.on('data', (chunk: string) => {
				if (text.length < 4096) {
					text += chunk;
				}
			});
			response.on('end', () => {
				if (response.statusCode !== 200) {
					resolve({ status: 'failed', reason: `${target.toString()} returned status ${response.statusCode ?? 'unknown'}` });
					return;
				}
				try {
					const parsed = JSON.parse(text) as { name?: unknown };
					resolve({ status: 'registered', name: typeof parsed.name === 'string' ? parsed.name : '' });
				} catch {
					resolve({ status: 'failed', reason: `${target.toString()} returned invalid JSON` });
				}
			});
			response.on('error', (error) => resolve({ status: 'failed', reason: error.message }));
		});
		request.on('timeout', () => request.destroy(new Error(`timed out after ${timeoutMs}ms`)));
		request.on('error', (error) => resolve({ status: 'failed', reason: error.message }));
		request.end(body);
	});
}

function isLoopbackAddress(address: string): boolean {
	return net.isIPv4(address) ? address.startsWith('127.') : address === '::1';
}
