import React, { useCallback, useEffect, useRef, useState } from "react";
import { observerFetch } from "../host/transport";
import type { FieldKind } from "./configEdits";
import { saveErrorText, useConfigEdits } from "./useConfigEdits";

const usageDataPath = "telemetry.enabled";
const usageDataFields: Readonly<Record<string, FieldKind>> = { [usageDataPath]: "immediate" };

interface Wording {
  heading: string;
  title: string;
  description: string;
}

function child(node: unknown, key: string): unknown {
  return node !== null && typeof node === "object" ? (node as Record<string, unknown>)[key] : undefined;
}

function nonEmpty(value: unknown): value is string {
  return typeof value === "string" && value !== "";
}

function wordingFrom(body: unknown): Wording | null {
  const section = child(child(body, "properties"), "telemetry");
  const setting = child(child(section, "properties"), "enabled");
  const heading = child(section, "title");
  const title = child(setting, "title");
  const description = child(setting, "description");
  if (!nonEmpty(heading) || !nonEmpty(title) || !nonEmpty(description)) return null;
  return { heading, title, description };
}

/**
 * The switch for sending anonymous usage data. Its heading, label and helper
 * text come from the observer's config definitions, and its value is always the
 * observer's: a change applies at once and the switch shows the result.
 */
export function UsageDataSetting(): React.ReactElement {
  const [wording, setWording] = useState<Wording | null>(null);
  const [wordingFailed, setWordingFailed] = useState(false);
  const wordingLoad = useRef({ have: false, inFlight: false, mounted: false });

  useEffect(() => {
    const load = wordingLoad.current;
    load.mounted = true;
    return () => {
      load.mounted = false;
    };
  }, []);

  // Every value refresh is also a retry point for the wording.
  const loadWording = useCallback((): void => {
    const load = wordingLoad.current;
    if (load.have || load.inFlight) return;
    load.inFlight = true;
    observerFetch("/api/config/definitions")
      .then(async (response) => (response.ok ? wordingFrom(await response.json()) : null))
      .catch(() => null)
      .then((loaded) => {
        load.inFlight = false;
        if (!load.mounted) return;
        if (loaded) {
          load.have = true;
          setWording(loaded);
          setWordingFailed(false);
        } else {
          setWordingFailed(true);
        }
      });
  }, []);

  const { edit, state } = useConfigEdits(usageDataFields, { onRefresh: loadWording });

  const unavailable = wordingFailed || state?.loadFailed === true;
  const ready = !unavailable && wording !== null && state !== null && state.server !== null;

  return (
    <section aria-labelledby={wording ? "cloud-usage-data-title" : undefined} className="cloud-panel cloud-usage-data">
      {wording ? <h2 id="cloud-usage-data-title">{wording.heading}</h2> : null}
      {ready && wording && state ? (
        <>
          <label className="cloud-usage-data__switch">
            <input
              aria-describedby="cloud-usage-data-description"
              checked={state.values[usageDataPath] === true}
              aria-disabled={state.inFlight.has(usageDataPath) || undefined}
              onChange={(event) => edit(usageDataPath, event.currentTarget.checked)}
              role="switch"
              type="checkbox"
            />
            <span>{wording.title}</span>
          </label>
          <p id="cloud-usage-data-description">{wording.description}</p>
          {state.error ? (
            <div className="cloud-alert cloud-alert--error" role="alert">
              {saveErrorText(state.error)}
            </div>
          ) : null}
        </>
      ) : null}
      {unavailable ? <p>The usage data setting is unavailable.</p> : null}
    </section>
  );
}
