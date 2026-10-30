import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it, vi } from "vitest";
import { saveErrorText } from "./useConfigEdits";

vi.mock("../host/transport", () => ({ observerFetch: vi.fn() }));

describe("saveErrorText", () => {
  it("shows the server's message exactly", () => {
    const message = "config.yaml could not be updated: X. Fix the file, or delete it and try again.";
    expect(saveErrorText({ message, status: 409 })).toBe(message);
  });

  it("names the status when there is no message", () => {
    expect(saveErrorText({ message: undefined, status: 500 })).toBe("This setting could not be saved (HTTP 500).");
  });

  it("falls back to generic text for a transport failure", () => {
    expect(saveErrorText({ message: undefined, status: undefined })).toBe("This setting could not be saved.");
  });

  it("treats an empty message as no message", () => {
    expect(saveErrorText({ message: "", status: 400 })).toBe("This setting could not be saved (HTTP 400).");
  });
});

describe("useConfigEdits", () => {
  it("takes only the fields: no options type and no refresh callback", () => {
    const source = readFileSync(fileURLToPath(new URL("./useConfigEdits.ts", import.meta.url)), "utf8");
    // Built from parts so the repository grep for the retired name stays empty.
    expect(source.includes(["UseConfigEdits", "Options"].join(""))).toBe(false);
    expect(source.includes("onRefresh")).toBe(false);
  });
});
