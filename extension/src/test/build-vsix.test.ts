import * as assert from 'node:assert/strict';
import test from 'node:test';

const {
	buildVsceArgs,
	normalizeReleaseVersion,
	MARKETPLACE_BASE_CONTENT_URL,
	MARKETPLACE_BASE_IMAGES_URL,
	releaseTagFromEnvironment,
	resolveReleaseVersion,
} = require('../../build-vsix.js') as {
	buildVsceArgs: (options?: { releaseVersion?: string | null; extraArgs?: string[] }) => string[];
	MARKETPLACE_BASE_CONTENT_URL: string;
	MARKETPLACE_BASE_IMAGES_URL: string;
	normalizeReleaseVersion: (value: string) => string;
	releaseTagFromEnvironment: (env?: NodeJS.ProcessEnv) => string;
	resolveReleaseVersion: (options?: {
		env?: NodeJS.ProcessEnv;
		repoRoot?: string;
		getExactTag?: (repoRoot?: string) => string;
	}) => string | null;
};

test('normalizeReleaseVersion strips tag prefixes and extracts the stable core from suffixed tags', () => {
	assert.equal(normalizeReleaseVersion('v1.2.3'), '1.2.3');
	assert.equal(normalizeReleaseVersion('refs/tags/v2.3.4'), '2.3.4');
	assert.equal(normalizeReleaseVersion('v3.4.5-dev'), '3.4.5');
	assert.equal(normalizeReleaseVersion('refs/tags/v4.5.6-dev'), '4.5.6');
	assert.equal(normalizeReleaseVersion('v5.6.7-test'), '5.6.7');
	assert.equal(normalizeReleaseVersion('v6.7.8_tagverify'), '6.7.8');
	assert.equal(normalizeReleaseVersion('v7.8.9+build.1'), '7.8.9');
});

test('normalizeReleaseVersion rejects invalid values', () => {
	assert.throws(
		() => normalizeReleaseVersion('release-1.2.3'),
		/stable major\.minor\.patch version/
	);
	assert.throws(
		() => normalizeReleaseVersion('v1.2'),
		/stable major\.minor\.patch version/
	);
	assert.throws(
		() => normalizeReleaseVersion('vx.y.z'),
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

test('resolveReleaseVersion normalizes suffixed release tags from GitHub metadata', () => {
	assert.equal(resolveReleaseVersion({
		env: {
			GITHUB_REF_TYPE: 'tag',
			GITHUB_REF_NAME: 'v4.5.6-test',
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

test('resolveReleaseVersion normalizes suffixed release tags from the exact git tag', () => {
	assert.equal(resolveReleaseVersion({
		env: {},
		getExactTag: () => 'v5.6.7-preview',
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
		[
			'package',
			'1.2.3',
			'--baseContentUrl',
			MARKETPLACE_BASE_CONTENT_URL,
			'--baseImagesUrl',
			MARKETPLACE_BASE_IMAGES_URL,
			'--no-git-tag-version',
			'--no-update-package-json',
			'--no-dependencies',
		],
	);
	assert.deepEqual(
		buildVsceArgs({ releaseVersion: null, extraArgs: ['--no-dependencies'] }),
		[
			'package',
			'--baseContentUrl',
			MARKETPLACE_BASE_CONTENT_URL,
			'--baseImagesUrl',
			MARKETPLACE_BASE_IMAGES_URL,
			'--no-dependencies',
		],
	);
});
