import type { IncomingMessage } from 'node:http';
import {
	cloudBridgeActions,
	isSkillDocsId,
	maxCloudAccessTokenBytes,
	type CloudBridgeAction,
	type SkillDocsId,
} from './cloud-bridge';
import { isLocalObserverControlHost } from './backend';

export type ObserverHostCloudPayload = {
	accessToken?: string;
	enabled?: boolean;
	expectedVersion?: string;
	realm?: string;
	skill?: SkillDocsId;
};

export type ObserverHostRequest =
	| {
		body?: string;
		kind: 'http';
		method: 'GET' | 'POST';
		path: string;
	}
	| {
		action: CloudBridgeAction;
		kind: 'cloud';
		payload?: ObserverHostCloudPayload;
	};

export type ObserverHostRequestEnvelope = {
	request: ObserverHostRequest;
	requestId: string;
	type: 'obstudio.host.request';
};

export type ObserverHostCancelEnvelope = {
	requestId: string;
	type: 'obstudio.host.cancel';
};

export type ObserverHostTelemetryEnvelope = {
	command: 'pause' | 'resume' | 'subscribe' | 'unsubscribe';
	type: 'obstudio.host.telemetry';
};

const maxHostRequestBodyBytes = 1 << 20;
export const maxRemoteObserverHostResponseBytes = 16 << 20;
export const maxLocalObserverHostResponseBytes = 64 << 20;
const maxHostRequestPathLength = 4096;
const requestIdPattern = /^[A-Za-z0-9_-]{8,128}$/;
const observerStateVersionPattern = /^[A-Za-z0-9_-]{43}$/;
const traceDetailPathPattern = /^\/api\/query\/traces\/[0-9a-fA-F]{32}$/;
const allowedGetPaths = new Set([
	'/api/audit/score',
	'/api/dashboards/preview',
	'/api/health',
	'/api/query/logs',
	'/api/query/logs/filter-values',
	'/api/query/metrics',
	'/api/query/metrics/filter-values',
	'/api/query/stats',
	'/api/query/stats/services',
	'/api/query/traces',
	'/api/query/traces/filter-values',
	'/api/query/validation/latest',
	'/api/query/validation/summary',
	'/api/splunk/export',
]);
const allowedPostPaths = new Set(['/api/validation/run']);

export function observerHostResponseByteLimit(url: URL): number {
	return isLocalObserverControlHost(url.hostname)
		? maxLocalObserverHostResponseBytes
		: maxRemoteObserverHostResponseBytes;
}

export type ObserverHostHTTPResponse = {
	body: string;
	headers?: Record<string, string>;
	status: number;
	statusText: string;
};

export function collectObserverHostHTTPResponse(
	response: IncomingMessage,
	request: { destroy(error?: Error): void },
	responseByteLimit: number,
): Promise<ObserverHostHTTPResponse> {
	return new Promise((resolve, reject) => {
		const chunks: Buffer[] = [];
		let settled = false;
		let size = 0;
		const cleanup = () => {
			response.removeListener('data', onData);
			response.removeListener('end', onEnd);
			response.removeListener('aborted', onAborted);
			response.removeListener('close', onClose);
			// ClientRequest.destroy() can trigger a delayed response error after
			// another event settled this promise. Retain the one-shot listener so
			// that late stream failure cannot become an uncaught extension error.
		};
		const finish = (callback: () => void) => {
			if (settled) {
				return;
			}
			settled = true;
			cleanup();
			callback();
		};
		const fail = (error: Error) => finish(() => reject(error));
		const onData = (chunk: Buffer | string) => {
			const buffer = Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk);
			size += buffer.length;
			if (size > responseByteLimit) {
				const error = new Error(
					`Observer response exceeded ${responseByteLimit / (1 << 20)} MiB.`,
				);
				request.destroy(error);
				fail(error);
				return;
			}
			chunks.push(buffer);
		};
		const onEnd = () => {
			if (!response.complete) {
				fail(new Error('Observer response ended before the message was complete.'));
				return;
			}
			const contentType = response.headers['content-type'];
			const responseHeaders = typeof contentType === 'string'
				? { 'content-type': contentType }
				: undefined;
			finish(() => resolve({
				body: Buffer.concat(chunks).toString('utf8'),
				headers: responseHeaders,
				status: response.statusCode ?? 0,
				statusText: response.statusMessage ?? '',
			}));
		};
		const onError = (error: Error) => fail(error);
		const onAborted = () => fail(new Error('Observer response was aborted before completion.'));
		const onClose = () => fail(new Error('Observer response closed before completion.'));

		response.on('data', onData);
		response.once('end', onEnd);
		response.once('error', onError);
		response.once('aborted', onAborted);
		response.once('close', onClose);
	});
}

export function isObserverHostRequestEnvelope(value: unknown): value is ObserverHostRequestEnvelope {
	if (typeof value !== 'object' || value === null) {
		return false;
	}
	const envelope = value as Record<string, unknown>;
	return envelope.type === 'obstudio.host.request'
		&& isHostRequestId(envelope.requestId)
		&& isObserverHostRequest(envelope.request);
}

export function isObserverHostCancelEnvelope(value: unknown): value is ObserverHostCancelEnvelope {
	if (typeof value !== 'object' || value === null) {
		return false;
	}
	const envelope = value as Record<string, unknown>;
	return envelope.type === 'obstudio.host.cancel' && isHostRequestId(envelope.requestId);
}

export function isObserverHostTelemetryEnvelope(value: unknown): value is ObserverHostTelemetryEnvelope {
	if (typeof value !== 'object' || value === null) {
		return false;
	}
	const envelope = value as Record<string, unknown>;
	return envelope.type === 'obstudio.host.telemetry'
		&& typeof envelope.command === 'string'
		&& ['pause', 'resume', 'subscribe', 'unsubscribe'].includes(envelope.command);
}

export function isAllowedObserverHostHTTPPath(method: 'GET' | 'POST', value: string): boolean {
	if (value.length === 0 || value.length > maxHostRequestPathLength || value.includes('#')) {
		return false;
	}
	let parsed: URL;
	try {
		parsed = new URL(value, 'http://observer.invalid');
	} catch {
		return false;
	}
	if (parsed.origin !== 'http://observer.invalid' || `${parsed.pathname}${parsed.search}` !== value) {
		return false;
	}
	if (method === 'GET') {
		return allowedGetPaths.has(parsed.pathname) || traceDetailPathPattern.test(parsed.pathname);
	}
	return allowedPostPaths.has(parsed.pathname);
}

function isObserverHostRequest(value: unknown): value is ObserverHostRequest {
	if (typeof value !== 'object' || value === null) {
		return false;
	}
	const request = value as Record<string, unknown>;
	if (request.kind === 'http') {
		return (request.method === 'GET' || request.method === 'POST')
			&& typeof request.path === 'string'
			&& isAllowedObserverHostHTTPPath(request.method, request.path)
			&& (request.body === undefined
				|| (typeof request.body === 'string'
					&& Buffer.byteLength(request.body, 'utf8') <= maxHostRequestBodyBytes))
			&& (request.method === 'POST' || request.body === undefined);
	}
	if (request.kind !== 'cloud' || !isCloudAction(request.action)) {
		return false;
	}
	return isObserverHostCloudRequestPayload(request.action, request.payload);
}

function isObserverHostCloudRequestPayload(action: CloudBridgeAction, value: unknown): boolean {
	switch (action) {
		case 'connect':
			return isObserverHostCloudPayload(value)
				&& typeof value.accessToken === 'string'
				&& typeof value.expectedVersion === 'string'
				&& typeof value.realm === 'string'
				&& value.enabled === undefined
				&& value.skill === undefined;
		case 'set-enabled':
			return isObserverHostCloudPayload(value)
				&& typeof value.enabled === 'boolean'
				&& typeof value.expectedVersion === 'string'
				&& value.accessToken === undefined
				&& value.realm === undefined
				&& value.skill === undefined;
		case 'open-skill-docs':
			return isObserverHostCloudPayload(value)
				&& isSkillDocsId(value.skill)
				&& value.accessToken === undefined
				&& value.enabled === undefined
				&& value.expectedVersion === undefined
				&& value.realm === undefined;
		case 'forget':
			return isObserverHostCloudPayload(value)
				&& typeof value.expectedVersion === 'string'
				&& value.accessToken === undefined
				&& value.enabled === undefined
				&& value.realm === undefined
				&& value.skill === undefined;
		case 'initialize':
		case 'open-audit-report':
		case 'open-free-edition':
		case 'open-ingest-token-help':
			return value === undefined;
	}
}

function isObserverHostCloudPayload(value: unknown): value is ObserverHostCloudPayload {
	if (typeof value !== 'object' || value === null) {
		return false;
	}
	const payload = value as Record<string, unknown>;
	return Object.keys(payload).every((key) => [
		'accessToken',
		'enabled',
		'expectedVersion',
		'realm',
		'skill',
	].includes(key))
		&& (payload.accessToken === undefined
			|| (typeof payload.accessToken === 'string'
				&& Buffer.byteLength(payload.accessToken, 'utf8') <= maxCloudAccessTokenBytes))
		&& (payload.enabled === undefined || typeof payload.enabled === 'boolean')
		&& (payload.expectedVersion === undefined
			|| (typeof payload.expectedVersion === 'string'
				&& observerStateVersionPattern.test(payload.expectedVersion)))
		&& (payload.realm === undefined
			|| (typeof payload.realm === 'string' && payload.realm.length <= 32))
		&& (payload.skill === undefined || isSkillDocsId(payload.skill));
}

function isCloudAction(value: unknown): value is CloudBridgeAction {
	return typeof value === 'string' && (cloudBridgeActions as readonly string[]).includes(value);
}

function isHostRequestId(value: unknown): value is string {
	return typeof value === 'string' && requestIdPattern.test(value);
}
