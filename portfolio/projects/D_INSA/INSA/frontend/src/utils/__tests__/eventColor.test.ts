import { describe, expect, it } from "vitest";
import {
  colorForEventType,
  colorForSubtype,
  resolveEventColor,
} from "../eventColor";

describe("colorForEventType", () => {
  it("maps known event types to their colors", () => {
    expect(colorForEventType("LEAVE")).toBe("#1677ff");
    expect(colorForEventType("TRAVEL")).toBe("#ff4d4f");
    expect(colorForEventType("MEETING")).toBe("#8c8c8c");
    expect(colorForEventType("MANUAL")).toBe("#1677ff");
    expect(colorForEventType("OTHER")).toBe("#bfbfbf");
  });
});

describe("colorForSubtype", () => {
  it("maps the 8 documented subtypes", () => {
    expect(colorForSubtype("annual")).toBe("#1677ff");
    expect(colorForSubtype("half")).toBe("#91caff");
    expect(colorForSubtype("public")).toBe("#52c41a");
    expect(colorForSubtype("sick")).toBe("#fa8c16");
    expect(colorForSubtype("condolence")).toBe("#722ed1");
    expect(colorForSubtype("field")).toBe("#fadb14");
    expect(colorForSubtype("travel")).toBe("#ff4d4f");
    expect(colorForSubtype("meeting")).toBe("#8c8c8c");
  });

  it("returns null for unknown / falsy subtypes", () => {
    expect(colorForSubtype(null)).toBeNull();
    expect(colorForSubtype(undefined)).toBeNull();
    expect(colorForSubtype("")).toBeNull();
    expect(colorForSubtype("nonsense")).toBeNull();
  });
});

describe("resolveEventColor", () => {
  it("prefers subtype over calendar over event type", () => {
    expect(resolveEventColor("LEAVE", "#abcdef", "sick")).toBe("#fa8c16");
  });

  it("falls back to calendar color when no subtype", () => {
    expect(resolveEventColor("LEAVE", "#abcdef", null)).toBe("#abcdef");
    expect(resolveEventColor("LEAVE", "#abcdef")).toBe("#abcdef");
  });

  it("falls back to event-type default when calendar color missing", () => {
    expect(resolveEventColor("TRAVEL", null)).toBe("#ff4d4f");
    expect(resolveEventColor("MEETING")).toBe("#8c8c8c");
  });
});
