import * as fs from 'node:fs';
import * as path from 'node:path';

export type ObserverBackend = {
	args: string[];
	command: string;
	cwd: string;
	label: string;
};

export function resolveBackend(extensionPath: string): ObserverBackend {
	const binary = path.join(extensionPath, 'dist', 'observer', 'obstudio');

	if (fs.existsSync(binary)) {
		return {
			args: [],
			command: binary,
			cwd: path.dirname(binary),
			label: 'observer',
		};
	}

	throw new Error(
		`observer binary not found at ${binary}. Run 'npm run compile' in the extension directory.`,
	);
}
