import { AppView } from "./AppView";
import { useTelemetry } from "./telemetry";
import { useUsers } from "./users";

export function App() {
  const { error, isLoading, users } = useUsers();
  const telemetry = useTelemetry();

  return <AppView error={error} isLoading={isLoading} telemetry={telemetry} users={users} />;
}
