import { useState } from "react";
import { PageShell } from "../../shell/PageShell";
import { useMyEvents } from "../../api/calendar";
import { useCalendarFilterStore } from "../../store/calendarFilterStore";
import { CalendarView } from "./CalendarView";
import { EventDetailModal } from "./EventDetailModal";

function monthRange(): { start: string; end: string } {
  const now = new Date();
  const start = new Date(now.getFullYear(), now.getMonth() - 1, 1);
  const end = new Date(now.getFullYear(), now.getMonth() + 2, 0);
  return {
    start: start.toISOString().slice(0, 10) + "T00:00:00",
    end: end.toISOString().slice(0, 10) + "T23:59:59",
  };
}

export default function MyCalendar() {
  const [range, setRange] = useState(monthRange);
  const { data: events = [], isFetching } = useMyEvents(range.start, range.end);
  const setSelectedEventId = useCalendarFilterStore(
    (s) => s.setSelectedEventId,
  );

  return (
    <PageShell title="내 캘린더" subtitle="내가 소유하거나 초대받은 일정">
      <CalendarView
        events={events}
        loading={isFetching}
        onEventClick={setSelectedEventId}
        onDatesSet={(s, e) =>
          setRange({
            start: s.toISOString().slice(0, 19),
            end: e.toISOString().slice(0, 19),
          })
        }
      />
      <EventDetailModal />
    </PageShell>
  );
}
