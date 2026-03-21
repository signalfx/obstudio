import { AppView } from "./AppView";
import { useUsers } from "./users";

export function App() {
  const { error, isLoading, users } = useUsers();

  return <AppView error={error} isLoading={isLoading} users={users} />;
}
