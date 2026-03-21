import type { User } from "@observer/shared";

type AppViewProps = {
  error: string | null;
  isLoading: boolean;
  users: User[];
};

export function AppView({ error, isLoading, users }: AppViewProps) {
  return (
    <main className="app-shell">
      <section className="hero">
        <p className="eyebrow">Observer</p>
        <h1>Shared types now drive both the API and the React client.</h1>
        <p className="lede">
          The server returns a typed user list from <code>/api/users</code> and
          streams updates from <code>/api/ws/</code>; this client renders each
          new list as it arrives.
        </p>
        {isLoading ? <p className="status">Loading users...</p> : null}
        {error !== null ? <p className="status error">Failed to load users: {error}</p> : null}
        {!isLoading && error === null ? (
          <ul className="user-list">
            {users.map((user) => (
              <li key={`${user.firstName}-${user.lastName}`} className="user-card">
                <span className="user-name">
                  {user.firstName} {user.lastName}
                </span>
              </li>
            ))}
          </ul>
        ) : null}
      </section>
    </main>
  );
}
