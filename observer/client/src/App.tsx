import { useEffect, useState } from "react";
import type { User } from "@observer/shared";

export function App() {
  const [users, setUsers] = useState<User[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let isActive = true;

    const loadUsers = async () => {
      try {
        const response = await fetch("/api/users");

        if (!response.ok) {
          throw new Error(`Request failed with status ${response.status}`);
        }

        const payload: User[] = await response.json();

        if (!isActive) {
          return;
        }

        setUsers(payload);
        setError(null);
      } catch (caughtError) {
        if (!isActive) {
          return;
        }

        const message = caughtError instanceof Error
          ? caughtError.message
          : "Unknown error";
        setError(message);
      } finally {
        if (isActive) {
          setIsLoading(false);
        }
      }
    };

    void loadUsers();

    return () => {
      isActive = false;
    };
  }, []);

  return (
    <main className="app-shell">
      <section className="hero">
        <p className="eyebrow">Observer</p>
        <h1>Shared types now drive both the API and the React client.</h1>
        <p className="lede">
          The server returns a typed user list from <code>/api/users</code>, and
          this client renders the same shared data shape.
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
