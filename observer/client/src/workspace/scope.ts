import { useEffect, useRef, useState } from "react";
import type { RegisteredWorkspace } from "../api/client";
import type { FilterClause } from "../FilterBar";

/** How a repo's service was found, which decides what the telemetry tabs show. */
export type RepoServiceSource = "audit" | "folder" | "none";

export interface RepoService {
  /** service.name the telemetry tabs are scoped to, or null to show everything. */
  service: string | null;
  source: RepoServiceSource;
}

/**
 * Maps a repo to the one service its telemetry comes from. The audit's
 * meta.service_name wins. Without an audit, a service named like the repo
 * folder is assumed to be it, and otherwise nothing is filtered.
 */
export function resolveRepoService(repo: RegisteredWorkspace, telemetryServices: readonly string[]): RepoService {
  if (repo.service) return { service: repo.service, source: "audit" };
  if (repo.folder && telemetryServices.includes(repo.folder)) return { service: repo.folder, source: "folder" };
  return { service: null, source: "none" };
}

/** Other registered repos whose telemetry resolves to the same service name. */
export function reposSharingService(
  repo: RegisteredWorkspace,
  service: string | null,
  workspaces: readonly RegisteredWorkspace[],
  telemetryServices: readonly string[],
): string[] {
  if (service === null) return [];
  return workspaces
    .filter((other) => other.name !== repo.name && resolveRepoService(other, telemetryServices).service === service)
    .map((other) => other.name);
}

function scopeClause(key: string, service: string): FilterClause {
  return { key, op: "eq", value: service };
}

function isScopeClause(clause: FilterClause, key: string, service: string | null | undefined): boolean {
  return service != null && clause.key === key && clause.op === "eq" && clause.value === service;
}

/**
 * Filter clauses for a telemetry tab, starting with a "<field> = <repo
 * service>" chip for the selected repo. The chip is an ordinary clause, so it
 * filters through the same path as one the user adds and can be removed to see
 * every service. Switching repos swaps only that chip and keeps the user's own.
 * key is the tab's filter field for the service (Traces matches any span).
 */
export function useScopedClauses(
  scopeService: string | null | undefined,
  key = "serviceName",
): [FilterClause[], (next: FilterClause[]) => void] {
  const [clauses, setClauses] = useState<FilterClause[]>(() => (scopeService ? [scopeClause(key, scopeService)] : []));
  const appliedRef = useRef(scopeService);

  useEffect(() => {
    const previous = appliedRef.current;
    if (previous === scopeService) return;
    appliedRef.current = scopeService;
    setClauses((current) => {
      const rest = current.filter((clause) => !isScopeClause(clause, key, previous) && !isScopeClause(clause, key, scopeService));
      return scopeService ? [scopeClause(key, scopeService), ...rest] : rest;
    });
  }, [scopeService, key]);

  return [clauses, setClauses];
}
