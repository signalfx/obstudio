// @vitest-environment happy-dom

import { act, renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { RegisteredWorkspace } from "../api/client";
import type { FilterClause } from "../FilterBar";
import { reposSharingService, resolveRepoService, useScopedClauses } from "./scope";

const checkout: RegisteredWorkspace = { name: "checkout-api", folder: "checkout-api", service: "checkout" };
const inventory: RegisteredWorkspace = { name: "inventory", folder: "inventory" };
const scratch: RegisteredWorkspace = { name: "scratch", folder: "scratch" };

describe("resolveRepoService", () => {
  it("uses the audit's service name first", () => {
    expect(resolveRepoService(checkout, ["checkout-api", "checkout"])).toEqual({ service: "checkout", source: "audit" });
  });

  it("falls back to a service named like the repo folder without an audit", () => {
    expect(resolveRepoService(inventory, ["checkout", "inventory"])).toEqual({ service: "inventory", source: "folder" });
  });

  it("scopes nothing when there is no audit and no matching service", () => {
    expect(resolveRepoService(scratch, ["checkout"])).toEqual({ service: null, source: "none" });
  });
});

describe("reposSharingService", () => {
  it("names other repos that resolve to the same service", () => {
    const fork: RegisteredWorkspace = { name: "checkout-api (2)", folder: "checkout-api", service: "checkout" };
    expect(reposSharingService(checkout, "checkout", [checkout, fork, inventory], ["inventory"])).toEqual(["checkout-api (2)"]);
  });

  it("counts a folder-name fallback as claiming the service", () => {
    const auditedInventory: RegisteredWorkspace = { name: "inventory-v2", folder: "inventory-v2", service: "inventory" };
    expect(reposSharingService(auditedInventory, "inventory", [auditedInventory, inventory], ["inventory"])).toEqual(["inventory"]);
  });

  it("reports nothing for an unscoped repo", () => {
    expect(reposSharingService(scratch, null, [scratch, inventory], [])).toEqual([]);
  });
});

describe("useScopedClauses", () => {
  const scope = (value: string): FilterClause => ({ key: "serviceName", op: "eq", value });
  const severity: FilterClause = { key: "severityDisplay", op: "eq", value: "ERROR" };

  it("starts with the repo's service chip", () => {
    const { result } = renderHook(() => useScopedClauses("checkout"));
    expect(result.current[0]).toEqual([scope("checkout")]);
  });

  it("uses the tab's own field for the repo chip", () => {
    const { result, rerender } = renderHook(({ service }) => useScopedClauses(service, "spanServiceName"), {
      initialProps: { service: "checkout" as string | null },
    });
    expect(result.current[0]).toEqual([{ key: "spanServiceName", op: "eq", value: "checkout" }]);
    act(() => result.current[1]([...result.current[0], scope("checkout")]));
    rerender({ service: "payments" });
    // Only the scoped field's chip moves; a root-service filter the user added stays.
    expect(result.current[0]).toEqual([{ key: "spanServiceName", op: "eq", value: "payments" }, scope("checkout")]);
  });

  it("starts empty when no repo service is known", () => {
    const { result } = renderHook(() => useScopedClauses(null));
    expect(result.current[0]).toEqual([]);
  });

  it("swaps only the repo chip when the repo changes and keeps the user's filters", () => {
    const { result, rerender } = renderHook(({ service }) => useScopedClauses(service), {
      initialProps: { service: "checkout" as string | null },
    });
    act(() => result.current[1]([...result.current[0], severity]));

    rerender({ service: "payments" });
    expect(result.current[0]).toEqual([scope("payments"), severity]);

    rerender({ service: null });
    expect(result.current[0]).toEqual([severity]);
  });

  it("adds the chip once the repo's service becomes known", () => {
    const { result, rerender } = renderHook(({ service }) => useScopedClauses(service), {
      initialProps: { service: null as string | null },
    });
    rerender({ service: "inventory" });
    expect(result.current[0]).toEqual([scope("inventory")]);
  });

  it("does not bring back a repo chip the user removed while the repo is unchanged", () => {
    const { result, rerender } = renderHook(({ service }) => useScopedClauses(service), {
      initialProps: { service: "checkout" as string | null },
    });
    act(() => result.current[1]([]));
    rerender({ service: "checkout" });
    expect(result.current[0]).toEqual([]);
  });

  it("does not duplicate a service chip the user already added for the new repo", () => {
    const { result, rerender } = renderHook(({ service }) => useScopedClauses(service), {
      initialProps: { service: "checkout" as string | null },
    });
    act(() => result.current[1]([scope("checkout"), scope("payments")]));
    rerender({ service: "payments" });
    expect(result.current[0]).toEqual([scope("payments")]);
  });
});
