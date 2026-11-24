import React from "react";
import type { RegisteredWorkspace } from "../api/client";

interface RepoSwitcherProps {
  workspaces: RegisteredWorkspace[];
  selected: RegisteredWorkspace | null;
  onSelect: (name: string) => void;
}

/**
 * Picks which registered repo the Explorer shows. It names repos only; the
 * server maps a name back to the root that registered it. Hidden until a
 * second repo registers, since one repo leaves nothing to switch.
 */
export function RepoSwitcher({ workspaces, selected, onSelect }: RepoSwitcherProps): React.ReactElement | null {
  if (workspaces.length < 2 || selected === null) return null;
  return (
    <label className="repo-switcher" title="Repo whose artifacts and services are shown">
      <span className="repo-switcher__label">Repo</span>
      <select
        className="repo-switcher__select"
        value={selected.name}
        onChange={(event) => onSelect(event.target.value)}
      >
        {workspaces.map((repo) => (
          <option key={repo.name} value={repo.name}>{repo.name}</option>
        ))}
      </select>
    </label>
  );
}
