const { execFileSync } = require("node:child_process");
const fs = require("node:fs");
const path = require("node:path");

function normalizeGoos(platform) {
	if (platform === "win32") {
		return "windows";
	}
	return platform;
}

function normalizeGoarch(arch) {
	if (arch === "x64") {
		return "amd64";
	}
	return arch;
}

function observerBinaryName(goos) {
	return goos === "windows" ? "obstudio.exe" : "obstudio";
}

function resolveBuildTarget(env = process.env) {
	const goos = env.OBSTUDIO_GOOS || normalizeGoos(process.platform);
	const goarch = env.OBSTUDIO_GOARCH || normalizeGoarch(process.arch);
	const binaryName = env.OBSTUDIO_OBSERVER_BINARY_NAME || observerBinaryName(goos);

	return { binaryName, goarch, goos };
}

function getBuildPaths(extensionRoot = __dirname, env = process.env) {
	const repoRoot = path.resolve(extensionRoot, "..");
	const observerRoot = path.join(repoRoot, "observer");
	const observerOutDir = path.join(extensionRoot, "dist", "observer");
	const target = resolveBuildTarget(env);
	const observerOutBinary = path.join(observerOutDir, target.binaryName);

	return { repoRoot, observerRoot, observerOutDir, observerOutBinary, target };
}

function resetObserverOutputDirs(paths) {
	fs.rmSync(paths.observerOutDir, { force: true, recursive: true });
	fs.mkdirSync(paths.observerOutDir, { recursive: true });
}

function stageSkills(paths) {
	console.log("Staging embedded skills via Go...");
	execFileSync("go", ["run", "./cmd/stage-skills"], {
		cwd: paths.observerRoot,
		stdio: "inherit",
	});
	console.log("Skills staged.");
}

function buildClientAssets(paths) {
	const assetsDir = path.join(paths.observerRoot, "internal", "web", "static", "assets");
	if (fs.existsSync(path.join(assetsDir, "main.js"))) {
		console.log("Client assets already built, skipping...");
		return;
	}

	// Use the Go client builder (cmd/build-client) which uses esbuild's Go API.
	// No npm/Node.js required — only the Go toolchain.
	console.log("Building client assets via Go...");
	execFileSync("go", ["run", "./cmd/build-client"], {
		cwd: paths.observerRoot,
		stdio: "inherit",
	});
	console.log("Client assets built.");
}

function buildObserverGo(paths) {
	console.log("Building observer binary...");

	execFileSync("go", ["build", "-o", paths.observerOutBinary, "./cmd/obstudio"], {
		cwd: paths.observerRoot,
		env: {
			...process.env,
			GOARCH: paths.target.goarch,
			GOOS: paths.target.goos,
		},
		stdio: "inherit",
	});

	fs.chmodSync(paths.observerOutBinary, 0o755);
	console.log(`Built observer binary to ${paths.observerOutBinary}`);
}

function bundleWeaverRuntime(paths) {
	console.log("Bundling Weaver validator runtime...");

	execFileSync("go", [
		"run",
		"./cmd/fetch-weaver",
		"-goos",
		paths.target.goos,
		"-goarch",
		paths.target.goarch,
		"-output",
		paths.observerOutDir,
	], {
		cwd: paths.observerRoot,
		stdio: "inherit",
	});

	console.log(`Bundled Weaver runtime into ${paths.observerOutDir}`);
}

if (require.main === module) {
	(async () => {
		const paths = getBuildPaths();
		resetObserverOutputDirs(paths);
		stageSkills(paths);
		buildClientAssets(paths);
		buildObserverGo(paths);
		bundleWeaverRuntime(paths);
	})().catch((error) => {
		console.error(error);
		process.exit(1);
	});
}

module.exports = {
	getBuildPaths,
	resolveBuildTarget,
	resetObserverOutputDirs,
	stageSkills,
	buildClientAssets,
	buildObserverGo,
	bundleWeaverRuntime,
};
