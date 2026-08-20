import React from "react";

interface EmptyStateProps {
  title: string;
  hint: string;
}

export function EmptyState({ title, hint }: EmptyStateProps): React.ReactElement {
  return (
    <p className="explorer__status explorer__status--empty">
      <span className="empty-state__title">{title}</span>
      <span className="empty-state__hint">{hint}</span>
    </p>
  );
}
