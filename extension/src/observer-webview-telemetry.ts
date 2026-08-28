import WebSocket from 'ws';
import { observerHostResponseByteLimit } from './observer-webview-host';

type TelemetryCommand = 'pause' | 'resume' | 'subscribe' | 'unsubscribe';

type ServerMessage = {
	data?: unknown;
	signal?: string;
	type: 'connected' | 'paused-update' | 'reload' | 'update';
};

export type ObserverWebSocketFactory = (
	url: string,
	options: { maxPayload: number },
) => WebSocket;

export class ObserverWebviewTelemetry {
	private disposed = false;
	private generation = 0;
	private paused = false;
	private reconnectTimer: NodeJS.Timeout | undefined;
	private socket: WebSocket | undefined;
	private subscribed = false;

	constructor(
		private readonly observerBaseUrl: string,
		private readonly postMessage: (message: unknown) => PromiseLike<boolean>,
		private readonly log: (message: string) => void,
		private readonly createSocket: ObserverWebSocketFactory = (url, options) => new WebSocket(url, options),
	) {}

	handle(command: TelemetryCommand): void {
		if (this.disposed) {
			return;
		}
		switch (command) {
			case 'subscribe':
				this.subscribed = true;
				this.connect();
				return;
			case 'unsubscribe':
				this.subscribed = false;
				this.paused = false;
				this.clearReconnect();
				this.closeSocket();
				return;
			case 'pause':
				this.paused = true;
				this.send({ type: 'pause' });
				return;
			case 'resume':
				this.paused = false;
				this.send({ type: 'resume' });
		}
	}

	dispose(): void {
		if (this.disposed) {
			return;
		}
		this.disposed = true;
		this.subscribed = false;
		this.clearReconnect();
		this.closeSocket();
	}

	private connect(): void {
		if (this.disposed || !this.subscribed || this.socket !== undefined) {
			return;
		}
		const generation = ++this.generation;
		const socket = this.createSocket(
			webSocketURL(this.observerBaseUrl),
			{ maxPayload: observerHostResponseByteLimit(new URL(this.observerBaseUrl)) },
		);
		this.socket = socket;

		socket.on('open', () => {
			if (!this.isCurrent(socket, generation) || !this.subscribed) {
				return;
			}
			this.send({ type: 'subscribe' });
			if (this.paused) {
				this.send({ type: 'pause' });
			}
		});
		socket.on('message', (data, isBinary) => {
			if (!this.isCurrent(socket, generation) || isBinary) {
				return;
			}
			let parsed: unknown;
			try {
				parsed = JSON.parse(data.toString());
			} catch {
				return;
			}
			if (!isServerMessage(parsed)) {
				return;
			}
			void this.postMessage({
				message: parsed,
				type: 'obstudio.host.telemetry-message',
			});
		});
		socket.on('error', (error) => {
			if (this.isCurrent(socket, generation)) {
				this.log(`Observer webview telemetry error: ${error.message}`);
			}
		});
		socket.on('close', () => {
			if (!this.isCurrent(socket, generation)) {
				return;
			}
			this.socket = undefined;
			if (this.disposed || !this.subscribed) {
				return;
			}
			void this.postMessage({
				message: { type: 'disconnected' },
				type: 'obstudio.host.telemetry-message',
			});
			this.reconnectTimer = setTimeout(() => {
				this.reconnectTimer = undefined;
				this.connect();
			}, 1_000);
		});
	}

	private isCurrent(socket: WebSocket, generation: number): boolean {
		return !this.disposed && this.socket === socket && this.generation === generation;
	}

	private send(message: { type: 'pause' | 'resume' | 'subscribe' }): void {
		const socket = this.socket;
		if (socket?.readyState !== WebSocket.OPEN) {
			return;
		}
		socket.send(JSON.stringify(message));
	}

	private closeSocket(): void {
		const socket = this.socket;
		this.socket = undefined;
		this.generation += 1;
		if (socket === undefined) {
			return;
		}
		socket.removeAllListeners();
		// ws emits an error when a connecting socket is terminated. The runtime is
		// intentionally disposing this generation, so absorb that expected event.
		socket.on('error', () => undefined);
		if (socket.readyState === WebSocket.CONNECTING) {
			socket.terminate();
		} else if (socket.readyState === WebSocket.OPEN) {
			socket.close();
		}
	}

	private clearReconnect(): void {
		if (this.reconnectTimer === undefined) {
			return;
		}
		clearTimeout(this.reconnectTimer);
		this.reconnectTimer = undefined;
	}
}

export function webSocketURL(observerBaseUrl: string): string {
	const url = new URL('api/ws', `${observerBaseUrl.replace(/\/+$/, '')}/`);
	if (url.protocol === 'http:') {
		url.protocol = 'ws:';
	} else if (url.protocol === 'https:') {
		url.protocol = 'wss:';
	} else {
		throw new Error('Observer webview telemetry requires an HTTP or HTTPS base URL.');
	}
	return url.toString();
}

function isServerMessage(value: unknown): value is ServerMessage {
	if (typeof value !== 'object' || value === null) {
		return false;
	}
	const message = value as Record<string, unknown>;
	return typeof message.type === 'string'
		&& ['connected', 'paused-update', 'reload', 'update'].includes(message.type)
		&& (message.signal === undefined || typeof message.signal === 'string');
}
