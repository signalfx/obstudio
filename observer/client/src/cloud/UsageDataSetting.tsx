import React, { useEffect, useRef, useState } from "react";
import { observerFetch } from "../host/transport";
import { onConfigRefresh } from "../telemetry/configSignal";
import { createConfigEdits, type ConfigEdits, type ConfigEditsState } from "./configEdits";

const usageDataPath = "telemetry.enabled";

interface Wording {
  title: string;
  description: string;
}

function wordingFrom(body: unknown): Wording | null {
  let node: unknown = body;
  for (const key of ["properties", "telemetry", "properties", "enabled"]) {
    node = node !== null && typeof node === "object" ? (node as Record<string, unknown>)[key] : undefined;
  }
  if (node === null || typeof node !== "object") return null;
  const { title, description } = node as { title?: unknown; description?: unknown };
  if (typeof title !== "string" || title === "" || typeof description !== "string" || description === "") return null;
  return { title, description };
}

function saveErrorText(error: NonNullable<ConfigEditsState["error"]>): string {
  if (error.message) return error.message;
  if (error.status !== undefined) return `Usage data setting could not be saved (HTTP ${error.status}).`;
  return "Usage data setting could not be saved.";
}

/**
 * The switch for sending anonymous usage data. Its label and helper text come
 * from the observer's config definitions, and its value is always the
 * observer's: a change applies at once and the switch shows the result.
 */
export function UsageDataSetting(): React.ReactElement {
  const [wording, setWording] = useState<Wording | null>(null);
  const [wordingFailed, setWordingFailed] = useState(false);
  const [state, setState] = useState<ConfigEditsState | null>(null);
  const editsRef = useRef<ConfigEdits | null>(null);

  useEffect(() => {
    let active = true;
    let haveWording = false;
    let wordingInFlight = false;

    const loadWording = (): void => {
      if (haveWording || wordingInFlight) return;
      wordingInFlight = true;
      observerFetch("/api/config/definitions")
        .then(async (response) => (response.ok ? wordingFrom(await response.json()) : null))
        .catch(() => null)
        .then((loaded) => {
          wordingInFlight = false;
          if (!active) return;
          if (loaded) {
            haveWording = true;
            setWording(loaded);
            setWordingFailed(false);
          } else {
            setWordingFailed(true);
          }
        });
    };

    const edits = createConfigEdits({ [usageDataPath]: "immediate" }, {
      fetchConfig: () => {
        // Every value refresh is also a retry point for the wording.
        loadWording();
        return observerFetch("/api/config");
      },
      postConfig: (body) => observerFetch("/api/config", {
        body,
        headers: { "Content-Type": "application/json", "X-Obstudio-Browser-Request": "1" },
        method: "POST",
      }),
      onChange: (next) => {
        if (active) setState(next);
      },
    });
    editsRef.current = edits;
    const unsubscribe = onConfigRefresh(() => edits.refresh());
    edits.refresh();

    return () => {
      active = false;
      unsubscribe();
      edits.dispose();
      editsRef.current = null;
    };
  }, []);

  const unavailable = wordingFailed || state?.loadFailed === true;
  const ready = !unavailable && wording !== null && state !== null && state.server !== null;

  return (
    <section aria-labelledby="cloud-usage-data-title" className="cloud-panel cloud-usage-data">
      <h2 id="cloud-usage-data-title">Usage data</h2>
      {ready && wording && state ? (
        <>
          <label className="cloud-usage-data__switch">
            <input
              aria-describedby="cloud-usage-data-description"
              checked={state.values[usageDataPath] === true}
              disabled={state.inFlight.has(usageDataPath)}
              onChange={(event) => editsRef.current?.edit(usageDataPath, event.currentTarget.checked)}
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
