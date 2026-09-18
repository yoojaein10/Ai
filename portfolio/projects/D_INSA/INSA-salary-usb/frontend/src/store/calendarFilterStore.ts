import { create } from "zustand";
import type { EventType } from "../api/calendar";

export type ViewMode = "dayGridMonth" | "timeGridWeek" | "timeGridDay";

interface CalendarFilterState {
  activeCalendarIds: number[] | null; // null = all
  eventTypes: EventType[] | null; // null = all
  viewMode: ViewMode;
  selectedEventId: number | null;
  deptId: number | null; // null = my dept

  setActiveCalendarIds: (ids: number[] | null) => void;
  toggleCalendarId: (id: number) => void;
  setEventTypes: (types: EventType[] | null) => void;
  toggleEventType: (t: EventType) => void;
  setViewMode: (v: ViewMode) => void;
  setSelectedEventId: (id: number | null) => void;
  setDeptId: (id: number | null) => void;
  reset: () => void;
}

const initialState = {
  activeCalendarIds: null as number[] | null,
  eventTypes: null as EventType[] | null,
  viewMode: "dayGridMonth" as ViewMode,
  selectedEventId: null as number | null,
  deptId: null as number | null,
};

export const useCalendarFilterStore = create<CalendarFilterState>((set) => ({
  ...initialState,

  setActiveCalendarIds: (ids) => set({ activeCalendarIds: ids }),
  toggleCalendarId: (id) =>
    set((s) => {
      const current = s.activeCalendarIds ?? [];
      const next = current.includes(id)
        ? current.filter((x) => x !== id)
        : [...current, id];
      return { activeCalendarIds: next };
    }),
  setEventTypes: (types) => set({ eventTypes: types }),
  toggleEventType: (t) =>
    set((s) => {
      const current = s.eventTypes ?? [];
      const next = current.includes(t)
        ? current.filter((x) => x !== t)
        : [...current, t];
      return { eventTypes: next };
    }),
  setViewMode: (v) => set({ viewMode: v }),
  setSelectedEventId: (id) => set({ selectedEventId: id }),
  setDeptId: (id) => set({ deptId: id }),
  reset: () => set({ ...initialState }),
}));
