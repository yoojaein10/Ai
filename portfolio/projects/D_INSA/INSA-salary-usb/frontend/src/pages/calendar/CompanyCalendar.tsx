import { useState } from "react";
import { Button, Checkbox, Space, Typography } from "antd";
import { PlusOutlined } from "@ant-design/icons";
import { PageShell } from "../../shell/PageShell";
import {
  useCalendars,
  useEvents,
  type EventType,
} from "../../api/calendar";
import { useCalendarFilterStore } from "../../store/calendarFilterStore";
import { CalendarView } from "./CalendarView";
import { EventDetailModal } from "./EventDetailModal";
import { CreateEventModal } from "./CreateEventModal";

const EVENT_TYPE_OPTIONS: { value: EventType; label: string }[] = [
  { value: "LEAVE", label: "휴가" },
  { value: "TRAVEL", label: "출장" },
  { value: "MEETING", label: "회의" },
  { value: "MANUAL", label: "일반" },
  { value: "OTHER", label: "기타" },
];

function monthRange(): { start: string; end: string } {
  const now = new Date();
  const start = new Date(now.getFullYear(), now.getMonth() - 1, 1);
  const end = new Date(now.getFullYear(), now.getMonth() + 2, 0);
  return {
    start: start.toISOString().slice(0, 10) + "T00:00:00",
    end: end.toISOString().slice(0, 10) + "T23:59:59",
  };
}

export default function CompanyCalendar() {
  const { data: calendars = [] } = useCalendars();
  const activeCalendarIds = useCalendarFilterStore(
    (s) => s.activeCalendarIds,
  );
  const toggleCalendarId = useCalendarFilterStore((s) => s.toggleCalendarId);
  const eventTypes = useCalendarFilterStore((s) => s.eventTypes);
  const toggleEventType = useCalendarFilterStore((s) => s.toggleEventType);
  const setSelectedEventId = useCalendarFilterStore(
    (s) => s.setSelectedEventId,
  );

  const [range, setRange] = useState(monthRange);
  const [createOpen, setCreateOpen] = useState(false);
  const [pendingRange, setPendingRange] = useState<{
    start: Date;
    end: Date;
  } | null>(null);

  const { data: events = [], isFetching } = useEvents({
    start: range.start,
    end: range.end,
    calendar_ids: activeCalendarIds ?? undefined,
    event_types: eventTypes ?? undefined,
  });

  const handleDatesSet = (start: Date, end: Date) => {
    setRange({
      start: start.toISOString().slice(0, 19),
      end: end.toISOString().slice(0, 19),
    });
  };

  const handleDateSelect = (start: Date, end: Date) => {
    setPendingRange({ start, end });
    setCreateOpen(true);
  };

  return (
    <PageShell
      title="회사 캘린더"
      subtitle="전사 공유 일정"
      actions={
        <Button
          type="primary"
          icon={<PlusOutlined />}
          onClick={() => {
            setPendingRange(null);
            setCreateOpen(true);
          }}
        >
          이벤트 추가
        </Button>
      }
      toolbar={
        <Space size="large" wrap>
          <div>
            <Typography.Text
              type="secondary"
              style={{ marginRight: 8, fontSize: 12 }}
            >
              캘린더
            </Typography.Text>
            <Space size={4} wrap>
              {calendars.map((c) => {
                const checked =
                  activeCalendarIds === null ||
                  activeCalendarIds.includes(c.id);
                return (
                  <Checkbox
                    key={c.id}
                    checked={checked}
                    onChange={() => toggleCalendarId(c.id)}
                  >
                    <span
                      style={{
                        display: "inline-block",
                        width: 8,
                        height: 8,
                        borderRadius: 4,
                        background: c.color_hex,
                        marginRight: 4,
                        verticalAlign: "middle",
                      }}
                    />
                    {c.name}
                  </Checkbox>
                );
              })}
            </Space>
          </div>
          <div>
            <Typography.Text
              type="secondary"
              style={{ marginRight: 8, fontSize: 12 }}
            >
              구분
            </Typography.Text>
            <Space size={4} wrap>
              {EVENT_TYPE_OPTIONS.map((opt) => {
                const checked =
                  eventTypes === null || eventTypes.includes(opt.value);
                return (
                  <Checkbox
                    key={opt.value}
                    checked={checked}
                    onChange={() => toggleEventType(opt.value)}
                  >
                    {opt.label}
                  </Checkbox>
                );
              })}
            </Space>
          </div>
        </Space>
      }
    >
      <CalendarView
        events={events}
        loading={isFetching}
        onEventClick={setSelectedEventId}
        onDatesSet={handleDatesSet}
        onDateSelect={handleDateSelect}
      />
      <EventDetailModal />
      <CreateEventModal
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        calendars={calendars}
        defaultStart={pendingRange?.start ?? null}
        defaultEnd={pendingRange?.end ?? null}
      />
    </PageShell>
  );
}
