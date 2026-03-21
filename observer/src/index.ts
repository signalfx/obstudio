import express from "express";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const app = express();
const port = Number(process.env.PORT ?? 3000);
const currentDir = path.dirname(fileURLToPath(import.meta.url));
const devPublicDir = path.resolve(currentDir, "../public");
const builtPublicDir = path.join(currentDir, "public");
const publicDir = fs.existsSync(builtPublicDir) ? builtPublicDir : devPublicDir;

app.use(express.static(publicDir));

app.use((request, response, next) => {
  if (request.method !== "GET") {
    next();
    return;
  }

  if (request.path.startsWith("/assets/") || path.extname(request.path) !== "") {
    next();
    return;
  }

  response.sendFile(path.join(publicDir, "index.html"));
});

app.listen(port, () => {
  console.log(`Observer listening on http://localhost:${port}`);
});
