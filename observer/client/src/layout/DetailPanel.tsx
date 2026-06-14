import React, { type ReactNode, useEffect, useRef, useState } from "react";

interface DetailPanelProps {
  title?: string;
  subtitle?: string;
  headerMode?: "default" | "close-only";
  scrollResetKey?: string | number;
  onClose: () => void;
  children: ReactNode;
  footer?: ReactNode;
}

/** Closeable side panel for displaying detail views. */
export function DetailPanel({
  title,
  subtitle,
  headerMode = "default",
  scrollResetKey,
  onClose,
  children,
  footer,
}: DetailPanelProps): React.ReactElement {
  const bodyRef = useRef<HTMLDivElement>(null);
  const showTitles = headerMode === "default" && Boolean(title || subtitle);

  useEffect(() => {
    bodyRef.current?.scrollTo(0, 0);
  }, [title, subtitle, headerMode, scrollResetKey]);

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
      {footer ? <div className="detail-panel__footer">{footer}</div> : null}
    </div>
  );
}

interface ResizablePanelProps {
  children: ReactNode;
  className?: string;
  defaultWidth?: number | string;
  minWidth?: number;
  maxWidth?: number;
  resizeLabel?: string;
  widthVarName?: `--${string}`;
}

export function ResizablePanel({
  children,
  className = "",
  defaultWidth = 560,
  minWidth = 420,
  maxWidth = 860,
  resizeLabel = "Resize panel",
  widthVarName = "--panel-width",
}: ResizablePanelProps): React.ReactElement {
  const [panelWidth, setPanelWidth] = useState<number | string>(defaultWidth);
  const [isResizing, setIsResizing] = useState(false);
  const dragStateRef = useRef<{ startX: number; startWidth: number } | null>(null);
  const panelRef = useRef<HTMLDivElement | null>(null);
  const lastMeasuredWidthRef = useRef<number | null>(null);

  useEffect(() => {
    setPanelWidth(defaultWidth);
  }, [defaultWidth]);

  useEffect(() => {
    const element = panelRef.current;
    if (!element) {
      return undefined;
    }

    const updateMeasuredWidth = () => {
      const width = element.getBoundingClientRect().width;
      if (width > 0) {
        lastMeasuredWidthRef.current = width;
      }
    };

    updateMeasuredWidth();
    if (typeof ResizeObserver === "undefined") {
      return undefined;
    }
    const observer = new ResizeObserver(updateMeasuredWidth);
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    if (!isResizing) {
      return undefined;
    }

    const previousCursor = document.body.style.cursor;
    const previousUserSelect = document.body.style.userSelect;
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";

    const handleMouseMove = (event: MouseEvent) => {
      if (!dragStateRef.current) {
        return;
      }
      const deltaX = event.clientX - dragStateRef.current.startX;
      const nextWidth = Math.min(maxWidth, Math.max(minWidth, dragStateRef.current.startWidth - deltaX));
      setPanelWidth(nextWidth);
    };

    const stopResizing = () => {
      dragStateRef.current = null;
      setIsResizing(false);
    };

    window.addEventListener("mousemove", handleMouseMove);
    window.addEventListener("mouseup", stopResizing);

    return () => {
      document.body.style.cursor = previousCursor;
      document.body.style.userSelect = previousUserSelect;
      window.removeEventListener("mousemove", handleMouseMove);
      window.removeEventListener("mouseup", stopResizing);
    };
  }, [isResizing, maxWidth, minWidth]);

  return (
    <div
      ref={panelRef}
      className={`resizable-panel ${isResizing ? "is-resizing" : ""} ${className}`.trim()}
      style={{ [widthVarName]: typeof panelWidth === "number" ? `${panelWidth}px` : panelWidth } as React.CSSProperties}
    >
      <button
        type="button"
        className="resizable-panel__handle"
        aria-label={resizeLabel}
        onMouseDown={(event) => {
          const measuredWidth = panelRef.current?.getBoundingClientRect().width;
          const fallbackWidth = typeof panelWidth === "number" ? panelWidth : lastMeasuredWidthRef.current ?? maxWidth;
          dragStateRef.current = {
            startX: event.clientX,
            startWidth: measuredWidth && measuredWidth > 0 ? measuredWidth : fallbackWidth,
          };
          setIsResizing(true);
          event.preventDefault();
        }}
      />
      {children}
    </div>
  );
}

interface CopyTextButtonProps {
  text: string;
  label: string;
}

export function CopyTextButton({ text, label }: CopyTextButtonProps): React.ReactElement {
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (!copied) {
      return undefined;
    }
    const timer = window.setTimeout(() => setCopied(false), 1200);
    return () => window.clearTimeout(timer);
  }, [copied]);

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
    } catch {
      setCopied(false);
    }
  };

  return (
    <button
      type="button"
      className={`copy-button ${copied ? "copy-button--copied" : ""}`}
      onClick={() => {
        void handleCopy();
      }}
      aria-label={`Copy ${label}`}
      title={copied ? `${label} copied` : `Copy ${label}`}
    >
      {copied ? (
        <svg viewBox="0 0 16 16" aria-hidden="true" focusable="false">
          <path
            d="M13.2 4.3a.75.75 0 0 1 0 1.06L7.1 11.5a.75.75 0 0 1-1.06 0L2.8 8.26a.75.75 0 0 1 1.06-1.06l2.71 2.71 5.57-5.6a.75.75 0 0 1 1.06 0Z"
            fill="currentColor"
          />
        </svg>
      ) : (
        <svg viewBox="0 0 16 16" aria-hidden="true" focusable="false">
          <path
            d="M5 2.75A1.75 1.75 0 0 1 6.75 1h5.5A1.75 1.75 0 0 1 14 2.75v6.5A1.75 1.75 0 0 1 12.25 11h-5.5A1.75 1.75 0 0 1 5 9.25v-6.5Zm1.75-.25a.25.25 0 0 0-.25.25v6.5c0 .14.11.25.25.25h5.5a.25.25 0 0 0 .25-.25v-6.5a.25.25 0 0 0-.25-.25h-5.5Z"
            fill="currentColor"
          />
          <path
            d="M2 5.75C2 4.78 2.78 4 3.75 4h.5a.75.75 0 0 1 0 1.5h-.5a.25.25 0 0 0-.25.25v6.5c0 .14.11.25.25.25h5.5a.25.25 0 0 0 .25-.25v-.5a.75.75 0 0 1 1.5 0v.5A1.75 1.75 0 0 1 9.25 14h-5.5A1.75 1.75 0 0 1 2 12.25v-6.5Z"
            fill="currentColor"
          />
        </svg>
      )}
    </button>
  );
}
