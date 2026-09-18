import { useMemo, useRef } from "react";
import FullCalendar from "@fullcalendar/react";
import dayGridPlugin from "@fullcalendar/daygrid";
import timeGridPlugin from "@fullcalendar/timegrid";
import interactionPlugin from "@fullcalendar/interaction";
import type { EventClickArg, EventInput } from "@fullcalendar/core";
import type { CalendarEvent } from "../../api/calendar";
import { useCalendarFilterStore } from "../../store/calendarFilterStore";
import { resolveEventColor } from "../../utils/eventColor";

interface CalendarViewProps {
  events: CalendarEvent[];
  loading?: boolean;
  onEventClick?: (eventId: number) => void;
  onDatesSet?: (start: Date, end: Date) => void;
  onDateSelect?: (start: Date, end: Date, allDay: boolean) => void;
}

export function CalendarView({
  events,
  loading,
  onEventClick,
  onDatesSet,
  onDateSelect,
}: CalendarViewProps) {
  const viewMode = useCalendarFilterStore((s) => s.viewMode);
  const fcRef = useRef<FullCalendar>(null);

  const fcEvents: EventInput[] = useMemo(
    () =>
      events.map((e) => ({
        id: String(e.id),
        title: e.title,
        start: e.start_at,
        end: e.end_at,
        allDay: e.all_day,
        backgroundColor: resolveEventColor(e.event_type, e.calendar_color),
        borderColor: resolveEventColor(e.event_type, e.calendar_color),
        extendedProps: {
          ownerName: e.owner_name,
          eventType: e.event_type,
          calendarName: e.calendar_name,
        },
      })),
    [events],
  );

  const handleEventClick = (arg: EventClickArg) => {
    if (onEventClick) onEventClick(Number(arg.event.id));
  };

  return (
    <div
      className="insa-calendar-wrap"
      style={{
        background: "var(--color-surface, #fff)",
        borderRadius: 8,
        padding: 12,
        opacity: loading ? 0.6 : 1,
        transition: "opacity 120ms ease-out",
      }}
    >
      <FullCalendar
        ref={fcRef}
        plugins={[dayGridPlugin, timeGridPlugin, interactionPlugin]}
        initialView={viewMode}
        headerToolbar={{
          left: "prev,next today",
          center: "title",
          right: "dayGridMonth,timeGridWeek,timeGridDay",
        }}
        locale="ko"
        buttonText={{
          today: "오늘",
          month: "월",
          week: "주",
          day: "일",
        }}
        height="auto"
        dayMaxEvents={3}
        events={fcEvents}
        selectable={Boolean(onDateSelect)}
        select={(arg) =>
          onDateSelect?.(arg.start, arg.end, arg.allDay ?? false)
        }
        eventClick={handleEventClick}
        datesSet={(arg) => onDatesSet?.(arg.start, arg.end)}
        nowIndicator
        firstDay={1}
      />
    </div>
  );
}
