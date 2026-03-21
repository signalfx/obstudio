import type { User } from "@observer/shared";

const allUsers: User[] = [
  {
    firstName: "Ada",
    lastName: "Lovelace",
  },
  {
    firstName: "Grace",
    lastName: "Hopper",
  },
  {
    firstName: "Margaret",
    lastName: "Hamilton",
  },
  {
    firstName: "Alan",
    lastName: "Turing",
  },
  {
    firstName: "Katherine",
    lastName: "Johnson",
  },
  {
    firstName: "Donald",
    lastName: "Knuth",
  },
  {
    firstName: "Barbara",
    lastName: "Liskov",
  },
  {
    firstName: "Edsger",
    lastName: "Dijkstra",
  },
];

export function getInitialUsers(): User[] {
  return allUsers.slice(0, 1);
}

export function getProgressiveUsers(step: number): User[] {
  const safeStep = Math.max(step, 1);
  const count = Math.min(getInitialUsers().length + safeStep, allUsers.length);
  return allUsers.slice(0, count);
}
