const esbuild = require("esbuild");
const fs = require("node:fs");
const path = require("node:path");

const extensionRoot = __dirname;
const repoRoot = path.resolve(extensionRoot, "..");
const observerRoot = path.join(repoRoot, "observer");
const observerOutDir = path.join(extensionRoot, "dist", "observer");
const observerPublicDir = path.join(observerOutDir, "public");
const observerAssetsDir = path.join(observerPublicDir, "assets");

async function buildObserverServer() {
	await esbuild.build({
		entryPoints: [path.join(observerRoot, "server", "src", "index.ts")],
		bundle: true,
		format: "cjs",
		logLevel: "info",
		outfile: path.join(observerOutDir, "index.js"),
		platform: "node",
		sourcemap: true,
		target: "node20",
	});
}

async function buildObserverClient() {
	await esbuild.build({
		absWorkingDir: path.join(observerRoot, "client"),
		bundle: true,
		entryPoints: ["src/main.tsx"],
		format: "esm",
		jsx: "automatic",
		loader: {
			".css": "css",
		},
		logLevel: "info",
		outdir: observerAssetsDir,
		platform: "browser",
		sourcemap: true,
		target: ["es2022"],
	});
}

function copyObserverHtml() {
	fs.mkdirSync(observerPublicDir, { recursive: true });
	fs.copyFileSync(
		path.join(observerRoot, "client", "public", "index.html"),
		path.join(observerPublicDir, "index.html"),
	);
}

async function main() {
	fs.rmSync(observerOutDir, { force: true, recursive: true });
	fs.mkdirSync(observerAssetsDir, { recursive: true });

	await buildObserverServer();
	await buildObserverClient();
	copyObserverHtml();
}

main().catch((error) => {
	console.error(error);
	process.exit(1);
});
