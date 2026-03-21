import type { User } from "@observer/shared";

type UsersTabProps = {
  error: string | null;
  isLoading: boolean;
  users: User[];
};

export function UsersTab({ error, isLoading, users }: UsersTabProps) {
  return (
    <section className="tab-panel" role="tabpanel">
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
  );
}
