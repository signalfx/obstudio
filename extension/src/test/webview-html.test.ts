import * as assert from 'node:assert/strict';
import test, { describe, it } from 'node:test';
import * as vm from 'node:vm';
import {
	getObserverWebviewHtml,
	getObserverLoadingWebviewHtml,
	getObserverErrorWebviewHtml,
	getObserverStoppedWebviewHtml,
	getStatusBarUpdate,
} from '../webview-html';
import { cloudBridgeActions } from '../cloud-bridge';
import { getObserverStartupHint } from '../startup-errors';

const cloudBridgeToken = 'cloud-bridge-token-1234567890';

// --- getObserverWebviewHtml ---

describe('getObserverWebviewHtml', () => {
	it('embeds the correct localhost URL with given port', () => {
		const html = getObserverWebviewHtml('http://127.0.0.1:56652', 'test-nonce', cloudBridgeToken);
		assert.ok(html.includes('http://127.0.0.1:56652'));
	});

	it('contains an iframe pointing to the observer URL', () => {
		const html = getObserverWebviewHtml('http://127.0.0.1:3000', 'test-nonce', cloudBridgeToken);
		assert.ok(html.includes('src="http://127.0.0.1:3000/"'));
		assert.ok(!html.includes('vscodeBridgeToken'));
	});

	it('sets Content-Security-Policy with frame-src', () => {
		const html = getObserverWebviewHtml('http://127.0.0.1:8080', 'test-nonce', cloudBridgeToken);
		assert.ok(html.includes('frame-src http://127.0.0.1:8080'));
	});

	it('includes sandbox attributes on the iframe', () => {
		const html = getObserverWebviewHtml('http://127.0.0.1:3000', 'test-nonce', cloudBridgeToken);
		assert.ok(html.includes('sandbox="allow-scripts allow-same-origin allow-forms allow-popups"'));
		assert.equal(html.includes('allow="clipboard-read; clipboard-write"'), false);
	});

	it('bridges keyboard events from the Observer iframe to VS Code', () => {
		const html = getObserverWebviewHtml(
			'https://observer.example.test/path',
			'test-nonce',
			cloudBridgeToken,
		);
		assert.ok(html.includes("script-src 'nonce-test-nonce'"));
		assert.ok(html.includes('<script nonce="test-nonce">'));
		assert.ok(html.includes("message.type === 'obstudio:host-keyboard-event'"));
		assert.ok(html.includes("messageEvent.source === observerFrame.contentWindow"));
		assert.ok(html.includes("messageEvent.origin === observerOrigin"));
		assert.ok(html.includes("const observerOrigin = \"https://observer.example.test\""));
		assert.ok(html.includes('new KeyboardEvent(eventData.type'));
		assert.ok(html.includes('keyCode: { get: () => eventData.keyCode }'));
		assert.ok(html.includes('which: { get: () => eventData.keyCode }'));
		for (const modifier of ['altKey', 'ctrlKey', 'metaKey', 'shiftKey']) {
			assert.ok(html.includes(`${modifier}: eventData.${modifier}`));
		}
		assert.ok(html.includes('bubbles: true'));
		assert.ok(html.includes('cancelable: true'));
		assert.ok(html.includes('window.dispatchEvent(forwardedEvent)'));
	});

	it('executes the keyboard bridge and rejects untrusted message sources', () => {
		const html = getObserverWebviewHtml(
			'https://observer.example.test/path',
			'test-nonce',
			cloudBridgeToken,
		);
		const script = html.match(/<script nonce="test-nonce">([\s\S]*?)<\/script>/)?.[1];
		assert.ok(script, 'expected generated bridge script');

		type MessageListener = (event: {
			data: unknown;
			origin: string;
			source: unknown;
		}) => void;
		class FakeKeyboardEvent {
			readonly type: string;
			[key: string]: unknown;

			constructor(type: string, init: Record<string, unknown>) {
				this.type = type;
				Object.assign(this, init);
			}
		}

		const observerContentWindow = {
			postMessage: () => undefined,
		};
		const dispatchedEvents: FakeKeyboardEvent[] = [];
		let messageListener: MessageListener | undefined;
		const windowStub = {
			addEventListener(type: string, listener: MessageListener) {
				if (type === 'message') {
					messageListener = listener;
				}
			},
			dispatchEvent(event: FakeKeyboardEvent) {
				dispatchedEvents.push(event);
				return true;
			},
		};
		vm.runInNewContext(script, {
			acquireVsCodeApi: () => ({ postMessage: () => undefined }),
			document: {
				getElementById: () => ({
					addEventListener: () => undefined,
					contentWindow: observerContentWindow,
				}),
			},
			KeyboardEvent: FakeKeyboardEvent,
			window: windowStub,
		});
		assert.ok(messageListener, 'expected message listener to be registered');

		const message = {
			data: {
				type: 'obstudio:host-keyboard-event',
				event: {
					type: 'keydown',
					key: 'p',
					code: 'KeyP',
					keyCode: 80,
					location: 0,
					altKey: false,
					ctrlKey: false,
					metaKey: true,
					shiftKey: true,
					repeat: false,
				},
			},
			origin: 'https://observer.example.test',
			source: observerContentWindow,
		};
		messageListener(message);

		assert.equal(dispatchedEvents.length, 1);
		assert.equal(dispatchedEvents[0].type, 'keydown');
		assert.equal(dispatchedEvents[0].key, 'p');
		assert.equal(dispatchedEvents[0].code, 'KeyP');
		assert.equal(dispatchedEvents[0].keyCode, 80);
		assert.equal(dispatchedEvents[0].which, 80);
		assert.equal(dispatchedEvents[0].metaKey, true);
		assert.equal(dispatchedEvents[0].shiftKey, true);
		assert.equal(dispatchedEvents[0].bubbles, true);
		assert.equal(dispatchedEvents[0].cancelable, true);

		messageListener({ ...message, origin: 'https://attacker.example.test' });
		messageListener({ ...message, source: {} });
		messageListener({ ...message, data: { type: 'obstudio:host-keyboard-event' } });
		assert.equal(dispatchedEvents.length, 1);
	});

	it('relays cloud requests and responses only through the bound bridge', () => {
		const html = getObserverWebviewHtml(
			'https://observer.example.test/path',
			'test-nonce',
			cloudBridgeToken,
		);
		const script = html.match(/<script nonce="test-nonce">([\s\S]*?)<\/script>/)?.[1];
		assert.ok(script, 'expected generated bridge script');

		type MessageListener = (event: {
			data: unknown;
			origin: string;
			source: unknown;
		}) => void;
		const extensionMessages: unknown[] = [];
		const observerMessages: Array<{ message: unknown; targetOrigin: string }> = [];
		const observerContentWindow = {
			postMessage(message: unknown, targetOrigin: string) {
				observerMessages.push({ message, targetOrigin });
			},
		};
		let messageListener: MessageListener | undefined;
		const windowStub = {
			addEventListener(type: string, listener: MessageListener) {
				if (type === 'message') {
					messageListener = listener;
				}
			},
			dispatchEvent: () => true,
		};
		vm.runInNewContext(script, {
			acquireVsCodeApi: () => ({
				postMessage(message: unknown) {
					extensionMessages.push(message);
				},
			}),
			document: {
				getElementById: () => ({
					addEventListener: () => undefined,
					contentWindow: observerContentWindow,
				}),
			},
			KeyboardEvent: class {},
			window: windowStub,
		});
		assert.ok(messageListener, 'expected message listener to be registered');
		assert.equal(JSON.stringify(observerMessages), JSON.stringify([{
				message: {
					bridgeToken: cloudBridgeToken,
					supportedActions: cloudBridgeActions,
					type: 'obstudio.cloud.bridge',
			},
			targetOrigin: 'https://observer.example.test',
		}]));
		observerMessages.length = 0;

		messageListener({
			data: { type: 'obstudio.cloud.ready' },
			origin: 'https://observer.example.test',
			source: observerContentWindow,
		});
		assert.equal(extensionMessages.length, 1);
		assert.equal((extensionMessages[0] as { bridgeToken?: unknown }).bridgeToken, cloudBridgeToken);
		assert.equal((extensionMessages[0] as { type?: unknown }).type, 'obstudio.cloud.ready');
		assert.equal(JSON.stringify(observerMessages), JSON.stringify([{
				message: {
					bridgeToken: cloudBridgeToken,
					supportedActions: cloudBridgeActions,
					type: 'obstudio.cloud.bridge',
			},
			targetOrigin: 'https://observer.example.test',
		}]));
		extensionMessages.length = 0;
		observerMessages.length = 0;

		messageListener({
			data: { type: 'obstudio.cloud.ready' },
			origin: 'https://attacker.example.test',
			source: observerContentWindow,
		});
		messageListener({
			data: { type: 'obstudio.cloud.ready' },
			origin: 'https://observer.example.test',
			source: {},
		});
		assert.equal(extensionMessages.length, 0);
		assert.equal(observerMessages.length, 0);

		const request = {
			action: 'initialize',
			bridgeToken: cloudBridgeToken,
			requestId: 'cloud-request-123',
			type: 'obstudio.cloud.request',
		};
		messageListener({
			data: request,
			origin: 'https://observer.example.test',
			source: observerContentWindow,
		});
		assert.deepEqual(extensionMessages, [request]);

		messageListener({
			data: request,
			origin: 'https://attacker.example.test',
			source: observerContentWindow,
		});
		messageListener({
			data: { ...request, bridgeToken: 'other-cloud-bridge-token-1234' },
			origin: 'https://observer.example.test',
			source: observerContentWindow,
		});
		assert.equal(extensionMessages.length, 1);

		const response = {
			bridgeToken: cloudBridgeToken,
			ok: true,
			requestId: 'cloud-request-123',
			type: 'obstudio.cloud.response',
		};
		messageListener({
			data: response,
			origin: 'vscode-webview://extension',
			source: windowStub,
		});
		assert.deepEqual(observerMessages, [{
			message: response,
			targetOrigin: 'https://observer.example.test',
		}]);

		messageListener({
			data: { ...response, bridgeToken: 'other-cloud-bridge-token-1234' },
			origin: 'vscode-webview://extension',
			source: windowStub,
		});
		assert.equal(observerMessages.length, 1);
	});

	it('rejects an unsafe script nonce', () => {
		assert.throws(
			() => getObserverWebviewHtml('http://127.0.0.1:3000', "bad' nonce", cloudBridgeToken),
			/Webview nonce contains invalid characters/,
		);
	});

	it('rejects an unsafe cloud bridge token', () => {
		assert.throws(
			() => getObserverWebviewHtml('http://127.0.0.1:3000', 'test-nonce', '<unsafe>'),
			/Cloud bridge token contains invalid characters/,
		);
	});
});

// --- getObserverLoadingWebviewHtml ---

describe('getObserverLoadingWebviewHtml', () => {
	it('shows a starting message', () => {
		const html = getObserverLoadingWebviewHtml();
		assert.ok(html.includes('Splunk Observability Studio is starting'));
	});

	it('does not contain an iframe', () => {
		const html = getObserverLoadingWebviewHtml();
		assert.ok(!html.includes('<iframe'));
	});
});

// --- getObserverErrorWebviewHtml ---

describe('getObserverErrorWebviewHtml', () => {
	it('shows the error message', () => {
		const html = getObserverErrorWebviewHtml('Port 4317 is already in use by "obstudio (PID 1234)"');
		assert.ok(html.includes('Port 4317 is already in use'));
		assert.ok(html.includes('obstudio (PID 1234)'));
	});

	it('shows the "could not start" heading', () => {
		const html = getObserverErrorWebviewHtml('some error');
		assert.ok(html.includes('Observer could not start'));
	});

	it('includes restart hint', () => {
		const html = getObserverErrorWebviewHtml('some error');
		assert.ok(html.includes('Restart Observer'));
		assert.ok(html.includes('output log'));
	});

	it('includes port-specific restart guidance for port conflicts', () => {
		const html = getObserverErrorWebviewHtml(
			'Observer UI port 3000 is already in use by "nginx (PID 42)".',
			getObserverStartupHint('port-conflict'),
		);
		assert.ok(html.includes('freeing the conflicting port'));
	});

	it('includes platform guidance for ENOEXEC failures', () => {
		const html = getObserverErrorWebviewHtml(
			'binary cannot run on darwin-arm64 (spawn ENOEXEC).',
			getObserverStartupHint('wrong-platform'),
		);
		assert.ok(html.includes('platform-specific extension package'));
		assert.ok(html.includes('sharedObserverUrl'));
	});

	it('escapes HTML in error messages to prevent XSS', () => {
		const html = getObserverErrorWebviewHtml('<script>alert("xss")</script>');
		assert.ok(!html.includes('<script>alert'));
		assert.ok(html.includes('&lt;script&gt;'));
	});

	it('escapes quotes in error messages', () => {
		const html = getObserverErrorWebviewHtml('Port used by "nginx"');
		assert.ok(html.includes('&quot;nginx&quot;'));
	});
});

// --- getObserverStoppedWebviewHtml ---

describe('getObserverStoppedWebviewHtml', () => {
	it('shows stopped message', () => {
		const html = getObserverStoppedWebviewHtml();
		assert.ok(html.includes('Observer is stopped'));
	});

	it('includes start hint', () => {
		const html = getObserverStoppedWebviewHtml();
		assert.ok(html.includes('Start Observer'));
	});

	it('does not contain an iframe', () => {
		const html = getObserverStoppedWebviewHtml();
		assert.ok(!html.includes('<iframe'));
	});
});

// --- getStatusBarUpdate ---

describe('getStatusBarUpdate', () => {
	it('returns spinner icon and starting tooltip for starting state', () => {
		const update = getStatusBarUpdate('starting');
		assert.ok(update.text.includes('loading~spin'));
		assert.ok(update.text.includes('Observer'));
		assert.ok(update.tooltip.includes('starting'));
		assert.equal(update.command, 'observability-studio.statusMenu');
	});

	it('returns pulse icon for running state', () => {
		const update = getStatusBarUpdate('running');
		assert.ok(update.text.includes('pulse'));
		assert.ok(update.tooltip.includes('running'));
		assert.equal(update.command, 'observability-studio.statusMenu');
	});

	it('returns circle-outline icon for stopped state', () => {
		const update = getStatusBarUpdate('stopped');
		assert.ok(update.text.includes('circle-outline'));
		assert.ok(update.tooltip.includes('stopped'));
		assert.equal(update.command, 'observability-studio.statusMenu');
	});

	it('returns error icon for error state', () => {
		const update = getStatusBarUpdate('error');
		assert.ok(update.text.includes('error'));
		assert.ok(update.tooltip.includes('failed'));
		assert.equal(update.command, 'observability-studio.statusMenu');
	});

	it('always uses statusMenu command for all states', () => {
		for (const state of ['starting', 'running', 'stopped', 'error'] as const) {
			const update = getStatusBarUpdate(state);
			assert.equal(update.command, 'observability-studio.statusMenu',
				`State "${state}" should use statusMenu command`);
		}
	});
});
