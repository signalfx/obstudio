import { AppView } from "./AppView";
import { useTelemetry } from "./telemetry";

export function App() {
  const telemetry = useTelemetry();

  return <AppView telemetry={telemetry} />;
}
