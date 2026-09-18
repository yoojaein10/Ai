"use client";

import React, { useMemo } from "react";
import FullCalendar from "@fullcalendar/react";
import dayGridPlugin from "@fullcalendar/daygrid";
import timeGridPlugin from "@fullcalendar/timegrid";
import interactionPlugin from "@fullcalendar/interaction";
import { CalendarEvent } from "@/lib/types";
import { getTypeColor } from "@/lib/eventColors";
import { getEventGroupOrder } from "@/lib/sortEvents";
import type { DayCellContentArg, DatesSetArg, EventContentArg } from "@fullcalendar/core";


interface MonthViewProps {
  events: CalendarEvent[];
  selectedDate: Date | null;
  onDateClick: (date: Date) => void;
  onDatesSet: (startDate: Date, endDate: Date) => void;
  calendarRef: React.RefObject<FullCalendar | null>;
  viewType?: "dayGridMonth" | "timeGridWeek";
  holidays?: { date: string; name: string }[];
}

export default function MonthView({
  events,
  selectedDate,
  onDateClick,
  onDatesSet,
  calendarRef,
  viewType = "dayGridMonth",
  holidays = [],
}: MonthViewProps) {
  const holidayMap = useMemo(() => {
    const map = new Map<string, string>();
    holidays.forEach(({ date, name }) => map.set(date, name));
    return map;
  }, [holidays]);
  // CalendarEvent → FullCalendar EventInput 변환
  const fcEvents = useMemo(() => {
    return events.map((ev) => {
      const isAllDay = ev.is_all_day;
      let start = ev.start_dt;
      let end = ev.end_dt;

      // 종일 이벤트: 날짜만 추출하여 타임존 이슈 방지
      // FullCalendar end는 exclusive → DB end_dt에 +1일
      if (isAllDay) {
        start = ev.start_dt.split(" ")[0];
        const endDateStr = ev.end_dt.split(" ")[0];
        const [y, m, d] = endDateStr.split("-").map(Number);
        const endDate = new Date(y, m - 1, d + 1);
        end = `${endDate.getFullYear()}-${String(endDate.getMonth() + 1).padStart(2, "0")}-${String(endDate.getDate()).padStart(2, "0")}`;
      }

      const forceColor     = ev._forceColor;
      const forceTextColor = ev._forceTextColor;
      const typeColor = forceColor ? null : getTypeColor(ev.title);
      const bg    = forceColor     ?? typeColor?.bg   ?? (ev.event_color || "#339AF0");
      const text  = forceTextColor ?? typeColor?.text ?? "#FFFFFF";

      // sortKey: 그룹(0~3) * 2 + 종일여부(0/1) → FullCalendar eventOrder 기준
      const sortKey = getEventGroupOrder(ev) * 2 + (isAllDay ? 0 : 1);

      return {
        id: String(ev.event_id),
        title: ev.title,
        start: start,
        end: end,
        allDay: isAllDay,
        backgroundColor: bg,
        borderColor: bg,
        extendedProps: {
          isAllDay: isAllDay,
          color: bg,
          textColor: text,
          sortKey,
        },
      };
    });
  }, [events]);

  // 요일/공휴일 색상 상수
  const DAY_COLORS = {
    sunday:  { normal: "#FF6B6B", selected: "#FF6B6B" },
    saturday: { normal: "#339AF0", selected: "#339AF0" },
    holiday: { normal: "#FF6B6B", selected: "#FF6B6B" },
  } as const;

  // 날짜 셀 커스텀 (숫자 + 공휴일명, 오늘/선택/요일 표시)
  const dayCellContent = (arg: DayCellContentArg) => {
    const isSelected =
      selectedDate &&
      arg.date.toDateString() === selectedDate.toDateString();
    const isToday = arg.isToday;
    const dow = arg.date.getDay(); // 0=일, 6=토

    const y = arg.date.getFullYear();
    const m = String(arg.date.getMonth() + 1).padStart(2, "0");
    const d = String(arg.date.getDate()).padStart(2, "0");
    const dateStr = `${y}-${m}-${d}`;
    const holidayName = holidayMap.get(dateStr);

    const isRed  = dow === 0 || !!holidayName;
    const isBlue = dow === 6 && !isRed;

    // 날짜 숫자 색상: 선택/오늘 상태일 때는 배경색으로 가리므로 흰색, 아니면 요일/공휴일 색
    const numberColor = isSelected || isToday
      ? undefined // className으로 처리
      : isRed  ? DAY_COLORS.sunday.normal
      : isBlue ? DAY_COLORS.saturday.normal
      : undefined;

    return (
      <div className="flex flex-col items-center w-full py-0.5">
        <span
          className={`text-sm w-7 h-7 flex items-center justify-center rounded-full transition-all font-medium
            ${isToday && !isSelected ? "bg-accent text-accent-contrast font-bold" : ""}
            ${isSelected ? "bg-txt-primary text-white font-bold" : ""}
            ${!isToday && !isSelected ? "" : ""}
          `}
          style={!isToday && !isSelected && numberColor ? { color: numberColor } : undefined}
        >
          {arg.dayNumberText.replace("일", "")}
        </span>
        {holidayName && (
          <span
            className="text-[9px] leading-tight truncate max-w-full px-0.5"
            style={{ color: DAY_COLORS.holiday.normal }}
          >
            {holidayName}
          </span>
        )}
      </div>
    );
  };

  // 시간 포맷: 분 없으면 "HH", 있으면 "HH:MM"
  const formatTime = (date: Date) => {
    const h = String(date.getHours()).padStart(2, '0');
    const m = date.getMinutes();
    return m === 0 ? h : `${h}:${String(m).padStart(2, '0')}`;
  };

  // 이벤트 렌더링 커스텀
  const eventContent = (arg: EventContentArg) => {
    const isAllDay   = arg.event.extendedProps.isAllDay;
    const color      = arg.event.extendedProps.color;
    const textColor  = arg.event.extendedProps.textColor as string ?? "#FFFFFF";

    if (isAllDay) {
      return (
        <div
          className="rounded px-1 py-0.5 text-[11px] leading-tight truncate w-full"
          style={{ backgroundColor: color, color: textColor }}
        >
          종일 {arg.event.title}
        </div>
      );
    } else {
      const start = arg.event.start;
      const end = arg.event.end;
      const timeStr = start && end
        ? `${formatTime(start)}~${formatTime(end)}`
        : start ? formatTime(start) : "";

      return (
        <div
          className="flex items-center gap-0.5 text-[10px] leading-tight truncate w-full pl-0.5"
          style={{ borderLeft: `2.5px solid ${color}` }}
        >
          <span className="text-txt-secondary shrink-0 tabular-nums">{timeStr}</span>
          <span className="text-txt-primary truncate font-medium">{arg.event.title}</span>
        </div>
      );
    }
  };

  const handleDateClick = (info: { date: Date }) => {
    onDateClick(info.date);
  };

  const handleDatesSet = (arg: DatesSetArg) => {
    onDatesSet(arg.start, arg.end);
  };

  return (
    <div className="fc-kakao-wrapper px-2 md:px-4 py-2 h-full">
      <FullCalendar
        ref={calendarRef as React.RefObject<FullCalendar>}
        plugins={[dayGridPlugin, timeGridPlugin, interactionPlugin]}
        initialView={viewType}
        locale="ko"
        headerToolbar={false}
        height="100%"
        fixedWeekCount={true}
        dayCellContent={dayCellContent}
        eventContent={eventContent}
        dateClick={handleDateClick}
        datesSet={handleDatesSet}
        events={fcEvents}
        dayMaxEvents={3}
        dayHeaderFormat={{ weekday: "short" }}
        eventDisplay="block"
        eventOrder={(a: any, b: any) => (a.extendedProps?.sortKey ?? 99) - (b.extendedProps?.sortKey ?? 99)}
      />
    </div>
  );
}
