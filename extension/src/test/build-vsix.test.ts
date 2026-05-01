import * as assert from 'node:assert/strict';
import test from 'node:test';

const {
	buildVsceArgs,
	normalizeReleaseVersion,
	releaseTagFromEnvironment,
	resolveReleaseVersion,
} = require('../../build-vsix.js') as {
	buildVsceArgs: (options?: { releaseVersion?: string | null; extraArgs?: string[] }) => string[];
	normalizeReleaseVersion: (value: string) => string;
	releaseTagFromEnvironment: (env?: NodeJS.ProcessEnv) => string;
	resolveReleaseVersion: (options?: {
		env?: NodeJS.ProcessEnv;
		repoRoot?: string;
		getExactTag?: (repoRoot?: string) => string;
	}) => string | null;
};

test('normalizeReleaseVersion strips tag prefixes', () => {
	assert.equal(normalizeReleaseVersion('v1.2.3'), '1.2.3');
	assert.equal(normalizeReleaseVersion('refs/tags/v2.3.4'), '2.3.4');
});

test('normalizeReleaseVersion rejects invalid values', () => {
	assert.throws(
		() => normalizeReleaseVersion('release-1.2.3'),
		/stable major\.minor\.patch version/
	);
	assert.throws(
		() => normalizeReleaseVersion('v1.2.3-rc.1'),
		/stable major\.minor\.patch version/
	);
	assert.throws(
		() => normalizeReleaseVersion('v1.2.3-tagverify'),
		/stable major\.minor\.patch version/
	);
});

test('releaseTagFromEnvironment prefers an explicit override', () => {
	assert.equal(releaseTagFromEnvironment({
		OBSTUDIO_EXTENSION_VERSION: 'v3.4.5',
		GITHUB_REF_TYPE: 'tag',
		GITHUB_REF_NAME: 'v9.9.9',
	}), 'v3.4.5');
});

test('resolveReleaseVersion uses GitHub tag metadata when available', () => {
	assert.equal(resolveReleaseVersion({
		env: {
			GITHUB_REF_TYPE: 'tag',
			GITHUB_REF_NAME: 'v4.5.6',
		},
		getExactTag: () => {
			throw new Error('git fallback should not be called');
		},
	}), '4.5.6');
});

test('resolveReleaseVersion falls back to the exact git tag', () => {
	assert.equal(resolveReleaseVersion({
		env: {},
		getExactTag: () => 'v5.6.7',
	}), '5.6.7');
});

test('resolveReleaseVersion returns null when there is no release tag', () => {
	assert.equal(resolveReleaseVersion({
		env: {},
		getExactTag: () => '',
	}), null);
});

test('buildVsceArgs adds release-version flags only when needed', () => {
	assert.deepEqual(
		buildVsceArgs({ releaseVersion: '1.2.3', extraArgs: ['--no-dependencies'] }),
		['package', '1.2.3', '--no-git-tag-version', '--no-update-package-json', '--no-dependencies'],
	);
	assert.deepEqual(
		buildVsceArgs({ releaseVersion: null, extraArgs: ['--no-dependencies'] }),
		['package', '--no-dependencies'],
	);
});
