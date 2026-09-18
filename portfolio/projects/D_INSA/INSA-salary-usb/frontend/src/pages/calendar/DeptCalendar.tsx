import { useState } from "react";
import { PageShell } from "../../shell/PageShell";
import { useDeptEvents } from "../../api/calendar";
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

export default function DeptCalendar() {
  const [range, setRange] = useState(monthRange);
  const deptId = useCalendarFilterStore((s) => s.deptId);
  const { data: events = [], isFetching } = useDeptEvents(
    range.start,
    range.end,
    deptId ?? undefined,
  );
  const setSelectedEventId = useCalendarFilterStore(
    (s) => s.setSelectedEventId,
  );

  return (
    <PageShell title="부서 캘린더" subtitle="소속 부서 구성원의 일정">
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
