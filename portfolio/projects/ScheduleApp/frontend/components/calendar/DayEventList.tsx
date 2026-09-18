"use client";

import React from "react";
import { CalendarEvent } from "@/lib/types";
import { sortCalendarEvents } from "@/lib/sortEvents";
import EventCard from "./EventCard";

interface DayEventListProps {
  selectedDate: Date | null;
  events: CalendarEvent[];
  onEventClick: (event: CalendarEvent) => void;
}

export default function DayEventList({
  selectedDate,
  events,
  onEventClick,
}: DayEventListProps) {
  if (!selectedDate) {
    return (
      <div className="p-6 text-center text-sm text-txt-secondary">
        날짜를 선택하여 일정을 확인하세요
      </div>
    );
  }

  const dateStr = selectedDate.toLocaleDateString("ko-KR", {
    year: "numeric",
    month: "long",
    day: "numeric",
    weekday: "long",
  });

  // Filter events for the selected date
  const rawDayEvents = events.filter((event) => {
    const eventStart = new Date(event.start_dt);
    const eventEnd = new Date(event.end_dt);
    const dayStart = new Date(selectedDate);
    dayStart.setHours(0, 0, 0, 0);
    const dayEnd = new Date(selectedDate);
    dayEnd.setHours(23, 59, 59, 999);

    return eventStart <= dayEnd && eventEnd >= dayStart;
  });

  const dayEvents = sortCalendarEvents(rawDayEvents);

  return (
    <div className={`flex-1 bg-bg-primary flex flex-col ${dayEvents.length > 0 ? "overflow-y-auto" : "overflow-hidden"}`}>
      <div className="px-4 py-3 bg-bg-primary border-b border-border sticky top-0 z-10">
        <h2 className="text-sm font-semibold text-txt-primary">{dateStr}</h2>
        <p className="text-xs text-txt-secondary mt-0.5">
          {dayEvents.length === 0
            ? "일정 없음"
            : `${dayEvents.length}개의 일정`}
        </p>
      </div>
      <div className="flex-1 p-4 space-y-2">
        {dayEvents.length === 0 ? (
          <div className="h-full flex flex-col items-center justify-center py-20 text-center">
            <svg
              className="w-16 h-16 text-txt-secondary opacity-30 mb-3"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={1.5}
                d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z"
              />
            </svg>
            <p className="text-sm text-txt-secondary">이 날에 일정이 없습니다</p>
          </div>
        ) : (
          dayEvents.map((event) => (
            <EventCard key={event.event_id} event={event} onClick={onEventClick} />
          ))
        )}
      </div>
    </div>
  );
}
