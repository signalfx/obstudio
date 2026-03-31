import { execFile } from "node:child_process";
import { promisify } from "node:util";
import type http from "node:http";
import { evictConnection as evictDuckDBConnection } from "./duckdb-store.js";

const execFileAsync = promisify(execFile);
const trackedHttpConnectionsByAddress = new Map<string, string>();
const trackedHttpConnections = new Map<string, { addressKey: string; pid: number }>();
const trackedHttpConnectionIdsByPid = new Map<number, Set<string>>();
const trackedHttpPidWatchers = new Map<number, NodeJS.Timeout>();
let nextHttpConnectionId = 1;

type SocketTuple = {
  localAddress: string;
  localPort: number;
  remoteAddress: string;
  remotePort: number;
};

type LsofRecord = {
  name?: string;
  pid?: number;
};

export async function resolveHttpConnectionId(request: http.IncomingMessage): Promise<string | undefined> {
  const socketTuple = getSocketTuple(request.socket);
  if (socketTuple === null) {
    return undefined;
  }

  const addressKey = getAddressKey(socketTuple);
  const existingConnectionId = trackedHttpConnectionsByAddress.get(addressKey);
  if (existingConnectionId !== undefined) {
    return existingConnectionId;
  }

  const pid = await findOriginatingPid(socketTuple);
  if (pid === undefined) {
    return undefined;
  }

  const connectionId = `http-${nextHttpConnectionId++}`;
  trackedHttpConnectionsByAddress.set(addressKey, connectionId);
  trackedHttpConnections.set(connectionId, { addressKey, pid });
  const trackedConnectionsForPid = trackedHttpConnectionIdsByPid.get(pid) ?? new Set<string>();
  trackedConnectionsForPid.add(connectionId);
  trackedHttpConnectionIdsByPid.set(pid, trackedConnectionsForPid);
  ensurePidWatcher(pid);
  return connectionId;
}

function ensurePidWatcher(pid: number): void {
  if (trackedHttpPidWatchers.has(pid)) {
    return;
  }

  const timer = setInterval(() => {
    if (doesProcessExist(pid)) {
      return;
    }

    const connectionIds = trackedHttpConnectionIdsByPid.get(pid);
    if (connectionIds !== undefined) {
      for (const connectionId of connectionIds) {
        evictHttpConnection(connectionId, `pid-exit:${pid}`);
      }
    }

    trackedHttpConnectionIdsByPid.delete(pid);
    const existingTimer = trackedHttpPidWatchers.get(pid);
    if (existingTimer !== undefined) {
      clearInterval(existingTimer);
      trackedHttpPidWatchers.delete(pid);
    }
  }, 1000);
  timer.unref();
  trackedHttpPidWatchers.set(pid, timer);
}

function evictHttpConnection(connectionId: string, reason: string): void {
  const trackedConnection = trackedHttpConnections.get(connectionId);
  if (trackedConnection === undefined) {
    return;
  }

  trackedHttpConnections.delete(connectionId);
  trackedHttpConnectionsByAddress.delete(trackedConnection.addressKey);
  void evictDuckDBConnection(connectionId);
  console.log(`[otlp] evicted http connection ${connectionId} (${reason})`);
}

async function findOriginatingPid(socketTuple: SocketTuple): Promise<number | undefined> {
  const { stdout } = await execFileAsync("lsof", [
    "-nP",
    `-iTCP:${socketTuple.remotePort}`,
    "-sTCP:ESTABLISHED",
    "-Fpcn",
  ]);
  const records = parseLsofRecords(stdout);

  for (const record of records) {
    if (record.pid === undefined || record.name === undefined) {
      continue;
    }

    const connectionName = parseConnectionName(record.name);
    if (connectionName === null) {
      continue;
    }

    if (
      connectionName.localAddress === socketTuple.remoteAddress &&
      connectionName.localPort === socketTuple.remotePort &&
      connectionName.remoteAddress === socketTuple.localAddress &&
      connectionName.remotePort === socketTuple.localPort
    ) {
      return record.pid;
    }
  }

  return undefined;
}

function parseLsofRecords(output: string): LsofRecord[] {
  const lines = output.split(/\r?\n/);
  const records: LsofRecord[] = [];
  let currentRecord: LsofRecord = {};

  for (const line of lines) {
    if (line === "") {
      continue;
    }

    const prefix = line[0];
    const value = line.slice(1);

    if (prefix === "p") {
      if (currentRecord.pid !== undefined || currentRecord.name !== undefined) {
        records.push(currentRecord);
      }
      currentRecord = { pid: Number(value) };
      continue;
    }

    if (prefix === "n") {
      currentRecord.name = value;
    }
  }

  if (currentRecord.pid !== undefined || currentRecord.name !== undefined) {
    records.push(currentRecord);
  }

  return records;
}

function parseConnectionName(name: string): SocketTuple | null {
  const [localEndpoint, remoteEndpoint] = name.split("->");
  if (remoteEndpoint === undefined) {
    return null;
  }

  const local = parseEndpoint(localEndpoint);
  const remote = parseEndpoint(remoteEndpoint);
  if (local === null || remote === null) {
    return null;
  }

  return {
    localAddress: local.address,
    localPort: local.port,
    remoteAddress: remote.address,
    remotePort: remote.port,
  };
}

function parseEndpoint(endpoint: string): { address: string; port: number } | null {
  const normalizedEndpoint = endpoint.trim();
  if (normalizedEndpoint.startsWith("[")) {
    const match = normalizedEndpoint.match(/^\[([^\]]+)\]:(\d+)$/);
    if (match === null) {
      return null;
    }

    return {
      address: normalizeLoopbackAddress(match[1]),
      port: Number(match[2]),
    };
  }

  const separatorIndex = normalizedEndpoint.lastIndexOf(":");
  if (separatorIndex < 0) {
    return null;
  }

  return {
    address: normalizeLoopbackAddress(normalizedEndpoint.slice(0, separatorIndex)),
    port: Number(normalizedEndpoint.slice(separatorIndex + 1)),
  };
}

function getSocketTuple(socket: http.IncomingMessage["socket"]): SocketTuple | null {
  if (
    socket.localAddress === undefined ||
    socket.localPort === undefined ||
    socket.remoteAddress === undefined ||
    socket.remotePort === undefined
  ) {
    return null;
  }

  return {
    localAddress: normalizeLoopbackAddress(socket.localAddress),
    localPort: socket.localPort,
    remoteAddress: normalizeLoopbackAddress(socket.remoteAddress),
    remotePort: socket.remotePort,
  };
}

function normalizeLoopbackAddress(address: string): string {
  return address.startsWith("::ffff:") ? address.slice("::ffff:".length) : address;
}

function getAddressKey(socketTuple: SocketTuple): string {
  return [
    socketTuple.remoteAddress,
    socketTuple.remotePort,
    socketTuple.localAddress,
    socketTuple.localPort,
  ].join("|");
}

function doesProcessExist(pid: number): boolean {
  try {
    process.kill(pid, 0);
    return true;
  } catch (error) {
    if (!(error instanceof Error) || !("code" in error)) {
      return false;
    }

    return error.code === "EPERM";
  }
}
