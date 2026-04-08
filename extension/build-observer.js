const { execFileSync } = require("node:child_process");
const fs = require("node:fs");
const path = require("node:path");

function getBuildPaths(extensionRoot = __dirname) {
	const repoRoot = path.resolve(extensionRoot, "..");
	const observerGoRoot = path.join(repoRoot, "observer-go");
	const observerGoOutDir = path.join(extensionRoot, "dist", "observer-go");
	const observerGoOutBinary = path.join(observerGoOutDir, "obstudio");

	return { repoRoot, observerGoRoot, observerGoOutDir, observerGoOutBinary };
}

function resetObserverOutputDirs(paths) {
	fs.rmSync(paths.observerGoOutDir, { force: true, recursive: true });
	fs.mkdirSync(paths.observerGoOutDir, { recursive: true });
}

function stageSkills(paths) {
	console.log("Staging embedded skills via Go...");
	execFileSync("go", ["run", "./cmd/stage-skills"], {
		cwd: paths.observerGoRoot,
		stdio: "inherit",
	});
	console.log("Skills staged.");
}

function buildClientAssets(paths) {
	const assetsDir = path.join(paths.observerGoRoot, "internal", "web", "static", "assets");
	if (fs.existsSync(path.join(assetsDir, "main.js"))) {
		console.log("Client assets already built, skipping...");
		return;
	}

	// Use the Go client builder (cmd/build-client) which uses esbuild's Go API.
	// No npm/Node.js required — only the Go toolchain.
	console.log("Building client assets via Go...");
	execFileSync("go", ["run", "./cmd/build-client"], {
		cwd: paths.observerGoRoot,
		stdio: "inherit",
	});
	console.log("Client assets built.");
}

function buildObserverGo(paths) {
	console.log("Building observer-go binary...");

	execFileSync("go", ["build", "-o", paths.observerGoOutBinary, "./cmd/obstudio"], {
		cwd: paths.observerGoRoot,
		stdio: "inherit",
	});

	fs.chmodSync(paths.observerGoOutBinary, 0o755);
	console.log(`Built observer-go binary to ${paths.observerGoOutBinary}`);
}

if (require.main === module) {
	(async () => {
		const paths = getBuildPaths();
		resetObserverOutputDirs(paths);
		stageSkills(paths);
		buildClientAssets(paths);
		buildObserverGo(paths);
	})().catch((error) => {
		console.error(error);
		process.exit(1);
	});
}

module.exports = { getBuildPaths, resetObserverOutputDirs, stageSkills, buildClientAssets, buildObserverGo };
