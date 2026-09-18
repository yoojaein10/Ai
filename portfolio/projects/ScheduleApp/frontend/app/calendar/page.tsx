"use client";

import React, { useState, useRef, useCallback, useMemo, useEffect, Suspense } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import FullCalendar from "@fullcalendar/react";
import api, { syncKakaoICS, getHolidays } from "@/lib/api";
import { VACATION_KEYWORDS } from "@/lib/sortEvents";
import {
  CalendarEvent,
  User,
  EventCreateRequest,
  EventUpdateRequest,
  VISIBILITY_OPTIONS,
  ApiResponse,
} from "@/lib/types";
import { useEvents } from "@/hooks/useEvents";
import Header, { ViewMode } from "@/components/layout/Header";
import MonthView from "@/components/calendar/MonthView";
import DayEventList from "@/components/calendar/DayEventList";
import EventBottomSheet from "@/components/event/EventBottomSheet";
import EventDetail from "@/components/event/EventDetail";
import FAB from "@/components/ui/FAB";
import { useAccentColor, ACCENT_COLORS } from "@/components/accent-provider";
import { useTheme } from "next-themes";

function AccentColorDropdown() {
  const { accentColor, setAccentColor } = useAccentColor();
  const [open, setOpen] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);
  const allColors = [...ACCENT_COLORS, "#FFFFFF", "#000000"];

  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    if (open) document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, [open]);

  return (
    <div className="relative" ref={dropdownRef}>
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-2 w-full px-2 py-2 rounded-lg bg-bg-secondary hover:bg-bg-tertiary transition-colors"
      >
        <span
          className={`w-5 h-5 rounded-full shrink-0 ${accentColor === "#FFFFFF" ? "border border-border" : ""}`}
          style={{ backgroundColor: accentColor }}
        />
        <span className="text-sm text-txt-primary flex-1 text-left">테마 색상</span>
        <svg
          className={`w-4 h-4 text-txt-secondary transition-transform ${open ? "rotate-180" : ""}`}
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
          strokeWidth={2}
        >
          <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
        </svg>
      </button>
      {open && (
        <div className="absolute left-0 right-0 mt-1 p-2 bg-bg-primary border border-border rounded-lg shadow-lg z-50">
          <div className="grid grid-cols-7 gap-1.5">
            {allColors.map((color) => {
              const isSelected = accentColor === color;
              const isWhite = color === "#FFFFFF";
              return (
                <button
                  key={color}
                  onClick={() => {
                    setAccentColor(color);
                    setOpen(false);
                  }}
                  className={`w-full aspect-square rounded-full transition-all duration-150 hover:scale-110 ${
                    isSelected
                      ? "ring-2 ring-offset-1 ring-offset-bg-primary ring-txt-primary"
                      : ""
                  } ${isWhite ? "border border-border" : ""}`}
                  style={{ backgroundColor: color }}
                  title={color}
                />
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}

function CalendarContent() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const empnoParam = searchParams.get("empno");
  const empno = empnoParam ? parseInt(empnoParam, 10) : null;

  const calendarRef = useRef<FullCalendar | null>(null);
  const empnoFetchedRef = useRef(false);

  // State
  const [user, setUser] = useState<User | null>(null);
  const [selectedDate, setSelectedDate] = useState<Date | null>(new Date());
  const [currentMonth, setCurrentMonth] = useState("");
  const [visibilityFilter, setVisibilityFilter] = useState<string[]>([
    "company",
    "dept",
    "personal",
  ]);
  const [showVacation, setShowVacation] = useState(true);
  const [showNpl, setShowNpl] = useState(true);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [empnoChecked, setEmpnoChecked] = useState(false);
  const { theme, setTheme } = useTheme();

  const [showBottomSheet, setShowBottomSheet] = useState(false);
  const [showDetail, setShowDetail] = useState(false);
  const [editingEvent, setEditingEvent] = useState<CalendarEvent | null>(null);
  const [selectedEvent, setSelectedEvent] = useState<CalendarEvent | null>(null);
  const [refreshTrigger, setRefreshTrigger] = useState(0);
  const [viewMode, setViewMode] = useState<ViewMode>("month");
  const [holidays, setHolidays] = useState<{ date: string; name: string }[]>([]);

  // Hooks
  const {
    events,
    loading: eventsLoading,
    fetchEvents,
    createEvent,
    updateEvent,
    deleteEvent,
  } = useEvents();

  // Current date range for fetching
  const [dateRange, setDateRange] = useState<{ start: string; end: string } | null>(null);

  // URL에 empno가 없을 때 저장된 사번으로 1회 복구
  useEffect(() => {
    if (empnoParam || empnoFetchedRef.current) return;
    empnoFetchedRef.current = true;
    api
      .get<ApiResponse<{ empno: number | null }>>("/users/current-empno")
      .then((res) => {
        const d = (res.data.data ?? res.data) as { empno: number | null };
        if (d?.empno) {
          router.replace(`/calendar?empno=${d.empno}`);
        } else {
          setEmpnoChecked(true);
        }
      })
      .catch(() => setEmpnoChecked(true));
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Load user info
  useEffect(() => {
    if (!empno) return;
    api
      .get<ApiResponse<User>>(`/users/me`, { params: { empno } })
      .then((res) => {
        const userData = res.data.data ?? res.data;
        setUser(userData as User);
      })
      .catch((err) => {
        console.error("Failed to load user info:", err);
      });
  }, [empno]);

  // Fetch events when date range changes or sync triggered
  useEffect(() => {
    if (!empno || !dateRange) return;
    fetchEvents(empno, dateRange.start, dateRange.end);
  }, [empno, dateRange, fetchEvents, refreshTrigger]);

  // Fetch holidays when date range changes
  useEffect(() => {
    if (!dateRange) return;
    getHolidays(dateRange.start, dateRange.end)
      .then(setHolidays)
      .catch(() => {});
  }, [dateRange]);

  // 5분마다 카카오 ICS 자동 동기화 (배재욱 4220 전용)
  useEffect(() => {
    if (empno !== 4220) return;

    const autoSync = async () => {
      try {
        console.log("[AutoSync] 카카오 ICS 동기화 실행...");
        const result = await syncKakaoICS(empno);
        console.log("[AutoSync] 결과:", result);
        if (result.created > 0 || result.deleted > 0) {
          setRefreshTrigger((v) => v + 1);
        }
      } catch (e) {
        console.error("[AutoSync] 실패:", e);
      }
    };

    // 최초 즉시 실행 + 5분 간격 반복
    autoSync();
    const intervalId = setInterval(autoSync, 5 * 60 * 1000);
    return () => clearInterval(intervalId);
  }, [empno]);

  // 5분마다 이벤트 목록 자동 갱신 (모든 사용자)
  useEffect(() => {
    if (!empno || !dateRange) return;

    const intervalId = setInterval(() => {
      fetchEvents(empno, dateRange.start, dateRange.end);
    }, 5 * 60 * 1000);
    return () => clearInterval(intervalId);
  }, [empno, dateRange, fetchEvents]);

  const canSeeNpl = user?.grade === "총무이사" || user?.grade === "국장";

  // Filter events by visibility + vacation/NPL toggles
  const filteredEvents = useMemo(() => {
    return events.filter((e) => {
      if (!visibilityFilter.includes(e.visibility)) return false;
      const title = e.title ?? "";
      if (!showVacation && VACATION_KEYWORDS.some((kw) => title.includes(kw))) return false;
      if (!showNpl && title.includes("NPL")) return false;
      return true;
    });
  }, [events, visibilityFilter, showVacation, showNpl]);

  const displayEvents = filteredEvents;

  // Handlers
  const handleDatesSet = useCallback((start: Date, end: Date) => {
    const middle = new Date(start.getTime() + (end.getTime() - start.getTime()) / 2);
    setCurrentMonth(
      middle.toLocaleDateString("ko-KR", { year: "numeric", month: "long" })
    );
    // Format dates for API (로컬 시간 기준)
    const startStr = `${start.getFullYear()}-${String(start.getMonth()+1).padStart(2,"0")}-${String(start.getDate()).padStart(2,"0")}`;
    const endStr = `${end.getFullYear()}-${String(end.getMonth()+1).padStart(2,"0")}-${String(end.getDate()).padStart(2,"0")}`;
    // 같은 범위면 새 객체 생성 금지 → useEffect 중복 실행 방지
    setDateRange(prev => {
      if (prev?.start === startStr && prev?.end === endStr) return prev;
      return { start: startStr, end: endStr };
    });
  }, []);

  const handleDateClick = useCallback((date: Date) => {
    setSelectedDate(date);
  }, []);

  const handlePrevMonth = () => calendarRef.current?.getApi().prev();
  const handleNextMonth = () => calendarRef.current?.getApi().next();
  const handleToday = () => {
    setSelectedDate(new Date());
    calendarRef.current?.getApi().today();
  };
  const handlePrevDay = () => setSelectedDate((d) => {
    const prev = new Date(d ?? new Date());
    prev.setDate(prev.getDate() - 1);
    return prev;
  });
  const handleNextDay = () => setSelectedDate((d) => {
    const next = new Date(d ?? new Date());
    next.setDate(next.getDate() + 1);
    return next;
  });

  const toggleVisibility = (value: string) => {
    setVisibilityFilter((prev) =>
      prev.includes(value)
        ? prev.filter((v) => v !== value)
        : [...prev, value]
    );
  };

  const handleCreateEvent = async (data: EventCreateRequest) => {
    if (!empno) return;
    const result = await createEvent(empno, data);
    if (result) {
      setShowBottomSheet(false);
      setEditingEvent(null);
      // 저장된 날짜로 캘린더 이동 (다른 달이면 자동으로 datesSet → fetchEvents 실행)
      const eventDate = new Date(result.start_dt.replace(" ", "T"));
      calendarRef.current?.getApi().gotoDate(eventDate);
      // 같은 달인 경우를 위해 직접 재조회 (handleDatesSet의 중복 방지 덕분에 중복 실행 안 됨)
      if (dateRange) {
        fetchEvents(empno, dateRange.start, dateRange.end);
      }
    }
  };

  const handleUpdateEvent = async (data: EventCreateRequest) => {
    if (!editingEvent || !empno) return;
    const updateData: EventUpdateRequest = {
      title: data.title,
      description: data.description,
      location: data.location,
      event_color: data.event_color,
      event_icon: data.event_icon,
      start_dt: data.start_dt,
      end_dt: data.end_dt,
      is_all_day: data.is_all_day,
      visibility: data.visibility,
      dept_code: data.dept_code,
      attendee_ids: data.attendee_ids,
      version: editingEvent.version,
    };
    const result = await updateEvent(empno, editingEvent.event_id, updateData);
    if (result) {
      setShowBottomSheet(false);
      setEditingEvent(null);
      setShowDetail(false);
      // 수정된 날짜로 캘린더 이동
      const eventDate = new Date(result.start_dt.replace(" ", "T"));
      calendarRef.current?.getApi().gotoDate(eventDate);
      if (dateRange) {
        fetchEvents(empno, dateRange.start, dateRange.end);
      }
    }
  };

  const handleDeleteEvent = async (eventId: number) => {
    if (!empno) return;
    const success = await deleteEvent(empno, eventId);
    if (success) {
      setShowDetail(false);
      setSelectedEvent(null);
      if (dateRange) {
        fetchEvents(empno, dateRange.start, dateRange.end);
      }
    }
  };

  const handleEventClick = async (event: CalendarEvent) => {
    if (event.source === "iw_schedule") {
      setSelectedEvent(event);
      setShowDetail(true);
      return;
    }
    try {
      const { data } = await api.get<ApiResponse<CalendarEvent>>(
        `/events/${event.event_id}`,
        { params: { empno } }
      );
      const detail = (data.data ?? data) as CalendarEvent;
      setSelectedEvent(detail);
    } catch {
      setSelectedEvent(event);
    }
    setShowDetail(true);
  };

  const handleEditFromDetail = (event: CalendarEvent) => {
    setShowDetail(false);
    setEditingEvent(event);
    setShowBottomSheet(true);
  };

  if (empno === null) {
    // 저장된 empno 조회 중이거나 redirect 대기
    if (!empnoChecked) {
      return (
        <div className="flex items-center justify-center h-screen text-txt-secondary">
          <div className="animate-pulse">불러오는 중...</div>
        </div>
      );
    }
    // 조회 완료 후에도 empno 없음
    return (
      <div className="flex items-center justify-center h-screen text-txt-secondary">
        empno 파라미터가 필요합니다.
      </div>
    );
  }

  return (
    <div className="flex h-screen bg-bg-primary" onContextMenu={(e) => e.preventDefault()}>
      {/* Sidebar - Desktop visibility filter */}
      <aside
        className={`hidden md:flex flex-col border-r border-border bg-bg-secondary/50 transition-all duration-300 ${
          sidebarOpen ? "w-60" : "w-0 overflow-hidden"
        }`}
      >
        <div className="p-4 flex-1 overflow-y-auto">
          <h3 className="text-xs font-semibold text-txt-secondary uppercase tracking-wider mb-3">
            캘린더
          </h3>
          {VISIBILITY_OPTIONS.map((opt) => (
            <label
              key={opt.value}
              className="flex items-center gap-3 py-2 px-2 rounded-lg hover:bg-bg-secondary cursor-pointer transition-colors"
            >
              <input
                type="checkbox"
                checked={visibilityFilter.includes(opt.value)}
                onChange={() => toggleVisibility(opt.value)}
                className="sr-only"
              />
              <div
                className={`w-4 h-4 rounded flex items-center justify-center border-2 transition-colors ${
                  visibilityFilter.includes(opt.value)
                    ? "border-transparent"
                    : "border-border bg-bg-primary"
                }`}
                style={
                  visibilityFilter.includes(opt.value)
                    ? { backgroundColor: opt.color }
                    : {}
                }
              >
                {visibilityFilter.includes(opt.value) && (
                  <svg
                    className="w-3 h-3 text-white"
                    fill="none"
                    viewBox="0 0 24 24"
                    stroke="currentColor"
                    strokeWidth={3}
                  >
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      d="M5 13l4 4L19 7"
                    />
                  </svg>
                )}
              </div>
              <span className="text-sm text-txt-primary">{opt.label}</span>
            </label>
          ))}

          {/* 휴가 / NPL 필터 */}
          {[
            { key: "vacation", label: "휴가", checked: showVacation, color: "#FFFF8D", iconColor: "#1A1A1A", onChange: () => setShowVacation((v) => !v) },
            ...(canSeeNpl ? [{ key: "npl", label: "NPL", checked: showNpl, color: "#C084FC", iconColor: "#FFFFFF", onChange: () => setShowNpl((v) => !v) }] : []),
          ].map((item) => (
            <label
              key={item.key}
              className="flex items-center gap-3 py-2 px-2 rounded-lg hover:bg-bg-secondary cursor-pointer transition-colors"
            >
              <input
                type="checkbox"
                checked={item.checked}
                onChange={item.onChange}
                className="sr-only"
              />
              <div
                className={`w-4 h-4 rounded flex items-center justify-center border-2 transition-colors ${
                  item.checked ? "border-transparent" : "border-border bg-bg-primary"
                }`}
                style={item.checked ? { backgroundColor: item.color } : {}}
              >
                {item.checked && (
                  <svg
                    className="w-3 h-3"
                    style={{ color: item.iconColor ?? "#FFFFFF" }}
                    fill="none"
                    viewBox="0 0 24 24"
                    stroke="currentColor"
                    strokeWidth={3}
                  >
                    <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                  </svg>
                )}
              </div>
              <span className="text-sm text-txt-primary">{item.label}</span>
            </label>
          ))}

          {/* Dark / Light Mode Toggle */}
          <div className="mt-6 pt-4 border-t border-border">
            <h3 className="text-xs font-semibold text-txt-secondary uppercase tracking-wider mb-3">
              화면 모드
            </h3>
            <div className="flex gap-1">
              {([
                { value: "light", label: "라이트", icon: "M12 3v1m0 16v1m9-9h-1M4 12H3m15.364 6.364l-.707-.707M6.343 6.343l-.707-.707m12.728 0l-.707.707M6.343 17.657l-.707.707M16 12a4 4 0 11-8 0 4 4 0 018 0z" },
                { value: "dark", label: "다크", icon: "M20.354 15.354A9 9 0 018.646 3.646 9.003 9.003 0 0012 21a9.003 9.003 0 008.354-5.646z" },
              ] as const).map((mode) => (
                <button
                  key={mode.value}
                  onClick={() => setTheme(mode.value)}
                  className={`flex-1 flex items-center justify-center gap-2 py-2.5 rounded-lg text-sm transition-colors ${
                    theme === mode.value
                      ? "bg-accent text-accent-contrast font-semibold"
                      : "bg-bg-secondary text-txt-secondary hover:bg-bg-tertiary"
                  }`}
                >
                  <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d={mode.icon} />
                  </svg>
                  {mode.label}
                </button>
              ))}
            </div>
          </div>

          {/* Accent Color Picker (Dropdown) */}
          <div className="mt-4 pt-4 border-t border-border">
            <AccentColorDropdown />
          </div>
        </div>
      </aside>

      {/* Main */}
      <main className="flex-1 flex flex-col overflow-hidden bg-bg-primary">
        <Header
          currentMonth={currentMonth}
          onPrevMonth={handlePrevMonth}
          onNextMonth={handleNextMonth}
          onToday={handleToday}
          onToggleSidebar={() => setSidebarOpen((prev) => !prev)}
          userName={user?.name}
          empno={empno}
          viewMode={viewMode}
          onViewChange={setViewMode}
          onSync={() => {
            setRefreshTrigger((v) => v + 1);
          }}
          onRefresh={() => {
            setRefreshTrigger((v) => v + 1);
          }}
        />

        {/* Mobile visibility filter */}
        <div className="md:hidden flex items-center gap-2 px-4 py-2 bg-bg-secondary border-b border-border overflow-x-auto">
          {VISIBILITY_OPTIONS.map((opt) => (
            <button
              key={opt.value}
              onClick={() => toggleVisibility(opt.value)}
              className={`flex-shrink-0 px-3 py-1 rounded-full text-xs font-medium transition-all ${
                visibilityFilter.includes(opt.value)
                  ? "text-white"
                  : "bg-bg-primary text-txt-secondary border border-border"
              }`}
              style={
                visibilityFilter.includes(opt.value)
                  ? { backgroundColor: opt.color }
                  : undefined
              }
            >
              {opt.label}
            </button>
          ))}
          <button
            onClick={() => setShowVacation((v) => !v)}
            className={`flex-shrink-0 px-3 py-1 rounded-full text-xs font-medium transition-all ${
              showVacation ? "text-white" : "bg-bg-primary text-txt-secondary border border-border"
            }`}
            style={showVacation ? { backgroundColor: "#FFFF8D", color: "#1A1A1A" } : undefined}
          >
            휴가
          </button>
          {canSeeNpl && (
            <button
              onClick={() => setShowNpl((v) => !v)}
              className={`flex-shrink-0 px-3 py-1 rounded-full text-xs font-medium transition-all ${
                showNpl ? "text-white" : "bg-bg-primary text-txt-secondary border border-border"
              }`}
              style={showNpl ? { backgroundColor: "#C084FC" } : undefined}
            >
              NPL
            </button>
          )}
        </div>

        <div className="flex-1 flex flex-col overflow-hidden min-h-0">
          <div className="flex-shrink-0 h-[58vh] min-h-[520px] overflow-hidden">
            <MonthView
              events={displayEvents}
              selectedDate={selectedDate}
              onDateClick={handleDateClick}
              onDatesSet={handleDatesSet}
              calendarRef={calendarRef}
              viewType={viewMode === "week" ? "timeGridWeek" : "dayGridMonth"}
              holidays={holidays}
            />
          </div>
          {viewMode === "month" && (
            <>
              <div className="h-px bg-border mx-4 flex-shrink-0" />
              <DayEventList
                selectedDate={selectedDate}
                events={displayEvents}
                onEventClick={handleEventClick}
              />
            </>
          )}
        </div>

        {/* Loading indicator */}
        {eventsLoading && (
          <div className="absolute top-16 left-1/2 -translate-x-1/2 bg-bg-primary shadow-lg rounded-full px-4 py-2 text-sm text-txt-secondary z-50">
            불러오는 중...
          </div>
        )}

        <FAB
          onClick={() => {
            setEditingEvent(null);
            setShowBottomSheet(true);
          }}
        />

        <EventBottomSheet
          isOpen={showBottomSheet}
          onClose={() => {
            setShowBottomSheet(false);
            setEditingEvent(null);
          }}
          onSave={editingEvent ? handleUpdateEvent : handleCreateEvent}
          initialDate={selectedDate}
          editEvent={editingEvent}
          userDeptCode={user?.dept_code}
        />

        <EventDetail
          event={selectedEvent}
          isOpen={showDetail}
          onClose={() => {
            setShowDetail(false);
            setSelectedEvent(null);
          }}
          onEdit={handleEditFromDetail}
          onDelete={handleDeleteEvent}
          currentEmpno={empno}
        />
      </main>
    </div>
  );
}

export default function CalendarPage() {
  return (
    <>
      <Suspense
        fallback={
          <div className="flex items-center justify-center min-h-screen">
            <div className="animate-pulse text-txt-secondary">불러오는 중...</div>
          </div>
        }
      >
        <CalendarContent />
      </Suspense>
    </>
  );
}
