import { describe, expect, it } from "vitest";
import { resolveForm } from "../FormRegistry";

describe("resolveForm", () => {
  it("returns a component for each registered doc type", () => {
    for (const code of ["ATT_LEAVE", "ATT_FIELD", "TRAVEL_ORDER", "CONTRACT_LABOR"]) {
      expect(resolveForm(code)).toBeTruthy();
    }
  });

  it("falls back to placeholder for unknown code", () => {
    const known = resolveForm("ATT_LEAVE");
    const unknown = resolveForm("NONSENSE_CODE");
    expect(unknown).toBe(known); // all mapped to PlaceholderForm currently
  });

  it("falls back to placeholder for null/undefined", () => {
    const known = resolveForm("ATT_LEAVE");
    expect(resolveForm(null)).toBe(known);
    expect(resolveForm(undefined)).toBe(known);
    expect(resolveForm("")).toBe(known);
  });
});
