import * as crypto from 'node:crypto';

export type AgentIntegrationConfigFingerprint = {
	configurationDigest: string;
	mcpUrl: string;
	version: 1;
};

export type AgentIntegrationManagedConfig = {
	fingerprintMaterial: string;
	mcpUrl: string;
};

export type AgentIntegrationInstallCredentials = {
	controlToken: string;
	healthProofSecret: string;
	mcpUrl: string;
};

type StableAgentIntegrationInstallOptions = {
	captureInstalledConfig: (
		credentials: AgentIntegrationInstallCredentials,
	) => AgentIntegrationManagedConfig | Promise<AgentIntegrationManagedConfig>;
	install: (credentials: AgentIntegrationInstallCredentials) => Promise<void>;
	isManagedConfigUnchanged: (
		config: AgentIntegrationManagedConfig,
	) => boolean | Promise<boolean>;
	readCredentials: () => AgentIntegrationInstallCredentials | Promise<AgentIntegrationInstallCredentials>;
	recordInstalledConfig: (
		config: AgentIntegrationManagedConfig,
		credentials: AgentIntegrationInstallCredentials,
	) => Promise<void>;
};

const stableAgentIntegrationInstallAttempts = 3;

function agentIntegrationInstallCredentialsEqual(
	left: AgentIntegrationInstallCredentials,
	right: AgentIntegrationInstallCredentials,
): boolean {
	return left.controlToken === right.controlToken
		&& left.healthProofSecret === right.healthProofSecret
		&& left.mcpUrl === right.mcpUrl;
}

export async function installAgentIntegrationWithStableCredentials(
	options: StableAgentIntegrationInstallOptions,
): Promise<AgentIntegrationInstallCredentials> {
	let previousInstall: AgentIntegrationManagedConfig | undefined;
	for (let attempt = 0; attempt < stableAgentIntegrationInstallAttempts; attempt += 1) {
		if (previousInstall !== undefined
			&& !await options.isManagedConfigUnchanged(previousInstall)) {
			throw new Error('Agent integration configuration changed while Observer credentials were rotating; the newer configuration was preserved.');
		}

		const credentials = await options.readCredentials();
		await options.install(credentials);
		const installedConfig = await options.captureInstalledConfig(credentials);
		// Persist ownership before checking for rotation so a bounded retry failure
		// can be repaired by the next credential refresh.
		await options.recordInstalledConfig(installedConfig, credentials);
		const currentCredentials = await options.readCredentials();
		if (agentIntegrationInstallCredentialsEqual(credentials, currentCredentials)) {
			return credentials;
		}
		previousInstall = installedConfig;
	}

	throw new Error('Observer credentials changed during three consecutive agent integration install attempts; retry after Observer startup stabilizes.');
}

export function createAgentIntegrationConfigFingerprint(
	config: AgentIntegrationManagedConfig,
): AgentIntegrationConfigFingerprint {
	return {
		configurationDigest: crypto.createHash('sha256').update(config.fingerprintMaterial).digest('hex'),
		mcpUrl: config.mcpUrl,
		version: 1,
	};
}

export function shouldRefreshOwnedAgentIntegrationConfig(
	stored: unknown,
	current: AgentIntegrationManagedConfig | undefined,
	desiredMcpUrl: string,
): boolean {
	if (typeof stored !== 'object' || stored === null || current === undefined) {
		return false;
	}
	const candidate = stored as Partial<AgentIntegrationConfigFingerprint>;
	if (candidate.version !== 1
		|| candidate.mcpUrl !== desiredMcpUrl
		|| current.mcpUrl !== desiredMcpUrl
		|| typeof candidate.configurationDigest !== 'string'
		|| !/^[a-f0-9]{64}$/.test(candidate.configurationDigest)) {
		return false;
	}
	return createAgentIntegrationConfigFingerprint(current).configurationDigest
		=== candidate.configurationDigest;
}

export function caseInsensitiveHeaderValue(
	headers: Record<string, unknown> | undefined,
	name: string,
): unknown {
	const matches = Object.entries(headers ?? {}).filter(([candidate]) => (
		candidate.toLowerCase() === name.toLowerCase()
	));
	return matches.length === 1 ? matches[0][1] : undefined;
}

export function authorizationHeadersMatchControlToken(
	headers: Record<string, unknown> | undefined,
	controlToken: string,
): boolean {
	const matches = Object.entries(headers ?? {}).filter(([candidate]) => (
		candidate.toLowerCase() === 'authorization'
	));
	const normalizedToken = controlToken.trim();
	if (normalizedToken === '') {
		return matches.length === 0;
	}
	return matches.length === 1 && matches[0][1] === `Bearer ${normalizedToken}`;
}

function parseTOMLBasicString(value: string): string | undefined {
	try {
		const parsed: unknown = JSON.parse(value);
		return typeof parsed === 'string' ? parsed : undefined;
	} catch {
		return undefined;
	}
}

function parseTOMLString(value: string): string | undefined {
	const trimmed = value.trim();
	if (trimmed.startsWith('"')) {
		return parseTOMLBasicString(trimmed);
	}
	const literal = /^'([^']*)'$/.exec(trimmed);
	return literal?.[1];
}

function parseTOMLSimpleKey(value: string): string | undefined {
	const trimmed = value.trim();
	if (/^[A-Za-z0-9_-]+$/.test(trimmed)) {
		return trimmed;
	}
	return parseTOMLString(trimmed);
}

type TOMLTableHeader = {
	kind: 'array-table' | 'table';
	path: string[];
};

function parseTOMLTableHeader(line: string): TOMLTableHeader | undefined {
	const comment = findUnquotedCharacter(line, '#');
	const structural = (comment < 0 ? line : line.slice(0, comment)).trim();
	const startsArrayTable = structural.startsWith('[[');
	const endsArrayTable = structural.endsWith(']]');
	if (startsArrayTable !== endsArrayTable
		|| (!startsArrayTable && (!structural.startsWith('[') || !structural.endsWith(']')))) {
		return undefined;
	}
	const kind = startsArrayTable ? 'array-table' : 'table';
	const segments = splitUnquoted(
		structural.slice(kind === 'array-table' ? 2 : 1, kind === 'array-table' ? -2 : -1),
		'.',
	);
	if (segments === undefined || segments.length === 0) {
		return undefined;
	}
	const path = segments.map(parseTOMLSimpleKey);
	return path.every((segment): segment is string => segment !== undefined)
		? { kind, path }
		: undefined;
}

function tomlPathEquals(path: readonly string[], expected: readonly string[]): boolean {
	return path.length === expected.length && path.every((segment, index) => segment === expected[index]);
}

function tomlPathStartsWith(path: readonly string[], expected: readonly string[]): boolean {
	return path.length >= expected.length && expected.every((segment, index) => path[index] === segment);
}

function parseTOMLAssignment(line: string): { key: string; value: string } | undefined {
	const assignment = findUnquotedCharacter(line, '=');
	if (assignment < 0) {
		return undefined;
	}
	const key = parseTOMLSimpleKey(line.slice(0, assignment));
	if (key === undefined) {
		return undefined;
	}
	let value = line.slice(assignment + 1);
	const comment = findUnquotedCharacter(value, '#');
	if (comment >= 0) {
		value = value.slice(0, comment);
	}
	return { key, value: value.trim() };
}

type CodexAuthorizationInspection = {
	headerContainerCount: number;
	malformed: boolean;
	values: string[];
};

function inspectCodexObstudioAuthorization(section: string): CodexAuthorizationInspection {
	const values: string[] = [];
	const lines = section.split(/\r?\n/);
	let currentTable: TOMLTableHeader | undefined;
	let headerContainerCount = 0;
	let malformed = false;
	for (const line of lines) {
		const trimmed = line.trim();
		const table = parseTOMLTableHeader(line);
		if (table !== undefined) {
			currentTable = table;
			if (currentTable.kind === 'table'
				&& tomlPathEquals(currentTable.path, ['mcp_servers', 'obstudio', 'http_headers'])) {
				headerContainerCount += 1;
			}
			continue;
		}
		if (currentTable?.kind === 'table'
			&& tomlPathEquals(currentTable.path, ['mcp_servers', 'obstudio'])) {
			const assignment = parseTOMLAssignment(line);
			if (assignment?.key !== 'http_headers') {
				continue;
			}
			headerContainerCount += 1;
			const inlineValues = parseInlineAuthorizationValues(assignment.value);
			if (inlineValues === undefined) {
				malformed = true;
			} else {
				values.push(...inlineValues);
			}
			continue;
		}
		if (currentTable?.kind !== 'table'
			|| !tomlPathEquals(currentTable.path, ['mcp_servers', 'obstudio', 'http_headers'])) {
			continue;
		}
		if (trimmed === '' || trimmed.startsWith('#')) {
			continue;
		}
		const assignment = parseTOMLAssignment(line);
		if (assignment === undefined) {
			malformed = true;
			continue;
		}
		if (assignment.key.toLowerCase() !== 'authorization') {
			continue;
		}
		const value = parseTOMLString(assignment.value);
		if (value !== undefined) {
			values.push(value);
		} else {
			malformed = true;
		}
	}

	return { headerContainerCount, malformed, values };
}

export function getCodexObstudioAuthorization(section: string): string | undefined {
	const { headerContainerCount, malformed, values } = inspectCodexObstudioAuthorization(section);
	return !malformed && headerContainerCount === 1 && values.length === 1
		? values[0]
		: undefined;
}

export function codexObstudioAuthorizationMatchesControlToken(
	section: string,
	controlToken: string,
): boolean {
	const { headerContainerCount, malformed, values } = inspectCodexObstudioAuthorization(section);
	if (malformed || headerContainerCount > 1 || values.length > 1) {
		return false;
	}
	const normalizedToken = controlToken.trim();
	if (normalizedToken === '') {
		return values.length === 0;
	}
	return headerContainerCount === 1
		&& values.length === 1
		&& values[0] === `Bearer ${normalizedToken}`;
}

export function getCodexObstudioUrl(section: string): string | undefined {
	const values: string[] = [];
	let currentTable: TOMLTableHeader | undefined;
	for (const line of section.split(/\r?\n/)) {
		const table = parseTOMLTableHeader(line);
		if (table !== undefined) {
			currentTable = table;
			continue;
		}
		if (currentTable?.kind !== 'table'
			|| !tomlPathEquals(currentTable.path, ['mcp_servers', 'obstudio'])) {
			continue;
		}
		const assignment = parseTOMLAssignment(line);
		if (assignment?.key !== 'url') {
			continue;
		}
		const value = parseTOMLString(assignment.value);
		if (value === undefined) {
			return undefined;
		}
		values.push(value);
	}
	return values.length === 1 ? values[0] : undefined;
}

function parseInlineAuthorizationValues(table: string): string[] | undefined {
	if (!table.startsWith('{')) {
		return undefined;
	}
	const closingBrace = findUnquotedCharacter(table, '}', 1);
	if (closingBrace < 0 || !/^\s*(?:#.*)?$/.test(table.slice(closingBrace + 1))) {
		return undefined;
	}
	const entries = splitUnquoted(table.slice(1, closingBrace), ',');
	if (entries === undefined) {
		return undefined;
	}

	const values: string[] = [];
	for (const entry of entries) {
		if (entry.trim() === '') {
			continue;
		}
		const assignment = parseTOMLAssignment(entry);
		if (assignment === undefined) {
			return undefined;
		}
		if (assignment.key.toLowerCase() !== 'authorization') {
			continue;
		}
		const value = parseTOMLString(assignment.value);
		if (value === undefined) {
			return undefined;
		}
		values.push(value);
	}
	return values;
}

function findUnquotedCharacter(value: string, target: string, start = 0): number {
	let quote: '"' | "'" | undefined;
	let escaped = false;
	for (let index = start; index < value.length; index += 1) {
		const character = value[index];
		if (quote === '"' && escaped) {
			escaped = false;
			continue;
		}
		if (quote === '"' && character === '\\') {
			escaped = true;
			continue;
		}
		if (quote !== undefined) {
			if (character === quote) {
				quote = undefined;
			}
			continue;
		}
		if (character === '"' || character === "'") {
			quote = character;
			continue;
		}
		if (character === target) {
			return index;
		}
	}
	return -1;
}

function splitUnquoted(value: string, separator: string): string[] | undefined {
	const parts: string[] = [];
	let quote: '"' | "'" | undefined;
	let escaped = false;
	let start = 0;
	for (let index = 0; index < value.length; index += 1) {
		const character = value[index];
		if (quote === '"' && escaped) {
			escaped = false;
			continue;
		}
		if (quote === '"' && character === '\\') {
			escaped = true;
			continue;
		}
		if (quote !== undefined) {
			if (character === quote) {
				quote = undefined;
			}
			continue;
		}
		if (character === '"' || character === "'") {
			quote = character;
			continue;
		}
		if (character === separator) {
			parts.push(value.slice(start, index));
			start = index + 1;
		}
	}
	if (quote !== undefined || escaped) {
		return undefined;
	}
	parts.push(value.slice(start));
	return parts;
}

export function getCodexObstudioSection(content: string): string | undefined {
	const lines = content.split(/\r?\n/);
	let section: string[] | undefined;
	for (const line of lines) {
		const table = parseTOMLTableHeader(line);
		if (table !== undefined) {
			if (table.kind === 'table'
				&& tomlPathEquals(table.path, ['mcp_servers', 'obstudio'])) {
				section = [line];
				continue;
			}
			if (section !== undefined
				&& tomlPathStartsWith(table.path, ['mcp_servers', 'obstudio'])
				&& (table.kind === 'table' || table.path.length > 2)) {
				section.push(line);
				continue;
			}
			if (section !== undefined) {
				break;
			}
		}
		if (section !== undefined) {
			section.push(line);
		}
	}
	return section?.join('\n');
}
