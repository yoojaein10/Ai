import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import apiClient from "./client";

export type CalendarScope = "COMPANY" | "DEPT" | "PERSONAL";
export type EventType = "MANUAL" | "LEAVE" | "TRAVEL" | "MEETING" | "OTHER";
export type SourceType = "APPROVAL_DOC" | "MANUAL";
export type Visibility = "PUBLIC" | "DEPT" | "PRIVATE";
export type ParticipantRole = "ORGANIZER" | "REQUIRED" | "OPTIONAL";
export type ParticipantResponseValue =
  | "PENDING"
  | "ACCEPTED"
  | "DECLINED"
  | "TENTATIVE";

export interface Calendar {
  id: number;
  name: string;
  color_hex: string;
  scope: CalendarScope;
  scope_ref: number | null;
  is_default: boolean;
  created_by: number | null;
  created_at: string | null;
}

export interface Participant {
  id: number;
  event_id: number;
  emp_id: number;
  emp_name: string | null;
  role: ParticipantRole;
  response: ParticipantResponseValue;
}

export interface CalendarEvent {
  id: number;
  calendar_id: number;
  calendar_name: string | null;
  calendar_color: string | null;
  title: string;
  description: string | null;
  event_type: EventType;
  source_type: SourceType;
  source_ref: number | null;
  start_at: string;
  end_at: string;
  all_day: boolean;
  owner_id: number;
  owner_name: string | null;
  location: string | null;
  visibility: Visibility;
  created_at: string | null;
  updated_at: string | null;
  participants: Participant[];
}

export interface CreateCalendarBody {
  name: string;
  color_hex?: string;
  scope?: CalendarScope;
  scope_ref?: number | null;
  is_default?: boolean;
}

export interface UpdateCalendarBody {
  name?: string;
  color_hex?: string;
  is_default?: boolean;
}

export interface CreateEventBody {
  calendar_id: number;
  title: string;
  description?: string | null;
  event_type?: EventType;
  start_at: string;
  end_at: string;
  all_day?: boolean;
  location?: string | null;
  visibility?: Visibility;
  participant_emp_ids?: number[];
}

export interface UpdateEventBody {
  calendar_id?: number;
  title?: string;
  description?: string | null;
  event_type?: EventType;
  start_at?: string;
  end_at?: string;
  all_day?: boolean;
  location?: string | null;
  visibility?: Visibility;
}

export interface EventQuery {
  start: string;
  end: string;
  calendar_ids?: number[];
  event_types?: EventType[];
  owner_id?: number;
}

// ── Queries ───────────────────────────────────────────────

export function useCalendars() {
  return useQuery({
    queryKey: ["calendar", "calendars"],
    queryFn: async () => {
      const { data } = await apiClient.get<Calendar[]>("/calendar/calendars");
      return data;
    },
  });
}

export function useEvents(q: EventQuery, enabled = true) {
  return useQuery({
    queryKey: ["calendar", "events", q],
    enabled,
    queryFn: async () => {
      const { data } = await apiClient.get<CalendarEvent[]>(
        "/calendar/events",
        { params: q }
      );
      return data;
    },
  });
}

export function useMyEvents(start: string, end: string, enabled = true) {
  return useQuery({
    queryKey: ["calendar", "events", "me", start, end],
    enabled,
    queryFn: async () => {
      const { data } = await apiClient.get<CalendarEvent[]>(
        "/calendar/events/me",
        { params: { start, end } }
      );
      return data;
    },
  });
}

export function useDeptEvents(
  start: string,
  end: string,
  deptId?: number,
  enabled = true
) {
  return useQuery({
    queryKey: ["calendar", "events", "dept", start, end, deptId ?? "self"],
    enabled,
    queryFn: async () => {
      const { data } = await apiClient.get<CalendarEvent[]>(
        "/calendar/events/dept",
        {
          params: { start, end, ...(deptId ? { dept_id: deptId } : {}) },
        }
      );
      return data;
    },
  });
}

export function useEvent(eventId: number | null) {
  return useQuery({
    queryKey: ["calendar", "event", eventId],
    enabled: eventId !== null,
    queryFn: async () => {
      const { data } = await apiClient.get<CalendarEvent>(
        `/calendar/events/${eventId}`
      );
      return data;
    },
  });
}

// ── Mutations ─────────────────────────────────────────────

function invalidateEventQueries(qc: ReturnType<typeof useQueryClient>) {
  qc.invalidateQueries({ queryKey: ["calendar", "events"] });
  qc.invalidateQueries({ queryKey: ["calendar", "event"] });
}

export function useCreateCalendar() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (body: CreateCalendarBody) => {
      const { data } = await apiClient.post<Calendar>(
        "/calendar/calendars",
        body
      );
      return data;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["calendar", "calendars"] });
    },
  });
}

export function useUpdateCalendar() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({
      id,
      body,
    }: {
      id: number;
      body: UpdateCalendarBody;
    }) => {
      const { data } = await apiClient.put<Calendar>(
        `/calendar/calendars/${id}`,
        body
      );
      return data;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["calendar", "calendars"] });
      invalidateEventQueries(qc);
    },
  });
}

export function useDeleteCalendar() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (id: number) => {
      await apiClient.delete(`/calendar/calendars/${id}`);
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["calendar", "calendars"] });
      invalidateEventQueries(qc);
    },
  });
}

export function useCreateEvent() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (body: CreateEventBody) => {
      const { data } = await apiClient.post<CalendarEvent>(
        "/calendar/events",
        body
      );
      return data;
    },
    onSuccess: () => invalidateEventQueries(qc),
  });
}

export function useUpdateEvent() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({
      id,
      body,
    }: {
      id: number;
      body: UpdateEventBody;
    }) => {
      const { data } = await apiClient.put<CalendarEvent>(
        `/calendar/events/${id}`,
        body
      );
      return data;
    },
    onSuccess: () => invalidateEventQueries(qc),
  });
}

export function useDeleteEvent() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (id: number) => {
      await apiClient.delete(`/calendar/events/${id}`);
    },
    onSuccess: () => invalidateEventQueries(qc),
  });
}

export function useAddParticipants() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({
      eventId,
      empIds,
      role = "REQUIRED",
    }: {
      eventId: number;
      empIds: number[];
      role?: ParticipantRole;
    }) => {
      const { data } = await apiClient.post<Participant[]>(
        `/calendar/events/${eventId}/participants`,
        { emp_ids: empIds, role }
      );
      return data;
    },
    onSuccess: () => invalidateEventQueries(qc),
  });
}

export function useRespondParticipant() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({
      eventId,
      response,
    }: {
      eventId: number;
      response: ParticipantResponseValue;
    }) => {
      const { data } = await apiClient.post<Participant>(
        `/calendar/events/${eventId}/participants/respond`,
        { response }
      );
      return data;
    },
    onSuccess: () => invalidateEventQueries(qc),
  });
}
