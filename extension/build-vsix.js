const { execFileSync } = require("node:child_process");
const fs = require("node:fs");
const path = require("node:path");

const MARKETPLACE_VERSION_PATTERN = /^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$/;

function normalizeReleaseVersion(rawVersion) {
	const trimmed = String(rawVersion ?? "").trim();
	if (!trimmed) {
		throw new Error("Release version cannot be empty");
	}

	const withoutRefPrefix = trimmed.startsWith("refs/tags/")
		? trimmed.slice("refs/tags/".length)
		: trimmed;
	const normalized = withoutRefPrefix.replace(/^v/i, "");
	if (!MARKETPLACE_VERSION_PATTERN.test(normalized)) {
		throw new Error(
			`Release version "${trimmed}" must be a stable major.minor.patch version for VS Code Marketplace`
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

function vsceCommand(extensionRoot = __dirname) {
	const binName = process.platform === "win32" ? "vsce.cmd" : "vsce";
	const command = path.join(extensionRoot, "node_modules", ".bin", binName);
	if (!fs.existsSync(command)) {
		throw new Error(`@vscode/vsce must be installed locally: ${command} not found`);
	}
	return command;
}

function buildVsceArgs({ releaseVersion = null, extraArgs = [] } = {}) {
	const args = ["package"];
	if (releaseVersion) {
		args.push(releaseVersion, "--no-git-tag-version", "--no-update-package-json");
	}
	return args.concat(extraArgs);
}

function packageVsix({
	extensionRoot = __dirname,
	env = process.env,
	extraArgs = [],
} = {}) {
	const releaseVersion = resolveReleaseVersion({
		env,
		repoRoot: path.resolve(extensionRoot, ".."),
	});
	const output = execFileSync(vsceCommand(extensionRoot), buildVsceArgs({
		releaseVersion,
		extraArgs,
	}), {
		cwd: extensionRoot,
		env,
		encoding: "utf-8",
		stdio: ["ignore", "pipe", "pipe"],
	});

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
	buildVsceArgs,
	gitExactTag,
	normalizeReleaseVersion,
	packageVsix,
	releaseTagFromEnvironment,
	resolveReleaseVersion,
	vsceCommand,
};
