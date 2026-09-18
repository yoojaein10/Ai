"use client";

import React, { useState, useEffect, useCallback, useMemo, useRef } from "react";
import {
  CalendarEvent,
  EventCreateRequest,
  DeptWithUsers,
  ApiResponse,
  VISIBILITY_OPTIONS,
} from "@/lib/types";
import api from "@/lib/api";
import Input from "@/components/ui/Input";
import DatePicker from "@/components/ui/DatePicker";
import ColorPicker from "./ColorPicker";
import EmojiPicker from "./EmojiPicker";

// ============================================================
// TimeSelect - 12시 기준 자동 스크롤 커스텀 시간 선택기
// ============================================================
const TIME_SLOTS = Array.from({ length: 48 }, (_, i) => {
  const h = String(Math.floor(i / 2)).padStart(2, "0");
  const m = i % 2 === 0 ? "00" : "30";
  return `${h}:${m}`;
});

function TimeSelect({ value, onChange, className }: {
  value: string;
  onChange: (v: string) => void;
  className?: string;
}) {
  const [open, setOpen] = useState(false);
  const listRef = useRef<HTMLDivElement>(null);
  const wrapRef = useRef<HTMLDivElement>(null);

  // 열릴 때 선택된 시간 위치로 스크롤
  useEffect(() => {
    if (open && listRef.current) {
      const selected = listRef.current.querySelector(`[data-value="${value}"]`) as HTMLElement;
      if (selected) selected.scrollIntoView({ block: "start" });
    }
  }, [open, value]);

  // 바깥 클릭 시 닫기
  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [open]);

  return (
    <div ref={wrapRef} className="relative">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className={className}
      >
        {value}
        <svg className="w-4 h-4 ml-auto text-txt-secondary" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
        </svg>
      </button>
      {open && (
        <div
          ref={listRef}
          className="absolute z-[60] mt-1 w-full max-h-48 overflow-y-auto bg-bg-primary border border-border rounded-lg shadow-lg"
        >
          {TIME_SLOTS.map((t) => (
            <div
              key={t}
              data-value={t}
              onClick={() => { onChange(t); setOpen(false); }}
              className={`px-3 py-1.5 text-sm cursor-pointer transition-colors
                ${t === value ? "bg-accent/10 text-accent font-medium" : "text-txt-primary hover:bg-bg-secondary"}`}
            >
              {t}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ============================================================
// EventBottomSheet - 일정 생성/수정 바텀시트
// ============================================================

interface EventBottomSheetProps {
  isOpen: boolean;
  onClose: () => void;
  onSave: (data: EventCreateRequest) => void | Promise<void>;
  initialDate?: Date | null;
  editEvent?: CalendarEvent | null;
  userDeptCode?: string;
}

export default function EventBottomSheet({
  isOpen,
  onClose,
  onSave,
  initialDate,
  editEvent,
  userDeptCode,
}: EventBottomSheetProps) {
  // --- Save loading state ---
  const [saving, setSaving] = useState(false);
  const [toastMsg, setToastMsg] = useState<string | null>(null);

  const showToast = (msg: string) => {
    setToastMsg(msg);
    setTimeout(() => setToastMsg(null), 2500);
  };

  // --- Form state ---
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [location, setLocation] = useState("");
  const [startDate, setStartDate] = useState("");
  const [startTime, setStartTime] = useState("09:00");
  const [endDate, setEndDate] = useState("");
  const [endTime, setEndTime] = useState("10:00");
  const [allDay, setAllDay] = useState(false);
  const [color, setColor] = useState("#339AF0");
  const [emoji, setEmoji] = useState("");
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [daouNotiEnabled, setDaouNotiEnabled] = useState(true);

  // --- Attendee tree state ---
  const [deptUsers, setDeptUsers] = useState<DeptWithUsers[]>([]);
  const [selectedAll, setSelectedAll] = useState(false);
  const [selectedDepts, setSelectedDepts] = useState<Set<string>>(new Set());
  const [selectedUsers, setSelectedUsers] = useState<Set<number>>(new Set());
  const [expandedDepts, setExpandedDepts] = useState<Set<string>>(new Set());

  // --- Load department+user tree ---
  useEffect(() => {
    api
      .get<ApiResponse<DeptWithUsers[]>>("/users/by-department")
      .then((res) => {
        const list = res.data.data ?? res.data;
        setDeptUsers(Array.isArray(list) ? list : []);
      })
      .catch(() => {
        // Silently fail
      });
  }, []);

  // --- All user IDs (memo) ---
  const allUserIds = useMemo(() => {
    const ids = new Set<number>();
    deptUsers.forEach((d) => d.users.forEach((u) => ids.add(u.apwid)));
    return ids;
  }, [deptUsers]);

  // --- Users per dept (memo) ---
  const usersByDept = useMemo(() => {
    const map: Record<string, Set<number>> = {};
    deptUsers.forEach((d) => {
      map[d.dept_code] = new Set(d.users.map((u) => u.apwid));
    });
    return map;
  }, [deptUsers]);

  // --- 참석자 선택에 따른 visibility 판별 ---
  const currentVisibility = useMemo(() => {
    if (selectedAll) return "company";
    const checkedDepts = Array.from(selectedDepts);
    if (checkedDepts.length === 0 && selectedUsers.size === 0) return "personal";
    if (checkedDepts.length >= 1) return "dept";
    return "personal";
  }, [selectedAll, selectedDepts, selectedUsers]);

  // --- 상단 컬러 바 색상 ---
  const visibilityColor = useMemo(() => {
    return VISIBILITY_OPTIONS.find((o) => o.value === currentVisibility)?.color ?? "#339AF0";
  }, [currentVisibility]);

  // --- 신규 일정: 참석자 변경 시 색상 자동 동기화 ---
  useEffect(() => {
    if (editEvent) return; // 수정 모드에서는 사용자 선택 색상 유지
    const match = VISIBILITY_OPTIONS.find((o) => o.value === currentVisibility);
    if (match) setColor(match.color);
  }, [currentVisibility, editEvent]);

  // --- 시작 시간 변경 시 종료 시간 자동 업데이트 (+1시간) ---
  useEffect(() => {
    const [h, m] = startTime.split(":").map(Number);
    const startMins = h * 60 + m;
    const endMins = Math.min(startMins + 60, 23 * 60 + 30); // 최대 23:30
    const endH = String(Math.floor(endMins / 60)).padStart(2, "0");
    const endM = endMins % 60 === 0 ? "00" : "30";
    setEndTime(`${endH}:${endM}`);
  }, [startTime]);


  // --- Derive visibility from selection ---
  const deriveVisibility = useCallback((): {
    visibility: string;
    dept_code?: string;
    attendee_ids: number[];
  } => {
    if (selectedAll) {
      return { visibility: "company", attendee_ids: [] };
    }

    const checkedDepts = Array.from(selectedDepts);
    if (checkedDepts.length === 0 && selectedUsers.size === 0) {
      return { visibility: "personal", attendee_ids: [] };
    }

    // One dept -> dept with dept_code, multiple depts -> dept without dept_code (attendees handle access)
    if (checkedDepts.length === 1) {
      return {
        visibility: "dept",
        dept_code: checkedDepts[0],
        attendee_ids: Array.from(selectedUsers),
      };
    }
    if (checkedDepts.length > 1) {
      return {
        visibility: "dept",
        dept_code: undefined,
        attendee_ids: Array.from(selectedUsers),
      };
    }

    // Only individual users selected (no full dept) -> personal
    return {
      visibility: "personal",
      attendee_ids: Array.from(selectedUsers),
    };
  }, [selectedAll, selectedDepts, selectedUsers, usersByDept]);
  // --- Tree handlers ---
  const handleToggleAll = useCallback(() => {
    if (selectedAll) {
      // Uncheck all
      setSelectedAll(false);
      setSelectedDepts(new Set());
      setSelectedUsers(new Set());
    } else {
      // Check all
      setSelectedAll(true);
      setSelectedDepts(new Set(deptUsers.map((d) => d.dept_code)));
      setSelectedUsers(new Set(allUserIds));
    }
  }, [selectedAll, deptUsers, allUserIds]);

  const handleToggleDept = useCallback(
    (deptCode: string) => {
      const deptUserIds = usersByDept[deptCode] || new Set<number>();
      const newSelectedUsers = new Set(selectedUsers);
      const newSelectedDepts = new Set(selectedDepts);

      if (newSelectedDepts.has(deptCode)) {
        // Uncheck dept
        newSelectedDepts.delete(deptCode);
        deptUserIds.forEach((uid) => newSelectedUsers.delete(uid));
      } else {
        // Check dept
        newSelectedDepts.add(deptCode);
        deptUserIds.forEach((uid) => newSelectedUsers.add(uid));
      }

      setSelectedDepts(newSelectedDepts);
      setSelectedUsers(newSelectedUsers);

      // Update "all" state
      const allDeptCodes = deptUsers.map((d) => d.dept_code);
      setSelectedAll(allDeptCodes.every((dc) => newSelectedDepts.has(dc)));
    },
    [selectedUsers, selectedDepts, usersByDept, deptUsers]
  );

  const handleToggleUser = useCallback(
    (apwid: number, deptCode: string) => {
      const newSelectedUsers = new Set(selectedUsers);
      if (newSelectedUsers.has(apwid)) {
        newSelectedUsers.delete(apwid);
      } else {
        newSelectedUsers.add(apwid);
      }
      setSelectedUsers(newSelectedUsers);

      // Update dept checkbox state
      const deptUserIds = usersByDept[deptCode] || new Set<number>();
      const allChecked = Array.from(deptUserIds).every((uid) =>
        newSelectedUsers.has(uid)
      );
      const newSelectedDepts = new Set(selectedDepts);
      if (allChecked && deptUserIds.size > 0) {
        newSelectedDepts.add(deptCode);
      } else {
        newSelectedDepts.delete(deptCode);
      }
      setSelectedDepts(newSelectedDepts);

      // Update "all" state
      const allDeptCodes = deptUsers.map((d) => d.dept_code);
      setSelectedAll(allDeptCodes.every((dc) => newSelectedDepts.has(dc)));
    },
    [selectedUsers, selectedDepts, usersByDept, deptUsers]
  );

  const handleToggleExpand = useCallback((deptCode: string) => {
    setExpandedDepts((prev) => {
      const next = new Set(prev);
      if (next.has(deptCode)) {
        next.delete(deptCode);
      } else {
        next.add(deptCode);
      }
      return next;
    });
  }, []);

  // --- Dept indeterminate check ---
  const isDeptIndeterminate = useCallback(
    (deptCode: string): boolean => {
      const deptUserIds = usersByDept[deptCode];
      if (!deptUserIds || deptUserIds.size === 0) return false;
      const checkedCount = Array.from(deptUserIds).filter((uid) =>
        selectedUsers.has(uid)
      ).length;
      return checkedCount > 0 && checkedCount < deptUserIds.size;
    },
    [usersByDept, selectedUsers]
  );

  // --- Total selected count ---
  const totalSelectedCount = selectedUsers.size;

  // --- Initialize form ---
  useEffect(() => {
    if (!isOpen) return;

    if (editEvent) {
      setTitle(editEvent.title);
      setDescription(editEvent.description || "");
      setLocation(editEvent.location || "");
      // MSSQL "2026-03-18 09:00:00" 형식 지원
      const sStr = editEvent.start_dt.replace(" ", "T");
      const eStr = editEvent.end_dt.replace(" ", "T");
      const s = new Date(sStr);
      const e = new Date(eStr);
      setStartDate(`${s.getFullYear()}-${String(s.getMonth() + 1).padStart(2, "0")}-${String(s.getDate()).padStart(2, "0")}`);
      setStartTime(`${String(s.getHours()).padStart(2, "0")}:${String(s.getMinutes()).padStart(2, "0")}`);
      setEndDate(`${e.getFullYear()}-${String(e.getMonth() + 1).padStart(2, "0")}-${String(e.getDate()).padStart(2, "0")}`);
      setEndTime(`${String(e.getHours()).padStart(2, "0")}:${String(e.getMinutes()).padStart(2, "0")}`);
      setAllDay(editEvent.is_all_day);
      setColor(editEvent.event_color || "#339AF0");
      setEmoji(editEvent.event_icon || "");
      setDaouNotiEnabled(editEvent.is_daou_noti_enabled ?? true);
      setShowAdvanced(false);

      // Restore attendee selection
      if (editEvent.visibility === "company") {
        setSelectedAll(true);
        setSelectedDepts(new Set(deptUsers.map((d) => d.dept_code)));
        setSelectedUsers(new Set(allUserIds));
      } else if (editEvent.attendees && editEvent.attendees.length > 0) {
        const ids = new Set(editEvent.attendees.map((a) => a.apwid));
        setSelectedUsers(ids);
        // Determine which depts are fully selected
        const fullDepts = new Set<string>();
        deptUsers.forEach((d) => {
          const deptUserIds = d.users.map((u) => u.apwid);
          if (
            deptUserIds.length > 0 &&
            deptUserIds.every((uid) => ids.has(uid))
          ) {
            fullDepts.add(d.dept_code);
          }
        });
        setSelectedDepts(fullDepts);
        setSelectedAll(false);
      } else {
        setSelectedAll(false);
        setSelectedDepts(new Set());
        setSelectedUsers(new Set());
      }
    } else {
      resetForm();
      if (initialDate) {
        // 로컬 시간 기준 날짜 (UTC 변환 방지)
        const y = initialDate.getFullYear();
        const m = String(initialDate.getMonth() + 1).padStart(2, "0");
        const dd = String(initialDate.getDate()).padStart(2, "0");
        const d = `${y}-${m}-${dd}`;
        setStartDate(d);
        setEndDate(d);
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [editEvent, initialDate, isOpen]);

  const resetForm = () => {
    setTitle("");
    setDescription("");
    setLocation("");
    const now = new Date();
    const today = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
    setStartDate(today);
    setEndDate(today);
    // 현재 시간에서 가장 가까운 30분 단위로 올림
    const mins = now.getHours() * 60 + now.getMinutes();
    const rounded = Math.ceil(mins / 30) * 30;
    const startH = String(Math.floor((rounded % 1440) / 60)).padStart(2, "0");
    const startM = (rounded % 1440) % 60 === 0 ? "00" : "30";
    const endRounded = rounded + 60; // 1시간 후
    const endH = String(Math.floor((endRounded % 1440) / 60)).padStart(2, "0");
    const endM = (endRounded % 1440) % 60 === 0 ? "00" : "30";
    setStartTime(`${startH}:${startM}`);
    setEndTime(`${endH}:${endM}`);
    setAllDay(false);
    setColor("#339AF0");
    setEmoji("");
    setDaouNotiEnabled(true);
    setShowAdvanced(false);
    setSelectedAll(false);
    setSelectedDepts(new Set());
    setSelectedUsers(new Set());
    setExpandedDepts(new Set());
    setSaving(false);
  };

  const handleSubmit = async (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    if (saving) return;
    if (!title.trim()) {
      showToast("제목을 입력해주세요");
      return;
    }

    const startDateTime = allDay
      ? `${startDate}T00:00:00`
      : `${startDate}T${startTime}:00`;
    const endDateTime = allDay
      ? `${endDate}T23:59:59`
      : `${endDate}T${endTime}:00`;

    const derived = deriveVisibility();

    const data: EventCreateRequest = {
      title: title.trim(),
      description: description.trim() || undefined,
      location: location.trim() || undefined,
      start_dt: startDateTime,
      end_dt: endDateTime,
      is_all_day: allDay,
      event_color: color,
      event_icon: emoji || undefined,
      visibility: derived.visibility,
      dept_code: derived.dept_code,
      attendee_ids: derived.attendee_ids.length > 0
        ? derived.attendee_ids
        : undefined,
      is_daou_noti_enabled: daouNotiEnabled,
    };

    setSaving(true);
    try {
      await onSave(data);
    } finally {
      setSaving(false);
    }
  };

  if (!isOpen) return null;

  return (
    <>
      {/* Backdrop */}
      <div
        className="fixed inset-0 bg-black/40 z-40 animate-fade-in"
        onClick={onClose}
      />

      {/* Bottom Sheet */}
      <div className="fixed inset-x-0 bottom-0 z-50 md:inset-auto md:top-1/2 md:left-1/2 md:-translate-x-1/2 md:-translate-y-1/2 md:w-full md:max-w-2xl">
        <div className="bg-bg-primary rounded-t-2xl md:rounded-2xl shadow-xl animate-slide-up max-h-[90vh] md:max-h-[85vh] flex flex-col">
          {/* 상단 컬러 바 - 참석자 선택에 따라 색상 변경 */}
          <div
            className="h-1.5 rounded-t-2xl md:rounded-t-2xl transition-colors duration-300"
            style={{ backgroundColor: visibilityColor }}
          />

          {/* Handle bar (mobile) */}
          <div className="flex justify-center pt-3 md:hidden">
            <div className="w-10 h-1 bg-[var(--bg-tertiary)] rounded-full" />
          </div>

          {/* Header */}
          <div className="flex items-center justify-between px-5 py-3 border-b border-border">
            <button
              onClick={onClose}
              className="text-sm text-txt-secondary hover:text-txt-primary transition-colors"
            >
              취소
            </button>
            <h2 className="text-base font-semibold text-txt-primary">
              {editEvent ? "일정 수정" : "새 일정"}
            </h2>
            <button
              type="button"
              onClick={() => handleSubmit()}
              disabled={saving}
              className="text-sm text-txt-secondary hover:text-txt-primary disabled:opacity-40 transition-colors"
            >
              {saving ? "저장 중..." : "저장"}
            </button>
          </div>

          {/* Toast */}
          {toastMsg && (
            <div className="mx-5 mt-2 px-4 py-2 rounded-lg bg-red-500 text-white text-sm text-center">
              {toastMsg}
            </div>
          )}

          {/* Form */}
          <form
            onSubmit={handleSubmit}
            className="flex-1 overflow-y-auto px-5 py-4"
          >
           <div className="grid grid-cols-1 md:grid-cols-2 gap-6 items-start">
            {/* === 좌측: 일정 정보 === */}
            <div className="space-y-4">
            {/* 제목 */}
            <Input
              placeholder="제목"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              className="text-base font-medium border-0 border-b border-border rounded-none px-0 focus:ring-0 focus:border-accent"
              autoFocus
            />

            {/* 내용 */}
            <div>
              <textarea
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                placeholder="내용을 입력하세요"
                rows={2}
                className="w-full px-3 py-2 border border-border rounded-lg text-sm text-txt-primary placeholder:text-txt-secondary bg-bg-primary focus:outline-none focus:ring-2 focus:ring-accent focus:border-transparent resize-none"
              />
            </div>

            {/* 종일 토글 */}
            <div className="flex items-center justify-between py-2">
              <span className="text-sm text-txt-primary">종일</span>
              <button
                type="button"
                onClick={() => setAllDay(!allDay)}
                className={`relative w-11 h-6 rounded-full transition-colors duration-200 ${allDay ? "bg-accent" : "bg-[var(--bg-tertiary)]"
                  }`}
              >
                <span
                  className={`absolute top-0.5 left-0.5 w-5 h-5 bg-white rounded-full shadow-sm transition-transform duration-200 ${allDay ? "translate-x-5" : ""
                    }`}
                />
              </button>
            </div>

            {/* 날짜/시간 */}
            <div className="space-y-3">
              <div className="flex gap-3">
                <DatePicker
                  label="시작"
                  value={startDate}
                  onChange={(v) => setStartDate(v)}
                />
                {!allDay && (
                  <div className="w-full">
                    <label className="block text-sm font-medium text-txt-primary mb-1">시간</label>
                    <TimeSelect
                      value={startTime}
                      onChange={setStartTime}
                      className="w-full flex items-center px-3 py-2 border border-border rounded-lg text-sm text-txt-primary bg-bg-primary focus:outline-none focus:ring-2 focus:ring-accent focus:border-transparent"
                    />
                  </div>
                )}
              </div>
              <div className="flex gap-3">
                <DatePicker
                  label="종료"
                  value={endDate}
                  onChange={(v) => setEndDate(v)}
                />
                {!allDay && (
                  <div className="w-full">
                    <label className="block text-sm font-medium text-txt-primary mb-1">시간</label>
                    <TimeSelect
                      value={endTime}
                      onChange={setEndTime}
                      className="w-full flex items-center px-3 py-2 border border-border rounded-lg text-sm text-txt-primary bg-bg-primary focus:outline-none focus:ring-2 focus:ring-accent focus:border-transparent"
                    />
                  </div>
                )}
              </div>
            </div>

            {/* 색상 */}
            <ColorPicker selectedColor={color} onChange={setColor} />

            {/* 다우오피스 정기 알림 */}
            <label className="flex items-center gap-3 py-2 cursor-pointer">
              <input
                type="checkbox"
                checked={daouNotiEnabled}
                onChange={(e) => setDaouNotiEnabled(e.target.checked)}
                className="w-4 h-4 rounded border-border text-accent focus:ring-accent"
              />
              <div className="flex flex-col">
                <span className="text-sm text-txt-primary">
                  다우오피스 정기 알림 받기
                </span>
                <span className="text-xs text-txt-secondary">
                  일정 1일 전 오전 9시에 알림을 발송합니다
                </span>
              </div>
            </label>

            {/* 추가 옵션 */}
            <button
              type="button"
              onClick={() => setShowAdvanced(!showAdvanced)}
              className="flex items-center gap-1 text-sm text-txt-primary"
            >
              <svg
                className={`w-4 h-4 transition-transform ${showAdvanced ? "rotate-90" : ""}`}
                fill="none"
                viewBox="0 0 24 24"
                stroke="currentColor"
              >
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
              </svg>
              추가 옵션
            </button>

            {showAdvanced && (
              <div className="space-y-4 animate-fade-in">
                <EmojiPicker selectedEmoji={emoji} onChange={setEmoji} />
                <Input
                  label="장소"
                  placeholder="장소를 입력하세요"
                  value={location}
                  onChange={(e) => setLocation(e.target.value)}
                />
              </div>
            )}
            </div>

            {/* === 우측: 참석자 === */}
            <div className="space-y-4">
            {/* 참석자 트리뷰 */}
            <div>
              <label className="block text-sm font-medium text-txt-primary mb-2">
                참석자
                {totalSelectedCount > 0 && (
                  <span className="ml-2 text-xs text-accent font-normal">
                    ({totalSelectedCount}명 선택)
                  </span>
                )}
              </label>
              <div className="border border-border rounded-lg overflow-hidden">
                <div className="max-h-[200px] md:max-h-[400px] overflow-y-auto">
                  {/* 전체 */}
                  <label className="flex items-center gap-2 px-3 py-2 hover:bg-bg-secondary cursor-pointer border-b border-border">
                    <input
                      type="checkbox"
                      checked={selectedAll}
                      onChange={handleToggleAll}
                      className="w-4 h-4 rounded border-border text-accent focus:ring-accent"
                    />
                    <span className="text-sm font-semibold text-txt-primary">
                      전체
                    </span>
                  </label>

                  {/* 부서별 */}
                  {deptUsers.map((dept) => {
                    const isExpanded = expandedDepts.has(dept.dept_code);
                    const isDeptChecked = selectedDepts.has(dept.dept_code);
                    const isIndeterminate = isDeptIndeterminate(dept.dept_code);

                    return (
                      <div key={dept.dept_code}>
                        {/* 부서 row */}
                        <div className="flex items-center gap-1 px-3 py-1.5 hover:bg-bg-secondary border-b border-border">
                          {/* 펼침/접기 */}
                          <button
                            type="button"
                            onClick={() => handleToggleExpand(dept.dept_code)}
                            className="w-5 h-5 flex items-center justify-center text-txt-secondary hover:text-txt-primary flex-shrink-0"
                          >
                            <svg
                              className={`w-3 h-3 transition-transform ${isExpanded ? "rotate-90" : ""
                                }`}
                              fill="currentColor"
                              viewBox="0 0 20 20"
                            >
                              <path d="M6 4l8 6-8 6V4z" />
                            </svg>
                          </button>
                          {/* 체크박스 */}
                          <input
                            type="checkbox"
                            ref={(el) => {
                              if (el) el.indeterminate = isIndeterminate;
                            }}
                            checked={isDeptChecked}
                            onChange={() => handleToggleDept(dept.dept_code)}
                            className="w-4 h-4 rounded border-border text-accent focus:ring-accent"
                          />
                          <button
                            type="button"
                            onClick={() => handleToggleExpand(dept.dept_code)}
                            className="text-sm font-semibold text-txt-primary flex-1 text-left"
                          >
                            {dept.dept_name}
                            <span className="ml-1 text-xs text-txt-secondary font-normal">
                              ({dept.users.length})
                            </span>
                          </button>
                        </div>

                        {/* 사용자 목록 */}
                        {isExpanded &&
                          dept.users.map((user) => (
                            <label
                              key={user.apwid}
                              className="flex items-center gap-2 pl-10 pr-3 py-1 hover:bg-bg-secondary cursor-pointer"
                            >
                              <input
                                type="checkbox"
                                checked={selectedUsers.has(user.apwid)}
                                onChange={() =>
                                  handleToggleUser(user.apwid, dept.dept_code)
                                }
                                className="w-3.5 h-3.5 rounded border-border text-accent focus:ring-accent"
                              />
                              <span className="text-sm text-txt-primary">
                                {user.name}
                              </span>
                            </label>
                          ))}
                      </div>
                    );
                  })}

                  {deptUsers.length === 0 && (
                    <div className="px-3 py-4 text-sm text-txt-secondary text-center">
                      부서 정보를 불러오는 중...
                    </div>
                  )}
                </div>
              </div>
            </div>

            </div>
           </div>

            {/* Bottom padding for mobile */}
            <div className="h-8 md:h-4" />
          </form>
        </div>
      </div>
    </>
  );
}
