import * as fs from 'node:fs';
import * as path from 'node:path';

export type ObserverBackend = {
	args: string[];
	command: string;
	cwd: string;
	env: Record<string, string>;
	label: string;
};

export type ObserverHealth = {
	apiVersion?: string;
	endpoints?: Record<string, string>;
	kind?: string;
	mode?: string;
	owner?: string;
	startedAt?: string;
	version?: string;
};

export function normalizeObserverBaseUrl(raw: string): string {
	const trimmed = raw.trim();
	if (trimmed.length === 0) {
		throw new Error('Observer URL cannot be empty.');
	}

	const parsed = new URL(trimmed);
	if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') {
		throw new Error(`Observer URL must use http or https: ${raw}`);
	}

	if (parsed.pathname.endsWith('/mcp')) {
		parsed.pathname = parsed.pathname.slice(0, -4) || '/';
	}

	parsed.search = '';
	parsed.hash = '';
	return parsed.toString().replace(/\/$/, '');
}

export function buildObserverValidatorSummaryUrl(baseUrl: string): string {
	return `${normalizeObserverBaseUrl(baseUrl)}/api/query/validation/summary`;
}

export function buildObserverHealthUrl(baseUrl: string): string {
	return `${normalizeObserverBaseUrl(baseUrl)}/api/health`;
}

export function observerPortFromUrl(baseUrl: string): number | undefined {
	const parsed = new URL(normalizeObserverBaseUrl(baseUrl));
	if (parsed.port.length > 0) {
		return Number(parsed.port);
	}
	if (parsed.protocol === 'http:') {
		return 80;
	}
	if (parsed.protocol === 'https:') {
		return 443;
	}
	return undefined;
}

export function resolveBackend(extensionPath: string): ObserverBackend {
	const candidates = process.platform === 'win32'
		? ['obstudio.exe', 'obstudio']
		: ['obstudio', 'obstudio.exe'];

	for (const candidate of candidates) {
		const binary = path.join(extensionPath, 'dist', 'observer', candidate);
		if (!fs.existsSync(binary)) {
			continue;
		}

		const env: Record<string, string> = {};
		const weaverCandidates = path.extname(binary) === '.exe'
			? ['weaver.exe', 'weaver']
			: ['weaver', 'weaver.exe'];
		for (const weaverCandidate of weaverCandidates) {
			const weaver = path.join(path.dirname(binary), weaverCandidate);
			if (!fs.existsSync(weaver)) {
				continue;
			}
			env.WEAVER_PATH = weaver;
			break;
		}
		return {
			args: [],
			command: binary,
			cwd: path.dirname(binary),
			env,
			label: 'observer',
		};
	}

	throw new Error(
		`observer binary not found in ${path.join(extensionPath, 'dist', 'observer')}. Run 'npm run compile' in the extension directory.`,
	);
}
