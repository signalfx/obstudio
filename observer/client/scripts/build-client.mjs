import { context, build } from "esbuild";
import fs from "node:fs/promises";
import http from "node:http";
import os from "node:os";
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
// Resolve the shared-observer state file path with the SAME override
// precedence the rest of the system uses (the Go binary and the extension both
// honor OBSTUDIO_SHARED_OBSERVER_STATE_PATH, falling back to the homedir
// default). Reading this file is how every consumer DISCOVERS the UI port the
// binary auto-scanned to — the watcher is just another discovery consumer.
const sharedObserverStatePath = () => {
  const override = process.env.OBSTUDIO_SHARED_OBSERVER_STATE_PATH?.trim();
  return override && override.length > 0
    ? override
    : path.join(os.homedir(), ".obstudio", "shared-observer.json");
};

// Extract the bound UI port by reading shared-observer.json fresh. Returns
// undefined (never throws) if the file is missing/unparseable/has no usable
// port — the binary may not be up yet, or we may be between restarts.
const discoverLiveReloadPort = async () => {
  try {
    const raw = await fs.readFile(sharedObserverStatePath(), "utf8");
    const state = JSON.parse(raw);
    if (typeof state?.baseUrl !== "string" || state.baseUrl.length === 0) {
      return undefined;
    }
    const parsed = new URL(state.baseUrl);
    if (parsed.port.length > 0) {
      return Number(parsed.port);
    }
    if (parsed.protocol === "http:") return 80;
    if (parsed.protocol === "https:") return 443;
    return undefined;
  } catch {
    return undefined;
  }
};

// Resolve the trigger target port. Precedence: an explicit PORT override still
// wins (pinning stays available for advanced cases); otherwise discover the
// autoscanned port from shared-observer.json. Read FRESH each trigger so the
// watcher follows the binary if it restarts on a different port mid-session.
const resolveLiveReloadPort = async () => {
  const pinned = process.env.PORT?.trim();
  if (pinned && pinned.length > 0) {
    const port = Number(pinned);
    if (Number.isFinite(port)) return port;
  }
  return discoverLiveReloadPort();
};

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
  const liveReloadPort = await resolveLiveReloadPort();
  if (liveReloadPort === undefined) {
    // Binary not up yet (or between restarts): skip quietly and let the next
    // rebuild retry. Hot-reload is a convenience; a missing/stale state file
    // must never crash or hang the watcher.
    return;
  }
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
