// ============================================================
// Events CRUD Hook (empno-based, visibility filtering)
// ============================================================

"use client";

import { useState, useCallback } from "react";
import api from "@/lib/api";
import { CalendarEvent, EventCreateRequest, EventUpdateRequest, ApiResponse } from "@/lib/types";

export function useEvents() {
  const [events, setEvents] = useState<CalendarEvent[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchEvents = useCallback(
    async (empno: number, start: string, end: string) => {
      setLoading(true);
      setError(null);
      try {
        const { data } = await api.get<ApiResponse<CalendarEvent[]>>("/events", {
          params: { empno, start, end },
        });
        const list = data.data ?? data;
        setEvents(Array.isArray(list) ? list : []);
        return Array.isArray(list) ? list : [];
      } catch (err) {
        const message =
          err instanceof Error ? err.message : "Failed to fetch events";
        setError(message);
        return [];
      } finally {
        setLoading(false);
      }
    },
    []
  );

  const createEvent = useCallback(
    async (empno: number, eventData: EventCreateRequest): Promise<CalendarEvent | null> => {
      setError(null);
      try {
        const { data } = await api.post<ApiResponse<CalendarEvent>>(
          `/events?empno=${empno}`,
          eventData
        );
        const created = data.data ?? data;
        setEvents((prev) => [...prev, created as CalendarEvent]);
        return created as CalendarEvent;
      } catch (err) {
        const message =
          err instanceof Error ? err.message : "Failed to create event";
        setError(message);
        return null;
      }
    },
    []
  );

  const updateEvent = useCallback(
    async (
      empno: number,
      eventId: number,
      eventData: EventUpdateRequest
    ): Promise<CalendarEvent | null> => {
      setError(null);
      try {
        const { data } = await api.put<ApiResponse<CalendarEvent>>(
          `/events/${eventId}?empno=${empno}`,
          eventData
        );
        const updated = data.data ?? data;
        setEvents((prev) =>
          prev.map((e) => (e.event_id === eventId ? (updated as CalendarEvent) : e))
        );
        return updated as CalendarEvent;
      } catch (err) {
        const message =
          err instanceof Error ? err.message : "Failed to update event";
        setError(message);
        return null;
      }
    },
    []
  );

  const deleteEvent = useCallback(
    async (empno: number, eventId: number): Promise<boolean> => {
      setError(null);
      try {
        await api.delete(`/events/${eventId}?empno=${empno}`);
        setEvents((prev) => prev.filter((e) => e.event_id !== eventId));
        return true;
      } catch (err) {
        const message =
          err instanceof Error ? err.message : "Failed to delete event";
        setError(message);
        return false;
      }
    },
    []
  );

  return {
    events,
    loading,
    error,
    fetchEvents,
    createEvent,
    updateEvent,
    deleteEvent,
  };
}
