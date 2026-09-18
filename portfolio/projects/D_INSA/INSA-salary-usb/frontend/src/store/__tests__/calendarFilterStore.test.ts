import { beforeEach, describe, expect, it } from "vitest";
import { useCalendarFilterStore } from "../calendarFilterStore";

const resetStore = () =>
  useCalendarFilterStore.setState({
    activeCalendarIds: null,
    eventTypes: null,
    viewMode: "dayGridMonth",
    selectedEventId: null,
    deptId: null,
  });

describe("calendarFilterStore", () => {
  beforeEach(() => {
    resetStore();
  });

  it("starts with null filters (meaning: all)", () => {
    const s = useCalendarFilterStore.getState();
    expect(s.activeCalendarIds).toBeNull();
    expect(s.eventTypes).toBeNull();
    expect(s.viewMode).toBe("dayGridMonth");
    expect(s.selectedEventId).toBeNull();
    expect(s.deptId).toBeNull();
  });

  it("setActiveCalendarIds replaces the list", () => {
    const { setActiveCalendarIds } = useCalendarFilterStore.getState();
    setActiveCalendarIds([1, 2]);
    expect(useCalendarFilterStore.getState().activeCalendarIds).toEqual([1, 2]);
    setActiveCalendarIds(null);
    expect(useCalendarFilterStore.getState().activeCalendarIds).toBeNull();
  });

  it("toggleCalendarId adds then removes", () => {
    const { toggleCalendarId } = useCalendarFilterStore.getState();
    toggleCalendarId(5);
    expect(useCalendarFilterStore.getState().activeCalendarIds).toEqual([5]);
    toggleCalendarId(7);
    expect(useCalendarFilterStore.getState().activeCalendarIds).toEqual([5, 7]);
    toggleCalendarId(5);
    expect(useCalendarFilterStore.getState().activeCalendarIds).toEqual([7]);
  });

  it("toggleEventType adds then removes", () => {
    const { toggleEventType } = useCalendarFilterStore.getState();
    toggleEventType("LEAVE");
    expect(useCalendarFilterStore.getState().eventTypes).toEqual(["LEAVE"]);
    toggleEventType("TRAVEL");
    expect(useCalendarFilterStore.getState().eventTypes).toEqual([
      "LEAVE",
      "TRAVEL",
    ]);
    toggleEventType("LEAVE");
    expect(useCalendarFilterStore.getState().eventTypes).toEqual(["TRAVEL"]);
  });

  it("setViewMode records the mode", () => {
    const { setViewMode } = useCalendarFilterStore.getState();
    setViewMode("timeGridWeek");
    expect(useCalendarFilterStore.getState().viewMode).toBe("timeGridWeek");
    setViewMode("timeGridDay");
    expect(useCalendarFilterStore.getState().viewMode).toBe("timeGridDay");
  });

  it("setSelectedEventId can open and close the modal", () => {
    const { setSelectedEventId } = useCalendarFilterStore.getState();
    setSelectedEventId(42);
    expect(useCalendarFilterStore.getState().selectedEventId).toBe(42);
    setSelectedEventId(null);
    expect(useCalendarFilterStore.getState().selectedEventId).toBeNull();
  });

  it("setDeptId and reset clears everything back to defaults", () => {
    const { setDeptId, toggleCalendarId, setViewMode, reset } =
      useCalendarFilterStore.getState();
    setDeptId(3);
    toggleCalendarId(9);
    setViewMode("timeGridWeek");
    expect(useCalendarFilterStore.getState().deptId).toBe(3);
    reset();
    const s = useCalendarFilterStore.getState();
    expect(s.deptId).toBeNull();
    expect(s.activeCalendarIds).toBeNull();
    expect(s.viewMode).toBe("dayGridMonth");
  });
});
