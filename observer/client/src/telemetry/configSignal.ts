const listeners = new Set<() => void>();

/** Registers a listener for "the user settings may have changed; refetch them". */
export function onConfigRefresh(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

/** Tells every listener to refetch the user settings. */
export function notifyConfigRefresh(): void {
  for (const listener of [...listeners]) {
    listener();
  }
}
