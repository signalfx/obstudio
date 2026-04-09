// Pure functions for generating webview HTML and escaping content.
// Extracted from extension.ts so they can be unit-tested without VS Code APIs.

export function escapeHtml(text: string): string {
	return text
		.replace(/&/g, '&amp;')
		.replace(/</g, '&lt;')
		.replace(/>/g, '&gt;')
		.replace(/"/g, '&quot;');
}

export function getObserverWebviewHtml(port: number): string {
	const observerUrl = `http://127.0.0.1:${port}`;

	return `<!DOCTYPE html>
<html lang="en">
<head>
	<meta charset="UTF-8">
	<meta
		http-equiv="Content-Security-Policy"
		content="default-src 'none'; frame-src ${observerUrl}; style-src 'unsafe-inline'; worker-src 'none';"
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
	<iframe src="${observerUrl}" title="Observer" sandbox="allow-scripts allow-same-origin allow-forms allow-popups"></iframe>
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
	<div>Observability Studio is starting…</div>
</body>
</html>`;
}

export function getObserverErrorWebviewHtml(errorMessage: string): string {
	const escaped = escapeHtml(errorMessage);

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
			Use the Command Palette (Cmd+Shift+P) and run
			<strong>Observability Studio: Restart Observer</strong> after
			freeing the port.
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
			<strong>Observability Studio: Start Observer</strong> to start it again.
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
