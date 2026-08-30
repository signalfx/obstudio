import * as assert from 'node:assert/strict';
import test, { describe, it } from 'node:test';
import {
	getObserverWebviewHtml,
	getObserverLoadingWebviewHtml,
	getObserverErrorWebviewHtml,
	getObserverStoppedWebviewHtml,
	getStatusBarUpdate,
} from '../webview-html';
import { getObserverStartupHint } from '../startup-errors';

// --- getObserverWebviewHtml ---

describe('getObserverWebviewHtml', () => {
	it('loads the bundled React client directly as the top-level webview', () => {
		const html = getObserverWebviewHtml(
			'vscode-webview://extension-id',
			'vscode-webview://extension-id/dist/webview/main.js',
			'vscode-webview://extension-id/dist/webview/main.css',
		);
		assert.ok(html.includes('<div id="root"></div>'));
		assert.ok(html.includes('<script src="vscode-webview://extension-id/dist/webview/main.js"></script>'));
		assert.ok(html.includes('<link rel="stylesheet" href="vscode-webview://extension-id/dist/webview/main.css">'));
		assert.equal(html.includes('<iframe'), false);
	});

	it('uses a strict CSP without network, frame, or clipboard capabilities', () => {
		const html = getObserverWebviewHtml(
			'vscode-webview://extension-id',
			'vscode-webview://extension-id/main.js',
			'vscode-webview://extension-id/main.css',
		);
		assert.ok(html.includes("default-src 'none'"));
		assert.ok(html.includes('script-src vscode-webview://extension-id'));
		assert.ok(html.includes("style-src vscode-webview://extension-id 'unsafe-inline'"));
		assert.ok(html.includes('img-src vscode-webview://extension-id data:;'));
		assert.equal(html.includes('img-src vscode-webview://extension-id data: https:'), false);
		assert.ok(html.includes("connect-src 'none'"));
		assert.ok(html.includes("frame-src 'none'"));
		for (const forbidden of [
			'clipboard-read',
			'clipboard-write',
			'obstudio.cloud',
			'obstudio:host-keyboard-event',
			'navigator.clipboard',
		]) {
			assert.equal(html.includes(forbidden), false, forbidden);
		}
	});

	it('escapes asset and CSP values in HTML attributes', () => {
		const html = getObserverWebviewHtml(
			'vscode-webview://extension&amp;id',
			'vscode-webview://extension/main.js?value="unsafe"',
			'vscode-webview://extension/main.css?value=<unsafe>',
		);
		assert.ok(html.includes('vscode-webview://extension&amp;amp;id'));
		assert.ok(html.includes('main.js?value=&quot;unsafe&quot;'));
		assert.ok(html.includes('main.css?value=&lt;unsafe&gt;'));
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
