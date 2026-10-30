import { useEffect, useState } from "react";
import { observerFetch } from "../host/transport";
import { onConfigRefresh } from "../telemetry/configSignal";

/**
 * Whether the observer has the Config Manager turned on. "pending" until the
 * observer has answered; after that it keeps the last answer while a newer
 * request is in flight.
 */
export type ConfigManagerCapability = "pending" | "on" | "off";

/** True iff the health body says the Config Manager is on. */
export function parseConfigManagerCapability(body: unknown): boolean {
  return typeof body === "object" && body !== null && !Array.isArray(body)
    && (body as Record<string, unknown>).configManager === true;
}

async function fetchConfigManagerCapability(): Promise<boolean> {
  try {
    const response = await observerFetch("/api/health");
    if (response.status !== 200) return false;
    return parseConfigManagerCapability(await response.json());
  } catch {
    return false;
  }
}

/**
 * Reads the Config Manager capability from /api/health on mount and on every
 * config refresh notice. Only the latest request is applied, and anything but
 * a 200 whose body says `configManager: true` is "off".
 */
export function useConfigManagerCapability(): ConfigManagerCapability {
  const [capability, setCapability] = useState<ConfigManagerCapability>("pending");
  useEffect(() => {
    let latest = 0;
    let disposed = false;
    const load = (): void => {
      const id = ++latest;
      void fetchConfigManagerCapability().then((on) => {
        if (!disposed && id === latest) setCapability(on ? "on" : "off");
      });
    };
    load();
    const unsubscribe = onConfigRefresh(load);
    return () => {
      disposed = true;
      unsubscribe();
    };
  }, []);
  return capability;
}
