import { useEffect, useState } from "react";
import type { User } from "@observer/shared";

type UseUsersResult = {
  error: string | null;
  isLoading: boolean;
  users: User[];
};

export function useUsers(): UseUsersResult {
  const [users, setUsers] = useState<User[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let isActive = true;
    let reconnectTimer: number | null = null;
    let socket: WebSocket | null = null;

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

    const connect = () => {
      socket = new WebSocket(`${window.location.protocol === "https:" ? "wss" : "ws"}://${window.location.host}/api/ws/`);

      socket.addEventListener("message", (event) => {
        if (!isActive) {
          return;
        }

        try {
          const payload: User[] = JSON.parse(event.data) as User[];
          setUsers(payload);
          setError(null);
          setIsLoading(false);
        } catch {
          setError("Received invalid WebSocket payload.");
        }
      });

      socket.addEventListener("close", () => {
        if (!isActive) {
          return;
        }

        reconnectTimer = window.setTimeout(connect, 1000);
      });

      socket.addEventListener("error", () => {
        socket?.close();
      });
    };

    void loadUsers();
    connect();

    return () => {
      isActive = false;
      if (reconnectTimer !== null) {
        window.clearTimeout(reconnectTimer);
      }

      socket?.close();
    };
  }, []);

  return { error, isLoading, users };
}
