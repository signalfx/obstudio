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
		external: [
			"@duckdb/node-bindings",
			"@duckdb/node-bindings-darwin-arm64",
			"@duckdb/node-bindings-darwin-x64",
			"@duckdb/node-bindings-linux-arm64",
			"@duckdb/node-bindings-linux-x64",
			"@duckdb/node-bindings-win32-arm64",
			"@duckdb/node-bindings-win32-x64",
		],
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

function copyObserverSql() {
	const sqlSrc = path.join(observerRoot, "server", "src", "sql");
	const sqlDest = path.join(observerOutDir, "sql");
	fs.mkdirSync(sqlDest, { recursive: true });
	for (const file of fs.readdirSync(sqlSrc)) {
		if (file.endsWith(".sql")) {
			fs.copyFileSync(path.join(sqlSrc, file), path.join(sqlDest, file));
		}
	}
}

function copyDuckDBNativeBindings() {
	const nodeModules = path.join(observerRoot, "node_modules");
	const bindings = ["@duckdb/node-bindings", "@duckdb/node-bindings-darwin-arm64", "@duckdb/node-bindings-darwin-x64", "@duckdb/node-bindings-linux-arm64", "@duckdb/node-bindings-linux-x64", "@duckdb/node-bindings-win32-arm64", "@duckdb/node-bindings-win32-x64"];
	for (const pkg of bindings) {
		const srcDir = path.join(nodeModules, pkg);
		if (!fs.existsSync(srcDir)) continue;
		const destDir = path.join(observerOutDir, "node_modules", pkg);
		fs.mkdirSync(destDir, { recursive: true });
		for (const file of fs.readdirSync(srcDir)) {
			const srcFile = path.join(srcDir, file);
			if (fs.statSync(srcFile).isFile()) {
				fs.copyFileSync(srcFile, path.join(destDir, file));
			}
		}
	}
}

async function main() {
	fs.rmSync(observerOutDir, { force: true, recursive: true });
	fs.mkdirSync(observerAssetsDir, { recursive: true });

	await buildObserverServer();
	await buildObserverClient();
	copyObserverHtml();
	copyObserverSql();
	copyDuckDBNativeBindings();
}

main().catch((error) => {
	console.error(error);
	process.exit(1);
});
