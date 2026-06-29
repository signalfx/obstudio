import * as crypto from 'node:crypto';

export const observerControlTokenSecretStorageKey = 'observability-studio.observer-control-token';

type SecretStorage = {
	get(key: string): Thenable<string | undefined>;
	store(key: string, value: string): Thenable<void>;
};

export async function resolveObserverControlToken(
	secretStorage: SecretStorage,
	environmentToken: string | undefined,
	generateToken: () => string = () => crypto.randomBytes(32).toString('base64url'),
): Promise<string> {
	const configuredToken = environmentToken?.trim();
	if (configuredToken) {
		return configuredToken;
	}

	const storedToken = (await secretStorage.get(observerControlTokenSecretStorageKey))?.trim();
	if (storedToken) {
		return storedToken;
	}

	const generatedToken = generateToken().trim();
	if (!generatedToken) {
		throw new Error('Could not generate an Observer control token.');
	}
	await secretStorage.store(observerControlTokenSecretStorageKey, generatedToken);
	return generatedToken;
}
