import React, { type ReactNode } from "react";

interface DetailPanelProps {
  title: string;
  subtitle?: string;
  onClose: () => void;
  children: ReactNode;
}

/** Closeable side panel for displaying detail views. */
export function DetailPanel({ title, subtitle, onClose, children }: DetailPanelProps): React.ReactElement {
  return (
    <div className="detail-panel">
      <div className="detail-panel__header">
        <div className="detail-panel__titles">
          <h3 className="detail-panel__title">{title}</h3>
          {subtitle ? <span className="detail-panel__subtitle">{subtitle}</span> : null}
        </div>
        <button className="detail-panel__close" onClick={onClose} type="button">
          &times;
        </button>
      </div>
      <div className="detail-panel__body">{children}</div>
    </div>
  );
}
