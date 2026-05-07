const { execFileSync } = require("node:child_process");
const fs = require("node:fs");
const path = require("node:path");

const MARKETPLACE_VERSION_PATTERN = /^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$/;
const SUFFIXED_TAG_VERSION_PATTERN = /^((0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*))(?:$|[^\d].*)/;
const REPOSITORY_ROOT_URL = "https://github.com/signalfx/obstudio";
const EXTENSION_SUBDIRECTORY = "extension";
const MARKETPLACE_BASE_CONTENT_URL = `${REPOSITORY_ROOT_URL}/blob/main/${EXTENSION_SUBDIRECTORY}`;
const MARKETPLACE_BASE_IMAGES_URL = `${REPOSITORY_ROOT_URL}/raw/main/${EXTENSION_SUBDIRECTORY}`;
const SUPPORTED_VSCODE_TARGETS = {
	"darwin-arm64": { binaryName: "obstudio", goarch: "arm64", goos: "darwin" },
	"darwin-x64": { binaryName: "obstudio", goarch: "amd64", goos: "darwin" },
	"linux-x64": { binaryName: "obstudio", goarch: "amd64", goos: "linux" },
	"win32-x64": { binaryName: "obstudio.exe", goarch: "amd64", goos: "windows" },
};

function normalizeReleaseVersion(rawVersion) {
	const trimmed = String(rawVersion ?? "").trim();
	if (!trimmed) {
		throw new Error("Release version cannot be empty");
	}

	const withoutRefPrefix = trimmed.startsWith("refs/tags/")
		? trimmed.slice("refs/tags/".length)
		: trimmed;
	const normalized = withoutRefPrefix.replace(/^v/i, "");
	const suffixedTagMatch = normalized.match(SUFFIXED_TAG_VERSION_PATTERN);
	if (suffixedTagMatch) {
		return suffixedTagMatch[1];
	}
	if (!MARKETPLACE_VERSION_PATTERN.test(normalized)) {
		throw new Error(
			`Release version "${trimmed}" must resolve to a stable major.minor.patch version for VS Code Marketplace packaging`
		);
	}

	return normalized;
}

function releaseTagFromEnvironment(env = process.env) {
	if (env.OBSTUDIO_EXTENSION_VERSION) {
		return env.OBSTUDIO_EXTENSION_VERSION;
	}
	if (env.GITHUB_REF_TYPE === "tag" && env.GITHUB_REF_NAME) {
		return env.GITHUB_REF_NAME;
	}
	if (env.GITHUB_REF && env.GITHUB_REF.startsWith("refs/tags/")) {
		return env.GITHUB_REF.slice("refs/tags/".length);
	}
	return "";
}

function gitExactTag(repoRoot = path.resolve(__dirname, "..")) {
	try {
		return execFileSync("git", ["describe", "--tags", "--exact-match"], {
			cwd: repoRoot,
			encoding: "utf-8",
			stdio: ["ignore", "pipe", "ignore"],
		}).trim();
	} catch {
		return "";
	}
}

function resolveReleaseVersion({
	env = process.env,
	repoRoot = path.resolve(__dirname, ".."),
	getExactTag = gitExactTag,
} = {}) {
	const envTag = releaseTagFromEnvironment(env);
	if (envTag) {
		return normalizeReleaseVersion(envTag);
	}

	const gitTag = getExactTag(repoRoot);
	if (!gitTag) {
		return null;
	}

	return normalizeReleaseVersion(gitTag);
}

function parseVsceTarget(extraArgs = []) {
	for (let index = 0; index < extraArgs.length; index += 1) {
		const value = extraArgs[index];
		if (value === "--target") {
			return extraArgs[index + 1] ?? null;
		}
		if (value.startsWith("--target=")) {
			return value.slice("--target=".length);
		}
	}
	return null;
}

function resolveVsceTarget(target) {
	if (target === null || target === undefined || target === "") {
		return null;
	}
	const resolved = SUPPORTED_VSCODE_TARGETS[target];
	if (!resolved) {
		throw new Error(
			`Unsupported VS Code target "${target}". Supported targets: ${Object.keys(SUPPORTED_VSCODE_TARGETS).join(", ")}`
		);
	}
	return resolved;
}

function buildObserverEnvironment(env = process.env, target = null) {
	const resolved = resolveVsceTarget(target);
	if (!resolved) {
		return env;
	}
	return {
		...env,
		OBSTUDIO_GOARCH: resolved.goarch,
		OBSTUDIO_GOOS: resolved.goos,
		OBSTUDIO_OBSERVER_BINARY_NAME: resolved.binaryName,
		OBSTUDIO_VSCODE_TARGET: target,
	};
}

function vsceCommand(extensionRoot = __dirname) {
	const binName = process.platform === "win32" ? "vsce.cmd" : "vsce";
	const command = path.join(extensionRoot, "node_modules", ".bin", binName);
	if (!fs.existsSync(command)) {
		throw new Error(`@vscode/vsce must be installed locally: ${command} not found`);
	}
	return command;
}

function buildVsceArgs({ releaseVersion = null, extraArgs = [] } = {}) {
	const args = [
		"package",
		"--baseContentUrl",
		MARKETPLACE_BASE_CONTENT_URL,
		"--baseImagesUrl",
		MARKETPLACE_BASE_IMAGES_URL,
	];
	if (releaseVersion) {
		args.splice(1, 0, releaseVersion);
		args.push("--no-git-tag-version", "--no-update-package-json");
	}
	return args.concat(extraArgs);
}

function vsceExecOptions({
	cwd,
	env,
} = {}) {
	return {
		cwd,
		env,
		encoding: "utf-8",
		shell: process.platform === "win32",
		stdio: ["ignore", "pipe", "pipe"],
	};
}

function packageVsix({
	extensionRoot = __dirname,
	env = process.env,
	extraArgs = [],
} = {}) {
	const target = parseVsceTarget(extraArgs);
	const releaseVersion = resolveReleaseVersion({
		env,
		repoRoot: path.resolve(extensionRoot, ".."),
	});
	const output = execFileSync(vsceCommand(extensionRoot), buildVsceArgs({
		releaseVersion,
		extraArgs,
	}), vsceExecOptions({
		cwd: extensionRoot,
		env: buildObserverEnvironment(env, target),
	}));

	return { output, releaseVersion };
}

if (require.main === module) {
	try {
		const { output, releaseVersion } = packageVsix({
			extraArgs: process.argv.slice(2),
		});
		if (releaseVersion) {
			process.stdout.write(`Packaging VSIX with release version ${releaseVersion}\n`);
		}
		process.stdout.write(output);
	} catch (error) {
		if (error && typeof error === "object") {
			if ("stdout" in error && typeof error.stdout === "string" && error.stdout) {
				process.stdout.write(error.stdout);
			}
			if ("stderr" in error && typeof error.stderr === "string" && error.stderr) {
				process.stderr.write(error.stderr);
			}
		}
		console.error(error);
		process.exit(1);
	}
}

module.exports = {
	buildObserverEnvironment,
	buildVsceArgs,
	gitExactTag,
	MARKETPLACE_BASE_CONTENT_URL,
	MARKETPLACE_BASE_IMAGES_URL,
	normalizeReleaseVersion,
	parseVsceTarget,
	packageVsix,
	releaseTagFromEnvironment,
	resolveReleaseVersion,
	resolveVsceTarget,
	SUPPORTED_VSCODE_TARGETS,
	vsceCommand,
	vsceExecOptions,
};
