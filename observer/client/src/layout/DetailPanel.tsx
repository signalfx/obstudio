import React, { type ReactNode, useEffect, useRef } from "react";

interface DetailPanelProps {
  title?: string;
  subtitle?: string;
  headerMode?: "default" | "close-only";
  onClose: () => void;
  children: ReactNode;
}

/** Closeable side panel for displaying detail views. */
export function DetailPanel({
  title,
  subtitle,
  headerMode = "default",
  onClose,
  children,
}: DetailPanelProps): React.ReactElement {
  const bodyRef = useRef<HTMLDivElement>(null);
  const showTitles = headerMode === "default" && Boolean(title || subtitle);

  useEffect(() => {
    bodyRef.current?.scrollTo(0, 0);
  }, [title, subtitle, headerMode]);

  return (
    <div className={headerMode === "close-only" ? "detail-panel detail-panel--close-only" : "detail-panel"}>
      <div className={headerMode === "close-only" ? "detail-panel__header detail-panel__header--close-only" : "detail-panel__header"}>
        {showTitles ? (
          <div className="detail-panel__titles">
            {title ? <h3 className="detail-panel__title">{title}</h3> : null}
            {subtitle ? <span className="detail-panel__subtitle">{subtitle}</span> : null}
          </div>
        ) : null}
        <button className="detail-panel__close" onClick={onClose} type="button" aria-label="Close panel">
          &times;
        </button>
      </div>
      <div ref={bodyRef} className={headerMode === "close-only" ? "detail-panel__body detail-panel__body--close-only" : "detail-panel__body"}>{children}</div>
    </div>
  );
}
