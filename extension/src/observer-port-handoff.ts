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
