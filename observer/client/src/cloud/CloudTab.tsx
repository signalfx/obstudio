import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  createSplunkExportBrowserSession,
  fetchSplunkExportStatus,
  isUnusableSplunkExportBrowserSession,
  recoverSplunkExportBrowserSession,
  resolveSplunkCloudRealm,
  runSplunkExportBrowserAction,
} from "../api/client";
import type { SplunkExportSignalStatus, SplunkExportStatus } from "../api/types";
import {
  isObserverHostCloudTimeoutError,
  isSplunkExportStatus,
  useCloudBridge,
  type CloudBridgeAction,
  type CloudBridgeResponse,
} from "./bridge";
import { hasHostCommandModifier } from "../hooks/useKeyboardShortcuts";

const maxSplunkDestinationBytes = 2048;
const maxSplunkAccessTokenBytes = 4096;
const maxFreeAccountFirstNameLength = 40;
const maxFreeAccountLastNameLength = 40;
const maxFreeAccountEmailLength = 80;
const splunkRealmPattern = /^[a-z]{2,12}[0-9]+$/;
const splunkAccessTokenTooLongMessage = "Access token must be 4,096 UTF-8 bytes or fewer.";
const freeEditionURL = "https://www.splunk.com/en_us/download/observability-cloud-free-edition.html";
const freeEditionTermsURL = "https://www.splunk.com/en_us/legal/splunk-observability-free-edition-terms.html";
const realmHelpURL = "https://help.splunk.com/en/splunk-observability-cloud/administer/org-reference-info/view-your-realm-api-endpoints-and-organization";
const ingestTokenHelpURL = "https://help.splunk.com/en/splunk-observability-cloud/administer/authentication-and-security/authentication-tokens/org-access-tokens";
const observabilityDocsURL = "https://docs.splunk.com/Observability/get-started/welcome.html#nav-Welcome-to-Splunk-Observability-Cloud";
const observabilityCloudDemoURL = "https://www.splunk.com/en_us/resources/videos/watch-splunks-observability-cloud-demo.html";
const observabilityDataCourseURL = "https://education.splunk.com/elearning/getting-data-into-splunk-observability-cloud-elearning";
const freeAccountRegionOptions = [
  { label: "United States", realm: "us1", value: "us" },
  { label: "Europe", realm: "eu0", value: "Europe (Ireland)" },
  { label: "Asia Pacific", realm: "au0", value: "apac-au" },
] as const;
const freeAccountRegions: ReadonlySet<string> = new Set(freeAccountRegionOptions.map(({ value }) => value));
const freeAccountRealmByRegion: ReadonlyMap<string, string> = new Map(
  freeAccountRegionOptions.map(({ realm, value }) => [value, realm]),
);

interface FreeAccountResult {
  intakeAcknowledged: boolean;
  realm: string;
  region: string;
}

class FreeAccountOutcomeUnknownError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "FreeAccountOutcomeUnknownError";
  }
}

type CloudFieldError = "email" | "firstName" | "lastName" | "region" | "terms" | "token";
type FreeAccountMutationState = "idle" | "pending" | "uncertain";

interface SignalRow {
  detail: string;
  label: string;
  status: string;
  tone: "error" | "idle" | "success" | "warning";
}

export type CloudConnectionState = "connected" | "configured" | "disconnected";

interface CloudTabProps {
  onConnectionChange?: (state: CloudConnectionState) => void;
}

interface CloudActionResponse {
  realm?: string;
  status?: SplunkExportStatus;
}

export function CloudTab({ onConnectionChange }: CloudTabProps): React.ReactElement {
  const { bridge, callBridge } = useCloudBridge();
  const [initializedBridge, setInitializedBridge] = useState<typeof bridge>(null);
  const [status, setStatus] = useState<SplunkExportStatus | null>(null);
  const [browserToken, setBrowserToken] = useState<string | null>(null);
  const [region, setRegion] = useState("");
  const [accessToken, setAccessToken] = useState("");
  const [freeAccountFirstName, setFreeAccountFirstName] = useState("");
  const [freeAccountLastName, setFreeAccountLastName] = useState("");
  const [freeAccountEmail, setFreeAccountEmail] = useState("");
  const [freeAccountRegion, setFreeAccountRegion] = useState("us");
  const [freeAccountRegionDetection, setFreeAccountRegionDetection] = useState<"detected" | "detecting" | "fallback" | "idle">("idle");
  const [freeAccountTermsAccepted, setFreeAccountTermsAccepted] = useState(false);
  const [freeAccountOpen, setFreeAccountOpen] = useState(false);
  const [freeAccountSuccess, setFreeAccountSuccess] = useState(false);
  const [freeAccountSubmitError, setFreeAccountSubmitError] = useState<string | null>(null);
  const [freeAccountMutationState, setFreeAccountMutationState] = useState<FreeAccountMutationState>("idle");
  const [cloudInitializationFinished, setCloudInitializationFinished] = useState(false);
  const [fieldError, setFieldError] = useState<CloudFieldError | null>(null);
  const [busyAction, setBusyAction] = useState<CloudBridgeAction | null>("initialize");
  const [controlError, setControlError] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [forgetOpen, setForgetOpen] = useState(false);
  const actionGenerationRef = useRef(0);
  const actionInFlightRef = useRef(false);
  const forgetOpenRef = useRef(false);
  const latestAppliedStatusRequestRef = useRef(0);
  const mountedRef = useRef(false);
  const restoreFocusAfterForgetCloseRef = useRef(false);
  const statusRequestSequenceRef = useRef(0);
  const statusRef = useRef<SplunkExportStatus | null>(null);
  const freeAccountSubmissionInFlight = useRef(false);
  const cloudConfiguredRef = useRef(false);
  const freeAccountMutationStateRef = useRef<FreeAccountMutationState>("idle");
  const freeAccountRegionEdited = useRef(false);
  const freeAccountRegionDetectionStarted = useRef(false);
  const forgetCancelRef = useRef<HTMLButtonElement>(null);
  const forgetConfirmRef = useRef<HTMLButtonElement>(null);
  const forgetTriggerRef = useRef<HTMLButtonElement>(null);
  const regionValueRef = useRef("");
  const regionInputRef = useRef<HTMLInputElement>(null);
  const tokenInputRef = useRef<HTMLInputElement>(null);
  const freeAccountFirstNameRef = useRef<HTMLInputElement>(null);
  const freeAccountLastNameRef = useRef<HTMLInputElement>(null);
  const freeAccountEmailRef = useRef<HTMLInputElement>(null);
  const freeAccountTermsRef = useRef<HTMLInputElement>(null);
  const freeAccountSuccessRef = useRef<HTMLHeadingElement>(null);
  forgetOpenRef.current = forgetOpen;
  regionValueRef.current = region;
  statusRef.current = status;

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  useEffect(() => {
    if (freeAccountOpen && !freeAccountSuccess) freeAccountFirstNameRef.current?.focus();
  }, [freeAccountOpen, freeAccountSuccess]);

  const closeForgetDialog = useCallback(() => {
    restoreFocusAfterForgetCloseRef.current = true;
    setForgetOpen(false);
  }, []);

  useEffect(() => {
    if (forgetOpen || !restoreFocusAfterForgetCloseRef.current) return;
    const focusTarget = forgetTriggerRef.current ?? regionInputRef.current;
    if (!focusTarget) return;
    restoreFocusAfterForgetCloseRef.current = false;
    focusTarget.focus();
  }, [forgetOpen, status]);

  useEffect(() => {
    setBusyAction("initialize");
    let active = true;
    const controller = new AbortController();
    setCloudInitializationFinished(false);
    const initialize = async () => {
      let bridgeInitialized = false;
      let nextBrowserToken: string | null = null;
      try {
        let nextStatus: unknown;
        let controlInitializationError: unknown;
        if (bridge) {
          try {
            const response = await callBridge("initialize");
            nextStatus = response.status;
            bridgeInitialized = true;
            if (response.warning?.trim()) {
              controlInitializationError = new Error(response.warning);
            }
            if (!isSplunkExportStatus(nextStatus)) {
              nextStatus = await fetchSplunkExportStatus(controller.signal);
            }
          } catch (initializationError) {
            if (controller.signal.aborted) return;
            controlInitializationError = initializationError;
            nextStatus = await fetchSplunkExportStatus(controller.signal);
          }
        } else {
          try {
            const session = await createSplunkExportBrowserSession(controller.signal);
            nextBrowserToken = session.browserToken;
            if (session.warning?.trim()) {
              controlInitializationError = new Error(session.warning);
            }
          } catch (browserSessionError) {
            if (controller.signal.aborted) return;
            controlInitializationError = browserSessionError;
          }
          nextStatus = await fetchSplunkExportStatus(controller.signal);
        }
        if (!active) return;
        if (!nextStatus || !isSplunkExportStatus(nextStatus)) {
          throw new Error("Observer returned an invalid cloud status.");
        }
        setStatus(nextStatus);
        if (bridge || nextBrowserToken) setControlError(null);
        if (controlInitializationError) {
          const message = errorMessage(controlInitializationError, "Could not enable cloud connection controls.");
          setControlError(message);
        }
      } catch (initializationError) {
        if (!active || controller.signal.aborted) return;
        const message = errorMessage(initializationError, "Could not load cloud connection status.");
        setError(message);
        onConnectionChange?.("disconnected");
      } finally {
        if (active) {
          setBrowserToken(nextBrowserToken);
          setInitializedBridge(bridgeInitialized ? bridge : null);
          setBusyAction(null);
          setCloudInitializationFinished(true);
        }
      }
    };
    void initialize();
    return () => {
      active = false;
      controller.abort();
    };
  }, [bridge, callBridge, onConnectionChange]);

  useEffect(() => {
    if (forgetOpen) forgetCancelRef.current?.focus();
  }, [forgetOpen]);

  useEffect(() => {
    if (!notice) return undefined;
    const timeoutId = window.setTimeout(() => setNotice(null), 4000);
    return () => window.clearTimeout(timeoutId);
  }, [notice]);

  useEffect(() => {
    if (freeAccountSuccess) freeAccountSuccessRef.current?.focus();
  }, [freeAccountSuccess]);

  const connected = status?.connected === true;
  const controlAvailable = bridge !== null
    ? initializedBridge === bridge
    : browserToken !== null;
  const mutationsDisabled = busyAction !== null
    || status === null
    || !controlAvailable
    || freeAccountMutationState === "uncertain";
  const displayedError = error ?? (controlAvailable ? controlError : null);
  const controlUnavailable = busyAction === null && status !== null && !controlAvailable;

  const applyObserverStatus = useCallback((
    nextStatus: SplunkExportStatus,
    clearReconciledFeedback: boolean,
  ) => {
    const previousStatus = statusRef.current;
    const controlStateChanged = previousStatus
      ? cloudControlStateChanged(previousStatus, nextStatus)
      : false;
    if (clearReconciledFeedback && (!previousStatus || controlStateChanged)) {
      setError(null);
    }
    if (previousStatus && controlStateChanged) {
      if (clearReconciledFeedback) setNotice(null);
      if (
        cloudConfigurationStateChanged(previousStatus, nextStatus)
        && forgetOpenRef.current
      ) {
        closeForgetDialog();
      }
    }
    statusRef.current = nextStatus;
    setStatus(nextStatus);
    if (
      clearReconciledFeedback
      && controlAvailable
      && (!previousStatus || controlStateChanged)
    ) {
      setControlError(null);
    }
    return controlStateChanged;
  }, [closeForgetDialog, controlAvailable]);

  const loadObserverStatus = useCallback(async (
    clearReconciledFeedback: boolean,
    signal?: AbortSignal,
    shouldApply: () => boolean = () => true,
  ) => {
    const sequence = ++statusRequestSequenceRef.current;
    const nextStatus = await fetchSplunkExportStatus(signal);
    if (
      !mountedRef.current
      || !shouldApply()
      || !isSplunkExportStatus(nextStatus)
      || sequence < latestAppliedStatusRequestRef.current
    ) {
      return { applied: false, stateChanged: false };
    }
    latestAppliedStatusRequestRef.current = sequence;
    return {
      applied: true,
      stateChanged: applyObserverStatus(nextStatus, clearReconciledFeedback),
    };
  }, [applyObserverStatus]);

  const reconcileFailedAction = useCallback(async (actionGeneration: number) => {
    try {
      const result = await loadObserverStatus(
        false,
        undefined,
        () => actionGenerationRef.current === actionGeneration,
      );
      if (result.applied && result.stateChanged) {
        setError(null);
        setNotice("Cloud state refreshed from Observer.");
      }
    } catch {
      // Normal polling will retry if the Observer is temporarily unavailable.
    }
  }, [loadObserverStatus]);

  useEffect(() => {
    if (status === null) return;
    const isConfigured = status.connected
      || status.metrics.configured
      || status.traces.configured;
    const state: CloudConnectionState = status.connected ? "connected" : isConfigured ? "configured" : "disconnected";
    onConnectionChange?.(state);
  }, [onConnectionChange, status]);

  const exportEnabled = status?.enabled === true;
  const metricsConfigured = status?.metrics.configured === true;
  const tracesConfigured = status?.traces.configured === true;
  const cloudConfigured = connected || metricsConfigured || tracesConfigured;
  cloudConfiguredRef.current = cloudConfigured;
  freeAccountMutationStateRef.current = freeAccountMutationState;
  const exportPartiallyEnabled = !exportEnabled
    && (status?.metrics.enabled === true || status?.traces.enabled === true);
  const exportActive = exportEnabled || exportPartiallyEnabled;
  const exportStateLabel = exportEnabled ? "on" : exportPartiallyEnabled ? "partially on" : "off";
  const destinationLabel = cloudConfigured
    ? status?.realm?.trim()
      ? status.realm.toLowerCase()
      : "configured destination"
    : "";
  const connectionSummary = connected
    ? `${destinationLabel} · Access token configured`
    : cloudConfigured
      ? status?.realm?.trim()
        ? `${destinationLabel} · Connection details incomplete`
        : "Connection details incomplete"
      : "Connect to export metrics and traces.";
  const signals = useMemo(() => [
    signalRow("Metrics", status?.metrics),
    signalRow("Traces", status?.traces),
  ], [status]);

  useEffect(() => {
    if (!cloudConfigured || freeAccountMutationStateRef.current === "pending") return;
    freeAccountSubmissionInFlight.current = false;
    setFreeAccountFirstName("");
    setFreeAccountLastName("");
    setFreeAccountEmail("");
    setFreeAccountTermsAccepted(false);
    if (freeAccountMutationStateRef.current === "uncertain") return;
    freeAccountRegionEdited.current = false;
    freeAccountRegionDetectionStarted.current = false;
    setFreeAccountRegion("us");
    setFreeAccountRegionDetection("idle");
    setFreeAccountOpen(false);
    setFreeAccountSuccess(false);
    setFreeAccountSubmitError(null);
    setFreeAccountMutationState("idle");
  }, [cloudConfigured]);

  useEffect(() => {
    if (
      !bridge
      || !controlAvailable
      || !cloudInitializationFinished
      || cloudConfigured
      || !freeAccountOpen
      || freeAccountSuccess
      || freeAccountRegionDetectionStarted.current
    ) return undefined;

    freeAccountRegionDetectionStarted.current = true;
    setFreeAccountRegionDetection("detecting");
    void callBridge("detect-free-account-region").then((response) => {
      if (!mountedRef.current) return;
      const detectedRegion = parseFreeAccountRegion(response.region);
      if (detectedRegion === undefined) {
        setFreeAccountRegionDetection("fallback");
        return;
      }
      if (!freeAccountRegionEdited.current) setFreeAccountRegion(detectedRegion);
      setFreeAccountRegionDetection("detected");
    }).catch(() => {
      if (mountedRef.current) setFreeAccountRegionDetection("fallback");
    });
    return undefined;
  }, [bridge, callBridge, cloudConfigured, cloudInitializationFinished, controlAvailable, freeAccountOpen, freeAccountSuccess]);

  useEffect(() => {
    if (busyAction !== null) return undefined;
    let active = true;
    let controller: AbortController | undefined;
    let timeoutId: number | undefined;

    const poll = async () => {
      controller = new AbortController();
      try {
        await loadObserverStatus(true, controller.signal, () => active);
      } catch {
        // Keep the last known status if a background status request fails.
      } finally {
        if (active) timeoutId = window.setTimeout(() => void poll(), 5000);
      }
    };

    timeoutId = window.setTimeout(() => void poll(), 5000);
    return () => {
      active = false;
      if (timeoutId !== undefined) window.clearTimeout(timeoutId);
      controller?.abort();
    };
  }, [busyAction, loadObserverStatus]);

  const runAction = async (
    action: CloudBridgeAction,
    payload?: { accessToken?: string; destination?: string; enabled?: boolean; realm?: string },
  ): Promise<CloudActionResponse | null> => {
    if (busyAction || actionInFlightRef.current || !controlAvailable) return null;
    const expectedVersion = statusRef.current?.version;
    if (!expectedVersion) {
      setError("Observer cloud state is unavailable. Refresh and try again.");
      return null;
    }
    const versionedPayload = { ...payload, expectedVersion };
    const actionGeneration = ++actionGenerationRef.current;
    actionInFlightRef.current = true;
    setBusyAction(action);
    setFieldError(null);
    setError(null);
    setNotice(null);
    try {
      let response: CloudBridgeResponse | CloudActionResponse;
      if (bridge) {
        response = await callBridge(action, versionedPayload);
      } else if (browserToken) {
        if (action !== "connect" && action !== "forget" && action !== "set-enabled") {
          throw new Error("This cloud action requires an IDE session.");
        }
        response = {
          status: await runSplunkExportBrowserAction(action, versionedPayload, browserToken),
        };
      } else {
        throw new Error("Cloud connection changes are not available in this session.");
      }
      if (response.status) setStatus(response.status);
      setControlError(null);
      return response;
    } catch (actionError) {
      const message = errorMessage(actionError, "The cloud connection request failed.");
      if (bridge && isObserverHostCloudTimeoutError(actionError)) {
        setInitializedBridge(null);
        setError(message);
        setControlError(null);
      } else if (!bridge && isUnusableSplunkExportBrowserSession(actionError)) {
        setBrowserToken(null);
        setControlError(null);
        try {
          const recovered = await recoverSplunkExportBrowserSession();
          const result = await loadObserverStatus(
            false,
            undefined,
            () => actionGenerationRef.current === actionGeneration,
          );
          if (!result.applied) {
            throw new Error("Observer returned an invalid cloud status.");
          }
          setBrowserToken(recovered.browserToken);
          setError(null);
          setControlError(recovered.warning?.trim() || null);
          setNotice("Cloud controls refreshed. Retry the action.");
        } catch {
          setError(message);
          void reconcileFailedAction(actionGeneration);
        }
        return null;
      } else {
        setError(message);
      }
      void reconcileFailedAction(actionGeneration);
      return null;
    } finally {
      actionInFlightRef.current = false;
      setBusyAction(null);
    }
  };

  const resolveConnectionDestination = async (destination: string): Promise<string | null> => {
    const normalizedRealm = destination.toLowerCase();
    if (splunkRealmPattern.test(normalizedRealm)) return normalizedRealm;
    if (busyAction || actionInFlightRef.current || !controlAvailable) return null;

    const actionGeneration = ++actionGenerationRef.current;
    actionInFlightRef.current = true;
    setBusyAction("resolve-realm");
    setFieldError(null);
    setError(null);
    setNotice(null);
    try {
      const resolvedRealm = bridge
        ? (await callBridge("resolve-realm", { destination })).realm
        : browserToken
          ? await resolveSplunkCloudRealm(destination, browserToken)
          : undefined;
      const realm = typeof resolvedRealm === "string" ? resolvedRealm.trim().toLowerCase() : "";
      if (!splunkRealmPattern.test(realm)) {
        throw new Error("Observer returned an invalid Splunk Observability Cloud realm.");
      }
      return realm;
    } catch (resolutionError) {
      const message = errorMessage(
        resolutionError,
        "Could not determine the realm from that Observability Cloud URL.",
      );
      if (!bridge && isUnusableSplunkExportBrowserSession(resolutionError)) {
        setBrowserToken(null);
        setControlError(null);
        try {
          const recovered = await recoverSplunkExportBrowserSession();
          const result = await loadObserverStatus(
            false,
            undefined,
            () => actionGenerationRef.current === actionGeneration,
          );
          if (!result.applied) {
            throw new Error("Observer returned an invalid cloud status.");
          }
          setBrowserToken(recovered.browserToken);
          setError(null);
          setControlError(recovered.warning?.trim() || null);
          setNotice("Cloud controls refreshed. Retry the action.");
        } catch {
          setFieldError("region");
          setError(message);
          regionInputRef.current?.focus();
        }
      } else {
        setFieldError("region");
        setError(message);
        regionInputRef.current?.focus();
      }
      return null;
    } finally {
      actionInFlightRef.current = false;
      setBusyAction(null);
    }
  };

  const connect = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (mutationsDisabled) return;
    const submittedAccessToken = accessToken;
    const token = submittedAccessToken.trim();
    const destination = region.trim();
    if (
      utf8ByteLength(destination) > maxSplunkDestinationBytes
      || !isPotentialSplunkCloudDestination(destination)
    ) {
      setFieldError("region");
      setError("Enter a valid realm or Splunk Observability Cloud URL.");
      regionInputRef.current?.focus();
      return;
    }
    if (token.length === 0) {
      setFieldError("token");
      setError("Paste the access token secret.");
      tokenInputRef.current?.focus();
      return;
    }
    if (utf8ByteLength(token) > maxSplunkAccessTokenBytes) {
      setFieldError("token");
      setError(splunkAccessTokenTooLongMessage);
      tokenInputRef.current?.focus();
      return;
    }
    const realm = await resolveConnectionDestination(destination);
    if (realm === null || regionValueRef.current.trim() !== destination) return;
    const response = await runAction("connect", {
      accessToken: token,
      realm,
    });
    if (!response) return;
    if (response.status?.connected !== true) {
      setError("Splunk Observability Cloud did not confirm the connection.");
      return;
    }
    setAccessToken((currentAccessToken) => (
      currentAccessToken === submittedAccessToken ? "" : currentAccessToken
    ));
    setNotice("Cloud destination connected.");
  };

  const submitConnectionOnEnter = (event: React.KeyboardEvent<HTMLInputElement>) => {
    if (
      event.key !== "Enter"
      || event.nativeEvent.isComposing
      || hasHostCommandModifier(event)
    ) return;
    event.preventDefault();
    event.currentTarget.form?.requestSubmit();
  };

  const openExternalLink = (
    event: React.MouseEvent<HTMLAnchorElement>,
    action: Extract<CloudBridgeAction, `open-${string}`>,
  ) => {
    if (!bridge) return;
    event.preventDefault();
    event.stopPropagation();
    void callBridge(action).catch((openError) => {
      setError(errorMessage(openError, "Could not open the external page."));
    });
  };

  const externalLinkAttributes = (url: string) => bridge
    ? { href: "#", rel: undefined, target: undefined }
    : { href: url, rel: "noopener noreferrer", target: "_blank" };

  const toggleExport = async () => {
    const response = await runAction("set-enabled", { enabled: !exportEnabled });
    if (response) {
      setNotice(exportEnabled ? "Remote export disabled." : "Remote export enabled.");
    }
  };

  const forget = async () => {
    const response = await runAction("forget");
    if (!response) return;
    closeForgetDialog();
    setRegion("");
    setAccessToken("");
    setNotice("Connection removed.");
  };

  const createFreeAccount = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (
      !bridge
      || mutationsDisabled
      || freeAccountRegionDetection === "detecting"
      || freeAccountRegionDetection === "idle"
      || freeAccountMutationState !== "idle"
      || freeAccountSubmissionInFlight.current
    ) return;

    const firstName = normalizeNamePart(freeAccountFirstName);
    const lastName = normalizeNamePart(freeAccountLastName);
    const email = freeAccountEmail.trim();
    if (!isValidNamePart(firstName, maxFreeAccountFirstNameLength)) {
      setFieldError("firstName");
      setError("Enter your first name.");
      freeAccountFirstNameRef.current?.focus();
      return;
    }
    if (!isValidNamePart(lastName, maxFreeAccountLastNameLength)) {
      setFieldError("lastName");
      setError("Enter your last name.");
      freeAccountLastNameRef.current?.focus();
      return;
    }
    if (!isValidEmail(email)) {
      setFieldError("email");
      setError("Enter a valid email address.");
      freeAccountEmailRef.current?.focus();
      return;
    }
    if (!freeAccountTermsAccepted) {
      setFieldError("terms");
      setError("Accept the Free Edition Terms of Use to continue.");
      freeAccountTermsRef.current?.focus();
      return;
    }

    freeAccountSubmissionInFlight.current = true;
    setFreeAccountMutationState("pending");
    setBusyAction("create-free-account");
    setFieldError(null);
    setError(null);
    setFreeAccountSubmitError(null);
    setNotice(null);
    try {
      const response = await callBridge("create-free-account", {
        email,
        firstName,
        lastName,
        region: freeAccountRegion,
        termsAccepted: true,
      });
      const result = parseFreeAccountResult(response.freeAccount);
      if (!result) {
        throw new FreeAccountOutcomeUnknownError("Observer did not confirm the Free Edition request.");
      }
      if (!result.intakeAcknowledged) {
        setFreeAccountMutationState("idle");
        setFreeAccountSubmitError("Splunk did not acknowledge the Free Edition signup intake.");
        return;
      }
      setFreeAccountMutationState("idle");
      if (cloudConfiguredRef.current) {
        setFreeAccountFirstName("");
        setFreeAccountLastName("");
        setFreeAccountEmail("");
        setFreeAccountTermsAccepted(false);
      } else {
        setFreeAccountFirstName((currentFirstName) => (
          normalizeNamePart(currentFirstName) === firstName ? "" : currentFirstName
        ));
        setFreeAccountLastName((currentLastName) => (
          normalizeNamePart(currentLastName) === lastName ? "" : currentLastName
        ));
        setFreeAccountEmail((currentEmail) => (
          currentEmail.trim() === email ? "" : currentEmail
        ));
        setFreeAccountTermsAccepted((currentTermsAccepted) => (
          currentTermsAccepted ? false : currentTermsAccepted
        ));
      }
      setRegion((currentRegion) => (
        currentRegion.trim() === "" ? result.realm : currentRegion
      ));
      setFreeAccountSuccess(true);
    } catch (submissionError) {
      setFieldError(null);
      if (isObserverHostCloudTimeoutError(submissionError)) {
        setInitializedBridge(null);
        setFreeAccountMutationState("uncertain");
        setFreeAccountSubmitError(`${errorMessage(
          submissionError,
          "The IDE did not confirm the Free Edition request.",
        )} No automatic retry was attempted.`);
      } else if (isOutcomeUnknown(submissionError)) {
        setFreeAccountMutationState("idle");
        setFreeAccountSubmitError(`${errorMessage(
          submissionError,
          "Observer could not confirm whether Splunk received the Free Edition request.",
        )} No automatic retry was attempted. Check your email before submitting another request.`);
      } else {
        setFreeAccountMutationState("idle");
        setFreeAccountSubmitError(errorMessage(submissionError, "Could not submit the Free Edition request."));
      }
      if (cloudConfiguredRef.current) {
        setFreeAccountFirstName("");
        setFreeAccountLastName("");
        setFreeAccountEmail("");
        setFreeAccountTermsAccepted(false);
      }
    } finally {
      freeAccountSubmissionInFlight.current = false;
      setBusyAction(null);
    }
  };

  const startAnotherFreeAccountRequest = () => {
    setFreeAccountOpen(true);
    setFreeAccountSuccess(false);
    setFieldError(null);
    setError(null);
    setFreeAccountSubmitError(null);
  };

  const openFreeAccount = () => {
    setFreeAccountOpen(true);
    setFieldError(null);
    setError(null);
    setFreeAccountSubmitError(null);
  };

  return (
    <section id="panel-cloud" aria-label="Cloud" className="tab-panel cloud-tab" role="tabpanel">
      <div className="cloud-tab__content">
        <div aria-atomic="true" aria-live="polite" className="cloud-alert-region">
          {displayedError || (cloudConfigured ? freeAccountSubmitError : null) ? (
            <div className="cloud-alert cloud-alert--error" role="alert">
              {displayedError ?? freeAccountSubmitError}
            </div>
          ) : null}
          {!displayedError && !freeAccountSubmitError && notice ? <div className="cloud-alert cloud-alert--success" role="status">{notice}</div> : null}
          {!displayedError && !freeAccountSubmitError && !notice && cloudConfigured && freeAccountSuccess ? (
            <div className="cloud-alert cloud-alert--success" role="status">
              Thank you for registering. Your free edition account is on its way! You will receive an email within 10 minutes.
            </div>
          ) : null}
        </div>

        <div
          aria-busy={busyAction ? "true" : "false"}
          className={cloudConfigured ? undefined : "cloud-setup-stack"}
        >
          <section className={cloudConfigured ? "cloud-panel" : "cloud-panel cloud-panel--setup"}>
          <header className="cloud-panel__header">
            <div>
              <h2>Splunk Observability Cloud</h2>
              <p>{connectionSummary}</p>
              {controlUnavailable ? (
                <p className="cloud-control-note" role="status">
                  Observer state is read-only in this browser session.
                </p>
              ) : null}
            </div>
            {cloudConfigured ? (
              <div className="cloud-panel__actions">
                <button
                  className="cloud-button cloud-button--danger"
                  disabled={mutationsDisabled}
                  onClick={() => setForgetOpen(true)}
                  ref={forgetTriggerRef}
                  type="button"
                >
                  Remove connection
                </button>
              </div>
            ) : null}
          </header>

          {!cloudConfigured ? (
            <form aria-label="Cloud connection" className="cloud-connect-form" noValidate onSubmit={connect}>
              <div className="cloud-field cloud-field--region">
                <div className="cloud-field__control cloud-field__control--filled">
                  <label className="cloud-field__floating-label" htmlFor="cloud-region">Realm or Observability Cloud URL</label>
                  <input
                    aria-describedby={fieldError === "region" ? "cloud-region-format cloud-region-error" : "cloud-region-format"}
                    aria-invalid={fieldError === "region"}
                    aria-label="Realm or Observability Cloud URL"
                    autoCapitalize="none"
                    autoComplete="off"
                    autoCorrect="off"
                    id="cloud-region"
                    maxLength={maxSplunkDestinationBytes}
                    onChange={(event) => {
                      setRegion(event.target.value);
                      if (fieldError === "region") setFieldError(null);
                      setError(null);
                    }}
                    onKeyDown={submitConnectionOnEnter}
                    ref={regionInputRef}
                    spellCheck={false}
                    value={region}
                  />
                </div>
                <p className="visually-hidden" id="cloud-region-format">Enter a realm or paste an Observability Cloud URL.</p>
                {fieldError === "region" ? (
                  <p className="cloud-field__error" id="cloud-region-error">Enter a valid realm or Observability Cloud URL.</p>
                ) : null}
              </div>
              <div className="cloud-field cloud-field--token">
                <div
                  className={accessToken
                    ? "cloud-field__control cloud-field__control--filled"
                    : "cloud-field__control"}
                >
                  <label className="cloud-field__floating-label" htmlFor="cloud-access-token">Access token</label>
                  <input
                    aria-describedby={fieldError === "token" ? "cloud-token-help cloud-token-error" : "cloud-token-help"}
                    aria-invalid={fieldError === "token"}
                    autoCapitalize="none"
                    autoComplete="new-password"
                    autoCorrect="off"
                    id="cloud-access-token"
                    onChange={(event) => {
                      if (utf8ByteLength(event.target.value) > maxSplunkAccessTokenBytes) {
                        setError(splunkAccessTokenTooLongMessage);
                        setFieldError("token");
                        return;
                      }
                      setAccessToken(event.target.value);
                      if (fieldError === "token") setFieldError(null);
                      setError(null);
                    }}
                    onKeyDown={submitConnectionOnEnter}
                    onPaste={(event) => {
                      const pastedToken = event.clipboardData.getData("text");
                      if (pastedToken === "") return;
                      const input = event.currentTarget;
                      const selectionStart = input.selectionStart ?? input.value.length;
                      const selectionEnd = input.selectionEnd ?? selectionStart;
                      const nextValue = input.value.slice(0, selectionStart)
                        + pastedToken
                        + input.value.slice(selectionEnd);
                      if (utf8ByteLength(nextValue) > maxSplunkAccessTokenBytes) {
                        event.preventDefault();
                        setFieldError("token");
                        setError(splunkAccessTokenTooLongMessage);
                      }
                    }}
                    placeholder="Access token"
                    ref={tokenInputRef}
                    spellCheck={false}
                    type="password"
                    value={accessToken}
                  />
                </div>
                <p className="cloud-field__help" id="cloud-token-help">
                  More on{" "}
                  <a
                    className="cloud-field__help-link"
                    {...externalLinkAttributes(realmHelpURL)}
                    onClick={(event) => openExternalLink(event, "open-realm-help")}
                  >
                    realm
                  </a>
                  {" and "}
                  <a
                    className="cloud-field__help-link"
                    {...externalLinkAttributes(ingestTokenHelpURL)}
                    onClick={(event) => openExternalLink(event, "open-ingest-token-help")}
                  >
                    access tokens
                  </a>
                </p>
                {fieldError === "token" ? (
                  <p className="cloud-field__error" id="cloud-token-error">Paste the full access token.</p>
                ) : null}
              </div>
              <div className="cloud-connect-form__action">
                <button
                  className="cloud-button cloud-button--primary"
                  disabled={mutationsDisabled}
                  type="submit"
                >
                  {busyAction === "connect" || busyAction === "resolve-realm" ? "Connecting..." : "Connect"}
                </button>
              </div>
            </form>
          ) : (
            <section aria-labelledby="cloud-export-title" className="cloud-export">
              <div className="cloud-export__header">
                <div>
                  <h3 id="cloud-export-title">Remote export</h3>
                  <p>Send metrics and traces to {destinationLabel}.</p>
                </div>
                <button
                  aria-checked={exportEnabled}
                  aria-label={`Remote telemetry export is ${exportStateLabel}`}
                  className={exportEnabled ? "cloud-switch cloud-switch--on" : "cloud-switch"}
                  disabled={mutationsDisabled}
                  onClick={() => void toggleExport()}
                  role="switch"
                  type="button"
                >
                  <span aria-hidden="true" className="cloud-switch__track"><span /></span>
                  <span>
                    {busyAction === "set-enabled"
                      ? "Updating"
                      : exportEnabled
                        ? "On"
                        : exportPartiallyEnabled
                          ? "Partial"
                          : "Off"}
                  </span>
                </button>
              </div>

              {exportActive ? (
                <div aria-label="Telemetry export activity" className="cloud-signal-list" role="list">
                  {signals.map((signal) => (
                    <div className={`cloud-signal-row cloud-signal-row--${signal.tone}`} key={signal.label} role="listitem">
                      <div>
                        <p><span aria-hidden="true" />{signal.label}</p>
                        <small>{signal.status}</small>
                      </div>
                      <span>{signal.detail}</span>
                    </div>
                  ))}
                </div>
              ) : null}
            </section>
          )}
          </section>
          {!cloudConfigured ? (
            bridge ? (
              <section
                aria-labelledby={freeAccountSuccess
                  ? "cloud-free-account-success-title"
                  : freeAccountOpen
                    ? "cloud-free-account-title"
                    : "cloud-free-account-prompt-title"}
                className="cloud-panel cloud-free-account cloud-free-account--signup"
              >
                {!freeAccountOpen && !freeAccountSuccess ? (
                  <div className="cloud-free-account__prompt">
                    <div>
                      <h3 id="cloud-free-account-prompt-title">New to Observability Cloud?</h3>
                      <p>Sign up to get an access token.</p>
                    </div>
                    <button
                      aria-controls="cloud-free-account-details"
                      aria-expanded={false}
                      className="cloud-button cloud-button--setup-action cloud-free-account__start"
                      disabled={mutationsDisabled}
                      onClick={openFreeAccount}
                      type="button"
                    >
                      Get started with Observability Cloud Free Edition
                    </button>
                  </div>
                ) : null}
                <div id="cloud-free-account-details" hidden={!freeAccountOpen}>
                  {freeAccountOpen && !freeAccountSuccess ? (
                    <header className="cloud-free-account__header">
                      <h3 id="cloud-free-account-title">Get started with Observability Cloud Free Edition</h3>
                    </header>
                  ) : null}
                  {freeAccountSuccess ? (
                    <div className="cloud-free-account__outcome cloud-free-account__outcome--success">
                      <h3 id="cloud-free-account-success-title" ref={freeAccountSuccessRef} tabIndex={-1}>
                        Thank you for registering. Your free edition account is on its way!
                      </h3>
                      <p className="cloud-free-account__confirmation-copy">
                        You will receive an email within 10 minutes. Check your spam folder if it doesn’t arrive. If you still need help, please reach out to Splunk Support.
                      </p>
                      <div className="cloud-free-account__outcome-actions">
                        <button className="cloud-button cloud-free-account__repeat" onClick={startAnotherFreeAccountRequest} type="button">
                          Submit another request
                        </button>
                      </div>
                      <nav aria-label="Free Edition resources">
                        <ul className="cloud-free-account__resources">
                          <li>
                            <a {...externalLinkAttributes(observabilityDocsURL)} onClick={(event) => openExternalLink(event, "open-observability-docs")}>
                              Observability Docs.
                            </a>{" "}Get guidance on how to use Splunk Observability.
                          </li>
                          <li>
                            <a {...externalLinkAttributes(observabilityCloudDemoURL)} onClick={(event) => openExternalLink(event, "open-observability-cloud-demo")}>
                              Observability Cloud Demo.
                            </a>{" "}Watch Splunk Observability Cloud work in real-time.
                          </li>
                          <li>
                            <a {...externalLinkAttributes(observabilityDataCourseURL)} onClick={(event) => openExternalLink(event, "open-observability-data-course")}>
                              Getting Data into Splunk Observability Cloud.
                            </a>{" "}Learn how to Get Data In to Splunk Observability with a free Splunk Education Course.
                          </li>
                        </ul>
                      </nav>
                    </div>
                  ) : freeAccountOpen ? (
                    <form aria-label="Free Edition account" className="cloud-free-account__form" id="cloud-free-account-form" noValidate onSubmit={createFreeAccount}>
                    <div className="cloud-free-account__fields">
                      <div className="cloud-field cloud-field--free-account">
                        <div className={freeAccountFirstName ? "cloud-field__control cloud-field__control--filled" : "cloud-field__control"}>
                          <label className="cloud-field__floating-label" htmlFor="cloud-free-account-first-name">First name</label>
                          <input
                            aria-describedby={fieldError === "firstName" ? "cloud-free-account-first-name-error" : undefined}
                            aria-invalid={fieldError === "firstName"}
                            autoComplete="given-name"
                            id="cloud-free-account-first-name"
                            maxLength={maxFreeAccountFirstNameLength}
                            onChange={(event) => {
                              setFreeAccountFirstName(event.target.value);
                              if (fieldError === "firstName") setFieldError(null);
                              setError(null);
                              setFreeAccountSubmitError(null);
                            }}
                            placeholder="First name"
                            ref={freeAccountFirstNameRef}
                            required
                            value={freeAccountFirstName}
                          />
                        </div>
                        {fieldError === "firstName" ? <p className="cloud-field__error" id="cloud-free-account-first-name-error">Enter your first name.</p> : null}
                      </div>
                      <div className="cloud-field cloud-field--free-account">
                        <div className={freeAccountLastName ? "cloud-field__control cloud-field__control--filled" : "cloud-field__control"}>
                          <label className="cloud-field__floating-label" htmlFor="cloud-free-account-last-name">Last name</label>
                          <input
                            aria-describedby={fieldError === "lastName" ? "cloud-free-account-last-name-error" : undefined}
                            aria-invalid={fieldError === "lastName"}
                            autoComplete="family-name"
                            id="cloud-free-account-last-name"
                            maxLength={maxFreeAccountLastNameLength}
                            onChange={(event) => {
                              setFreeAccountLastName(event.target.value);
                              if (fieldError === "lastName") setFieldError(null);
                              setError(null);
                              setFreeAccountSubmitError(null);
                            }}
                            placeholder="Last name"
                            ref={freeAccountLastNameRef}
                            required
                            value={freeAccountLastName}
                          />
                        </div>
                        {fieldError === "lastName" ? <p className="cloud-field__error" id="cloud-free-account-last-name-error">Enter your last name.</p> : null}
                      </div>
                      <div className="cloud-field cloud-field--free-account">
                        <div className={freeAccountEmail ? "cloud-field__control cloud-field__control--filled" : "cloud-field__control"}>
                          <label className="cloud-field__floating-label" htmlFor="cloud-free-account-email">Email</label>
                          <input
                            aria-describedby={fieldError === "email" ? "cloud-free-account-email-error" : undefined}
                            aria-invalid={fieldError === "email"}
                            autoCapitalize="none"
                            autoComplete="email"
                            autoCorrect="off"
                            id="cloud-free-account-email"
                            inputMode="email"
                            maxLength={maxFreeAccountEmailLength}
                            onChange={(event) => {
                              setFreeAccountEmail(event.target.value);
                              if (fieldError === "email") setFieldError(null);
                              setError(null);
                              setFreeAccountSubmitError(null);
                            }}
                            placeholder="Email"
                            ref={freeAccountEmailRef}
                            required
                            spellCheck={false}
                            type="email"
                            value={freeAccountEmail}
                          />
                        </div>
                        {fieldError === "email" ? <p className="cloud-field__error" id="cloud-free-account-email-error">Enter a valid email address.</p> : null}
                      </div>
                      <div className="cloud-field cloud-field--free-account">
                        <div className="cloud-field__control cloud-field__control--filled cloud-field__control--select">
                          <label className="cloud-field__floating-label" htmlFor="cloud-free-account-region">Region</label>
                          <select
                            aria-describedby={freeAccountRegionDetection === "detecting" ? "cloud-free-account-region-hint" : undefined}
                            id="cloud-free-account-region"
                            onChange={(event) => {
                              const nextRegion = parseFreeAccountRegion(event.target.value);
                              if (nextRegion === undefined) return;
                              freeAccountRegionEdited.current = true;
                              setFreeAccountRegion(nextRegion);
                              setError(null);
                              setFreeAccountSubmitError(null);
                            }}
                            value={freeAccountRegion}
                          >
                            {freeAccountRegionOptions.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
                          </select>
                        </div>
                        {freeAccountRegionDetection === "detecting" ? (
                          <p aria-live="polite" className="cloud-field__hint" id="cloud-free-account-region-hint">
                            Detecting automatically. Change if needed.
                          </p>
                        ) : null}
                      </div>
                    </div>
                    <div className="cloud-free-account__terms">
                      <input
                        aria-describedby={fieldError === "terms" ? "cloud-free-account-terms-error" : undefined}
                        aria-invalid={fieldError === "terms"}
                        aria-label="I accept the Observability Cloud Free Edition Terms of Use."
                        checked={freeAccountTermsAccepted}
                        id="cloud-free-account-terms"
                        onChange={(event) => {
                          setFreeAccountTermsAccepted(event.target.checked);
                          if (fieldError === "terms") setFieldError(null);
                          setError(null);
                          setFreeAccountSubmitError(null);
                        }}
                        ref={freeAccountTermsRef}
                        required
                        type="checkbox"
                      />
                      <span>
                        <label htmlFor="cloud-free-account-terms">I accept the</label>{" "}
                        <a {...externalLinkAttributes(freeEditionTermsURL)} onClick={(event) => openExternalLink(event, "open-free-edition-terms")}>
                          Observability Cloud Free Edition Terms of Use
                        </a>.
                      </span>
                    </div>
                    {fieldError === "terms" ? <p className="cloud-field__error cloud-free-account__terms-error" id="cloud-free-account-terms-error">Accept the Terms of Use to continue.</p> : null}
                    <div className="cloud-free-account__action">
                      {freeAccountSubmitError ? (
                        <div className="cloud-alert cloud-alert--error cloud-free-account__submission-error" role="alert">
                          {freeAccountSubmitError}
                        </div>
                      ) : null}
                      <button
                        className="cloud-button cloud-button--setup-action"
                        disabled={mutationsDisabled || freeAccountRegionDetection === "detecting" || freeAccountRegionDetection === "idle"}
                        type="submit"
                      >
                        {busyAction === "create-free-account" ? "Submitting..." : "Start Free Edition"}
                      </button>
                    </div>
                    </form>
                  ) : null}
                </div>
              </section>
            ) : (
              <section aria-labelledby="cloud-free-account-title" className="cloud-panel cloud-free-account cloud-free-account--external">
                <div>
                  <h3 id="cloud-free-account-title">Don't have an Observability Cloud account?</h3>
                  <p>Create a free account with your own organization, then connect it here.</p>
                </div>
                <a className="cloud-button cloud-free-account__link" href={freeEditionURL} rel="noopener noreferrer" target="_blank">
                  Start Free Edition<span aria-hidden="true" />
                </a>
              </section>
            )
          ) : null}
        </div>
      </div>

      {forgetOpen ? (
        <div
          className="cloud-dialog-backdrop"
          onMouseDown={(event) => {
            if (event.currentTarget === event.target && busyAction !== "forget") closeForgetDialog();
          }}
        >
          <section
            aria-describedby="cloud-forget-description"
            aria-labelledby="cloud-forget-title"
            aria-modal="true"
            className="cloud-dialog"
            onKeyDown={(event) => {
              if (event.key === "Escape" && busyAction !== "forget") {
                event.preventDefault();
                closeForgetDialog();
                return;
              }
              if (event.key !== "Tab") return;
              const first = forgetCancelRef.current;
              const last = forgetConfirmRef.current;
              if (!first || !last) return;
              if (event.shiftKey && document.activeElement === first) {
                event.preventDefault();
                last.focus();
              } else if (!event.shiftKey && document.activeElement === last) {
                event.preventDefault();
                first.focus();
              }
            }}
            role="dialog"
          >
            <h2 id="cloud-forget-title">Remove connection?</h2>
            <p id="cloud-forget-description">
              This removes the saved region and access token and turns off remote export.
            </p>
            <div>
              <button
                className="cloud-button"
                disabled={busyAction === "forget"}
                onClick={closeForgetDialog}
                ref={forgetCancelRef}
                type="button"
              >
                Cancel
              </button>
              <button
                className="cloud-button cloud-button--danger"
                disabled={busyAction === "forget"}
                onClick={() => void forget()}
                ref={forgetConfirmRef}
                type="button"
              >
                {busyAction === "forget" ? "Removing connection..." : "Remove connection"}
              </button>
            </div>
          </section>
        </div>
      ) : null}
    </section>
  );
}

function cloudControlStateChanged(
  current: SplunkExportStatus,
  next: SplunkExportStatus,
): boolean {
  return cloudConfigurationStateChanged(current, next)
    || current.enabled !== next.enabled
    || current.metrics.enabled !== next.metrics.enabled
    || current.traces.enabled !== next.traces.enabled;
}

function cloudConfigurationStateChanged(
  current: SplunkExportStatus,
  next: SplunkExportStatus,
): boolean {
  return current.version !== next.version
    || current.connected !== next.connected
    || (current.realm ?? "").trim().toLowerCase() !== (next.realm ?? "").trim().toLowerCase()
    || current.metrics.configured !== next.metrics.configured
    || current.traces.configured !== next.traces.configured;
}

function utf8ByteLength(value: string): number {
  return new TextEncoder().encode(value).byteLength;
}

function isPotentialSplunkCloudDestination(value: string): boolean {
  const trimmed = value.trim();
  if (splunkRealmPattern.test(trimmed.toLowerCase())) return true;
  let parsed: URL;
  try {
    parsed = new URL(trimmed);
  } catch {
    return false;
  }
  if (
    parsed.protocol !== "https:"
    || parsed.username !== ""
    || parsed.password !== ""
    || parsed.port !== ""
  ) return false;
  const hostname = parsed.hostname.toLowerCase();
  return hostname.endsWith(".observability.splunkcloud.com")
    || hostname.endsWith(".signalfx.com");
}

function signalRow(label: string, signal: SplunkExportSignalStatus | undefined): SignalRow {
  if (!signal) {
    return { detail: "No activity", label, status: "Waiting for Observer", tone: "idle" };
  }
  const detail = `${formatCount(signal.exportedItems, label === "Metrics" ? "point" : "span")} · ${formatCount(signal.exportedBatches, "batch", "batches")}`;
  if (!signal.enabled) {
    return { detail, label, status: "Remote export off", tone: "idle" };
  }
  if (signal.lastExport && !signal.lastExport.success) {
    return {
      detail,
      label,
      status: signal.lastExport.error ? `Failed: ${signal.lastExport.error}` : "Last export failed",
      tone: "error",
    };
  }
  if (signal.lastExport?.success) {
    return {
      detail,
      label,
      status: `Last export ${formatTime(signal.lastExport.time)}`,
      tone: signal.failedBatches > 0 ? "warning" : "success",
    };
  }
  return { detail, label, status: "Waiting for telemetry", tone: "idle" };
}

function formatCount(value: number, singular: string, plural = `${singular}s`): string {
  return `${value.toLocaleString()} ${value === 1 ? singular : plural}`;
}

function formatTime(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? value
    : date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

function parseFreeAccountRegion(value: unknown): string | undefined {
  if (typeof value !== "string") return undefined;
  return freeAccountRegions.has(value) ? value : undefined;
}

function parseFreeAccountResult(value: unknown): FreeAccountResult | undefined {
  if (typeof value !== "object" || value === null) return undefined;
  const result = value as Record<string, unknown>;
  const realm = typeof result.realm === "string" ? result.realm.trim().toLowerCase() : "";
  const region = parseFreeAccountRegion(result.region);
  const expectedRealm = region === undefined ? undefined : freeAccountRealmByRegion.get(region);
  return typeof result.intakeAcknowledged === "boolean"
    && region !== undefined
    && realm === expectedRealm
    ? { intakeAcknowledged: result.intakeAcknowledged, realm, region }
    : undefined;
}

function normalizeNamePart(value: string): string {
  return value.trim().replace(/\s+/g, " ");
}

function isValidNamePart(value: string, maxLength: number): boolean {
  return value.length > 0 && value.length <= maxLength;
}

function isValidEmail(value: string): boolean {
  return value.length <= maxFreeAccountEmailLength
    && /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value);
}

function isOutcomeUnknown(error: unknown): boolean {
  if (error instanceof FreeAccountOutcomeUnknownError) return true;
  if (isObserverHostCloudTimeoutError(error)) return true;
  if (typeof error !== "object" || error === null) return false;
  const metadata = error as { code?: unknown; retrySafe?: unknown };
  return metadata.retrySafe === false || metadata.code === "outcome_unknown";
}

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof Error && error.message.trim() !== "" ? error.message : fallback;
}
