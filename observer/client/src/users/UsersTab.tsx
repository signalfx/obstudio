import type { User } from "@observer/shared";

type UsersTabProps = {
  error: string | null;
  isLoading: boolean;
  users: User[];
};

export function UsersTab({ error, isLoading, users }: UsersTabProps) {
  return (
    <section className="tab-panel" role="tabpanel">
      <div className="panel-toolbar">
        <div className="panel-toolbar__title">
          <span className="panel-toolbar__glyph" aria-hidden="true">
            U
          </span>
          <span>User directory</span>
        </div>
        <div className="panel-toolbar__meta">
          <span>{users.length} records</span>
          <span>{error === null ? "WebSocket healthy" : "Degraded"}</span>
        </div>
      </div>

      {isLoading ? <p className="status">Loading users from `/api/users`...</p> : null}
      {error !== null ? <p className="status error">Failed to load users: {error}</p> : null}
      {!isLoading && error === null ? (
        <ul className="user-list">
          {users.map((user) => (
            <li key={`${user.firstName}-${user.lastName}`} className="user-card">
              <div className="user-card__avatar" aria-hidden="true">
                {user.firstName.slice(0, 1)}
                {user.lastName.slice(0, 1)}
              </div>
              <div className="user-card__content">
                <span className="user-name">
                  {user.firstName} {user.lastName}
                </span>
                <span className="user-meta">Shared type payload mirrored from the server.</span>
              </div>
              <span className="user-status">online</span>
            </li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}
