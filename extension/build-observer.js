const { execFileSync } = require("node:child_process");
const fs = require("node:fs");
const path = require("node:path");

function getBuildPaths(extensionRoot = __dirname) {
	const repoRoot = path.resolve(extensionRoot, "..");
	const observerRoot = path.join(repoRoot, "observer");
	const observerOutDir = path.join(extensionRoot, "dist", "observer");
	const observerOutBinary = path.join(observerOutDir, "obstudio");

	return { repoRoot, observerRoot, observerOutDir, observerOutBinary };
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
		stdio: "inherit",
	});

	fs.chmodSync(paths.observerOutBinary, 0o755);
	console.log(`Built observer binary to ${paths.observerOutBinary}`);
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
