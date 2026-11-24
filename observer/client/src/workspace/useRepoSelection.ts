import { useCallback, useEffect, useState } from "react";
import { fetchWorkspaces, type RegisteredWorkspace, type WorkspaceList } from "../api/client";

/** New repos register whenever a launch attaches, so the list is re-read. */
export const WORKSPACES_REFRESH_MS = 10_000;

const REPO_PARAM = "repo";

export interface RepoSelection {
  /** Registered repos, sorted by name; empty until loaded or on an older server. */
  workspaces: RegisteredWorkspace[];
  /** The repo the Explorer is showing, or null until the list loads. */
  selected: RegisteredWorkspace | null;
  select: (name: string) => void;
}

function initialRepoFromLocation(): string | null {
  if (typeof window === "undefined") return null;
  return new URLSearchParams(window.location.search).get(REPO_PARAM) || null;
}

function writeRepoToLocation(name: string | null): void {
  if (typeof window === "undefined") return;
  const url = new URL(window.location.href);
  if (name) url.searchParams.set(REPO_PARAM, name);
  else url.searchParams.delete(REPO_PARAM);
  window.history.replaceState(window.history.state, "", url);
}

/**
 * The repo switcher's state. Until the user picks a repo it follows the
 * server's active workspace (the most recent launch or focused editor window).
 * A pick is this client's alone: it is kept in ?repo= and sent with each
 * artifact request, so it never changes what another window reads.
 */
export function useRepoSelection(): RepoSelection {
  const [list, setList] = useState<WorkspaceList | null>(null);
  const [chosen, setChosen] = useState<string | null>(() => initialRepoFromLocation());
  const [reloads, setReloads] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    fetchWorkspaces(controller.signal)
      .then((next) => {
        if (!controller.signal.aborted) setList(next);
      })
      .catch(() => {
        // An older server has no registry; the Explorer then reads the
        // default workspace exactly as before.
      });
    return () => controller.abort();
  }, [reloads]);

  useEffect(() => {
    const reload = () => setReloads((n) => n + 1);
    const id = window.setInterval(reload, WORKSPACES_REFRESH_MS);
    window.addEventListener("focus", reload);
    return () => {
      window.clearInterval(id);
      window.removeEventListener("focus", reload);
    };
  }, []);

  const workspaces = list?.workspaces ?? [];
  const chosenRepo = chosen === null ? undefined : workspaces.find((repo) => repo.name === chosen);
  const selected = chosenRepo ?? workspaces.find((repo) => repo.name === list?.active) ?? null;

  // A pick the server no longer knows (it restarted, or the registry dropped
  // the repo) falls back to the active workspace instead of a dead name.
  useEffect(() => {
    if (list !== null && chosen !== null && chosenRepo === undefined) {
      setChosen(null);
      writeRepoToLocation(null);
    }
  }, [list, chosen, chosenRepo]);

  const select = useCallback((name: string) => {
    setChosen(name);
    writeRepoToLocation(name);
  }, []);

  return { workspaces, selected, select };
}
