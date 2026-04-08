import { AppView } from "./AppView";
import { useTelemetry } from "./telemetry";

/** Root component that wires up the telemetry WebSocket and renders the app. */
export function App() {
  const telemetry = useTelemetry();

  return <AppView telemetry={telemetry} />;
}
