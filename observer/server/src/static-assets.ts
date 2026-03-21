import express from "express";
import fs from "node:fs";
import path from "node:path";

type StaticAssetOptions = {
  isDev: boolean;
  liveReloadScript: string;
  publicDir: string;
};

export function registerStaticAssets(
  app: express.Express,
  { isDev, liveReloadScript, publicDir }: StaticAssetOptions,
): void {
  app.use(express.static(publicDir, { index: false }));

  app.use((request, response, next) => {
    if (request.method !== "GET") {
      next();
      return;
    }

    if (request.path.startsWith("/assets/") || path.extname(request.path) !== "") {
      next();
      return;
    }

    response.type("html").send(renderIndexHtml(publicDir, isDev, liveReloadScript));
  });
}

function renderIndexHtml(publicDir: string, isDev: boolean, liveReloadScript: string): string {
  const htmlPath = path.join(publicDir, "index.html");
  const html = fs.readFileSync(htmlPath, "utf8");

  if (!isDev) {
    return html;
  }

  return html.replace("</body>", `${liveReloadScript}</body>`);
}
