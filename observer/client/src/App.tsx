import { AppView } from "./AppView";
import { useUsers } from "./useUsers";

export function App() {
  const { error, isLoading, users } = useUsers();

  return <AppView error={error} isLoading={isLoading} users={users} />;
}
