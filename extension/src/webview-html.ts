// Pure functions for generating webview HTML and escaping content.
// Extracted from extension.ts so they can be unit-tested without VS Code APIs.

import { getObserverStartupHint } from './startup-errors';

export function escapeHtml(text: string): string {
	return text
		.replace(/&/g, '&amp;')
		.replace(/</g, '&lt;')
		.replace(/>/g, '&gt;')
		.replace(/"/g, '&quot;');
}

export function getObserverWebviewHtml(observerUrl: string, nonce: string): string {
	if (!/^[A-Za-z0-9+/_=-]+$/.test(nonce)) {
		throw new Error('Webview nonce contains invalid characters.');
	}
	const iframeSrc = escapeHtml(observerUrl);
	const observerOrigin = JSON.stringify(new URL(observerUrl).origin).replace(/</g, '\\u003c');

	return `<!DOCTYPE html>
<html lang="en">
<head>
	<meta charset="UTF-8">
	<meta
		http-equiv="Content-Security-Policy"
		content="default-src 'none'; frame-src ${iframeSrc}; script-src 'nonce-${nonce}'; style-src 'unsafe-inline'; worker-src 'none';"
	>
	<meta name="viewport" content="width=device-width, initial-scale=1.0">
	<title>Observer</title>
	<style>
		html, body, iframe {
			height: 100%;
			margin: 0;
			padding: 0;
			width: 100%;
		}

		body {
			background: var(--vscode-editor-background);
		}

		iframe {
			border: 0;
		}
	</style>
</head>
<body>
	<iframe id="observer-frame" src="${iframeSrc}" title="Observer" sandbox="allow-scripts allow-same-origin allow-forms allow-popups"></iframe>
	<script nonce="${nonce}">
		const observerFrame = document.getElementById('observer-frame');
		const observerOrigin = ${observerOrigin};
		window.addEventListener('message', (messageEvent) => {
			if (messageEvent.source !== observerFrame.contentWindow || messageEvent.origin !== observerOrigin) return;
			const message = messageEvent.data;
			if (!message || message.type !== 'obstudio:host-keyboard-event' || !message.event) return;
			const eventData = message.event;
			if ((eventData.type !== 'keydown' && eventData.type !== 'keyup')
				|| typeof eventData.key !== 'string'
				|| typeof eventData.code !== 'string'
				|| typeof eventData.keyCode !== 'number') return;
			const forwardedEvent = new KeyboardEvent(eventData.type, {
				key: eventData.key,
				code: eventData.code,
				location: eventData.location,
				altKey: eventData.altKey,
				ctrlKey: eventData.ctrlKey,
				metaKey: eventData.metaKey,
				shiftKey: eventData.shiftKey,
				repeat: eventData.repeat,
				bubbles: true,
				cancelable: true,
			});
			Object.defineProperties(forwardedEvent, {
				keyCode: { get: () => eventData.keyCode },
				which: { get: () => eventData.keyCode },
			});
			window.dispatchEvent(forwardedEvent);
		});
	</script>
</body>
</html>`;
}

export function getObserverLoadingWebviewHtml(): string {
	return `<!DOCTYPE html>
<html lang="en">
<head>
	<meta charset="UTF-8">
	<meta
		http-equiv="Content-Security-Policy"
		content="default-src 'none'; style-src 'unsafe-inline';"
	>
	<meta name="viewport" content="width=device-width, initial-scale=1.0">
	<title>Observer</title>
	<style>
		body {
			align-items: center;
			background: var(--vscode-editor-background);
			color: var(--vscode-foreground);
			display: flex;
			font-family: var(--vscode-font-family);
			height: 100vh;
			justify-content: center;
			margin: 0;
			padding: 24px;
			text-align: center;
		}
	</style>
</head>
<body>
	<div>Splunk Observability Studio is starting…</div>
</body>
</html>`;
}

export function getObserverErrorWebviewHtml(
	errorMessage: string,
	startupHint: string = getObserverStartupHint('generic'),
): string {
	const escaped = escapeHtml(errorMessage);
	const hint = escapeHtml(startupHint);

	return `<!DOCTYPE html>
<html lang="en">
<head>
	<meta charset="UTF-8">
	<meta
		http-equiv="Content-Security-Policy"
		content="default-src 'none'; style-src 'unsafe-inline';"
	>
	<meta name="viewport" content="width=device-width, initial-scale=1.0">
	<title>Observer</title>
	<style>
		body {
			align-items: center;
			background: var(--vscode-editor-background);
			color: var(--vscode-foreground);
			display: flex;
			font-family: var(--vscode-font-family);
			height: 100vh;
			justify-content: center;
			margin: 0;
			padding: 24px;
			text-align: center;
		}
		.container { max-width: 520px; }
		h2 { color: var(--vscode-errorForeground); margin-bottom: 12px; }
		.error-detail {
			background: var(--vscode-textBlockQuote-background);
			border-left: 3px solid var(--vscode-errorForeground);
			color: var(--vscode-foreground);
			font-family: var(--vscode-editor-font-family, monospace);
			font-size: 12px;
			margin: 16px 0;
			padding: 12px;
			text-align: left;
			white-space: pre-wrap;
			word-break: break-word;
		}
		.hint {
			color: var(--vscode-descriptionForeground);
			font-size: 13px;
			line-height: 1.5;
		}
	</style>
</head>
<body>
	<div class="container">
		<h2>Observer could not start</h2>
		<div class="error-detail">${escaped}</div>
		<p class="hint">
			${hint}
		</p>
	</div>
</body>
</html>`;
}

export function getObserverStoppedWebviewHtml(): string {
	return `<!DOCTYPE html>
<html lang="en">
<head>
	<meta charset="UTF-8">
	<meta
		http-equiv="Content-Security-Policy"
		content="default-src 'none'; style-src 'unsafe-inline';"
	>
	<meta name="viewport" content="width=device-width, initial-scale=1.0">
	<title>Observer</title>
	<style>
		body {
			align-items: center;
			background: var(--vscode-editor-background);
			color: var(--vscode-foreground);
			display: flex;
			font-family: var(--vscode-font-family);
			height: 100vh;
			justify-content: center;
			margin: 0;
			padding: 24px;
			text-align: center;
		}
		.hint {
			color: var(--vscode-descriptionForeground);
			font-size: 13px;
			margin-top: 8px;
		}
	</style>
</head>
<body>
	<div>
		<div>Observer is stopped.</div>
		<p class="hint">
			Use the Command Palette (Cmd+Shift+P) and run
			<strong>Splunk Observability Studio: Start Observer</strong> to start it again.
		</p>
	</div>
</body>
</html>`;
}

export type StatusBarState = 'starting' | 'running' | 'stopped' | 'error';

export interface StatusBarUpdate {
	text: string;
	tooltip: string;
	command: string;
}

export function getStatusBarUpdate(state: StatusBarState): StatusBarUpdate {
	const command = 'observability-studio.statusMenu';

	switch (state) {
		case 'starting':
			return { text: '$(loading~spin) Observer', tooltip: 'Observer is starting...', command };
		case 'running':
			return { text: '$(pulse) Observer', tooltip: 'Observer is running — click for options', command };
		case 'stopped':
			return { text: '$(circle-outline) Observer', tooltip: 'Observer is stopped — click to start', command };
		case 'error':
			return { text: '$(error) Observer', tooltip: 'Observer failed — click for options', command };
	}
}

export function getErrorMessage(error: unknown): string {
	if (error instanceof Error) {
		return error.message;
	}

	return String(error);
}
