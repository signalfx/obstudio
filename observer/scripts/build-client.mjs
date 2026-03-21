import { context, build } from "esbuild";
import http from "node:http";
import path from "node:path";
import { fileURLToPath } from "node:url";

const args = process.argv.slice(2);
const watch = args.includes("--watch");
const outdirIndex = args.indexOf("--outdir");

if (outdirIndex === -1 || outdirIndex === args.length - 1) {
  console.error("Expected --outdir <path>.");
  process.exit(1);
}

const currentDir = path.dirname(fileURLToPath(import.meta.url));
const projectRoot = path.resolve(currentDir, "..");
const outdir = path.resolve(projectRoot, args[outdirIndex + 1]);
const liveReloadPort = Number(process.env.PORT ?? 3000);

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
  absWorkingDir: projectRoot,
  bundle: true,
  entryPoints: ["client/src/main.tsx"],
  format: "esm",
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
  console.log(`Built client assets to ${outdir}`);
}
