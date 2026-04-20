import { context, build } from "esbuild";
import fs from "node:fs/promises";
import http from "node:http";
import path from "node:path";
import { fileURLToPath } from "node:url";

const args = process.argv.slice(2);
const watch = args.includes("--watch");
const outdirIndex = args.indexOf("--outdir");
if (outdirIndex !== -1 && outdirIndex === args.length - 1) {
  console.error("Expected --outdir <path>.");
  process.exit(1);
}
const currentDir = path.dirname(fileURLToPath(import.meta.url));
const clientRoot = path.resolve(currentDir, "..");
const goStaticDir = path.resolve(clientRoot, "../internal/web/static/assets");
const defaultOutdir = goStaticDir;
const outdir = outdirIndex === -1
  ? defaultOutdir
  : path.resolve(clientRoot, args[outdirIndex + 1]);
const liveReloadPort = Number(process.env.PORT ?? 3000);

const copyPublicAssets = async () => {
  const publicDir = path.resolve(clientRoot, "public");
  const entries = await fs.readdir(publicDir, { withFileTypes: true });
  await Promise.all(
    entries
      .filter((entry) => entry.isFile() && entry.name !== "index.html")
      .map((entry) => fs.copyFile(path.join(publicDir, entry.name), path.join(outdir, entry.name))),
  );
};

const triggerLiveReload = async () => {
  await new Promise((resolve) => {
    const request = http.request(
      {
        host: "127.0.0.1",
        method: "POST",
        path: "/__live-reload/trigger",
        port: liveReloadPort
      },
      (response) => {
        response.resume();
        response.on("end", resolve);
      },
    );

    request.on("error", () => {
      resolve(undefined);
    });

    request.end();
  });
};

const options = {
  absWorkingDir: clientRoot,
  bundle: true,
  entryPoints: ["src/main.tsx"],
  format: "iife",
  jsx: "automatic",
  loader: {
    ".css": "css"
  },
  outdir,
  platform: "browser",
  plugins: [
    {
      name: "live-reload-signal",
      setup(buildContext) {
        buildContext.onEnd(async (result) => {
          if (watch && result.errors.length === 0) {
            await copyPublicAssets();
            await triggerLiveReload();
          }
        });
      }
    }
  ],
  sourcemap: true,
  target: ["es2022"]
};

if (watch) {
  const ctx = await context(options);
  await ctx.watch();
  console.log(`Watching client files; writing assets to ${outdir}`);
} else {
  await build(options);
  await copyPublicAssets();
  console.log(`Built client assets to ${outdir}`);
}
