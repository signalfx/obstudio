import { createWriteStream, existsSync, mkdirSync, mkdtempSync, readdirSync, rmSync } from "node:fs";
import { finished } from "node:stream/promises";
import { Readable } from "node:stream";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { createRequire } from "node:module";
import { execFileSync } from "node:child_process";

const releaseTag = process.env.OTEL_PROTO_RELEASE ?? "v1.9.0";
const archiveUrl = `https://github.com/open-telemetry/opentelemetry-proto/archive/refs/tags/${releaseTag}.tar.gz`;

const require = createRequire(import.meta.url);
const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(scriptDir, "..");
const outputDir = path.join(repoRoot, "shared", "otlp");
const tempRoot = mkdtempSync(path.join(tmpdir(), "observer-otlp-"));

try {
  const archivePath = path.join(tempRoot, `opentelemetry-proto-${releaseTag}.tar.gz`);

  console.log(`Downloading ${archiveUrl}`);
  await downloadFile(archiveUrl, archivePath);

  console.log(`Extracting ${archivePath}`);
  execFileSync("tar", ["-xzf", archivePath, "-C", tempRoot], { stdio: "inherit" });

  const extractedDir = findExtractedDirectory(tempRoot);
  const protoSourceRoot = path.join(extractedDir, "opentelemetry", "proto");
  const protoFiles = collectProtoFiles(protoSourceRoot, extractedDir);

  if (protoFiles.length === 0) {
    throw new Error(`No .proto files found in ${protoSourceRoot}`);
  }

  rmSync(outputDir, { recursive: true, force: true });
  mkdirSync(outputDir, { recursive: true });

  const protocPath = resolveBin("grpc_tools_node_protoc");
  const tsProtoPluginPath = resolveBin("protoc-gen-ts_proto");
  const includeArgs = buildIncludeArgs();

  console.log(`Generating TypeScript bindings into ${outputDir}`);
  execFileSync(
    protocPath,
    [
      `--plugin=protoc-gen-ts_proto=${tsProtoPluginPath}`,
      `--proto_path=${extractedDir}`,
      ...includeArgs,
      `--ts_proto_out=${outputDir}`,
      "--ts_proto_opt=esModuleInterop=true,forceLong=string,oneof=unions,outputEncodeMethods=false,outputJsonMethods=false,outputClientImpl=false,outputServices=none,exportCommonSymbols=false,useOptionals=messages",
      ...protoFiles,
    ],
    {
      cwd: extractedDir,
      stdio: "inherit",
    },
  );
} finally {
  rmSync(tempRoot, { recursive: true, force: true });
}

function findExtractedDirectory(directory) {
  const child = readdirSync(directory, { withFileTypes: true }).find(
    (entry) => entry.isDirectory() && entry.name.startsWith("opentelemetry-proto-"),
  );

  if (child === undefined) {
    throw new Error(`Could not find extracted release directory in ${directory}`);
  }

  return path.join(directory, child.name);
}

function collectProtoFiles(searchRoot, pathRoot) {
  if (!existsSync(searchRoot)) {
    throw new Error(`Missing proto source directory: ${searchRoot}`);
  }

  const queue = [searchRoot];
  const files = [];

  while (queue.length > 0) {
    const currentDirectory = queue.pop();
    const entries = readdirSync(currentDirectory, { withFileTypes: true });

    for (const entry of entries) {
      const resolvedPath = path.join(currentDirectory, entry.name);

      if (entry.isDirectory()) {
        queue.push(resolvedPath);
        continue;
      }

      if (entry.isFile() && entry.name.endsWith(".proto")) {
        files.push(path.relative(pathRoot, resolvedPath));
      }
    }
  }

  return files.sort();
}

function buildIncludeArgs() {
  const grpcToolsDirectory = path.dirname(require.resolve("grpc-tools/package.json"));
  const includeCandidates = [
    path.join(grpcToolsDirectory, "deps", "protobuf", "src"),
    path.join(grpcToolsDirectory, "bin"),
  ];

  return includeCandidates.filter(existsSync).map((candidate) => `--proto_path=${candidate}`);
}

function resolveBin(binaryName) {
  const executableName = process.platform === "win32" ? `${binaryName}.cmd` : binaryName;
  return path.join(repoRoot, "node_modules", ".bin", executableName);
}

async function downloadFile(url, destinationPath) {
  const response = await fetch(url);

  if (!response.ok || response.body === null) {
    throw new Error(`Failed to download ${url}: ${response.status} ${response.statusText}`);
  }

  const output = createWriteStream(destinationPath);
  await finished(Readable.fromWeb(response.body).pipe(output));
}
