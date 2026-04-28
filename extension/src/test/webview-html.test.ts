import * as assert from 'node:assert/strict';
import test, { describe, it } from 'node:test';
import {
	getObserverWebviewHtml,
	getObserverLoadingWebviewHtml,
	getObserverErrorWebviewHtml,
	getObserverStoppedWebviewHtml,
	getStatusBarUpdate,
} from '../webview-html';

// --- getObserverWebviewHtml ---

describe('getObserverWebviewHtml', () => {
	it('embeds the correct localhost URL with given port', () => {
		const html = getObserverWebviewHtml(56652);
		assert.ok(html.includes('http://127.0.0.1:56652'));
	});

	it('contains an iframe pointing to the observer URL', () => {
		const html = getObserverWebviewHtml(3000);
		assert.ok(html.includes('<iframe src="http://127.0.0.1:3000"'));
	});

	it('sets Content-Security-Policy with frame-src', () => {
		const html = getObserverWebviewHtml(8080);
		assert.ok(html.includes('frame-src http://127.0.0.1:8080'));
	});

	it('includes sandbox attributes on the iframe', () => {
		const html = getObserverWebviewHtml(3000);
		assert.ok(html.includes('sandbox="allow-scripts allow-same-origin allow-forms allow-popups"'));
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
