import React from "react";
import type { ValidationSeverity } from "../api/types";

interface ValidationBadgeProps {
  count: number;
  severity: ValidationSeverity | null;
  title?: string;
}

/** Compact badge for showing how many validation findings match an entity. */
export function ValidationBadge({ count, severity, title }: ValidationBadgeProps): React.ReactElement | null {
  if (count <= 0) return null;
  return (
    <span className={`validation-badge validation-badge--${severity ?? "information"}`} title={title ?? `${count} validation findings`}>
      {count}
    </span>
  );
}
