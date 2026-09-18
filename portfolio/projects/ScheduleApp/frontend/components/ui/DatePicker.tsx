"use client";

import React, { useState, useRef, useEffect } from "react";

interface DatePickerProps {
  label?: string;
  value: string; // "YYYY-MM-DD"
  onChange: (value: string) => void;
}

export default function DatePicker({ label, value, onChange }: DatePickerProps) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  // value에서 표시할 연/월 계산
  const parsed = value ? value.split("-").map(Number) : null;
  const [viewYear, setViewYear] = useState(parsed ? parsed[0] : new Date().getFullYear());
  const [viewMonth, setViewMonth] = useState(parsed ? parsed[1] : new Date().getMonth() + 1);

  // value 변경 시 viewYear/viewMonth 동기화
  useEffect(() => {
    if (value) {
      const [y, m] = value.split("-").map(Number);
      setViewYear(y);
      setViewMonth(m);
    }
  }, [value]);

  // 외부 클릭 시 닫기
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    if (open) document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [open]);

  const daysInMonth = new Date(viewYear, viewMonth, 0).getDate();
  const firstDayOfWeek = new Date(viewYear, viewMonth - 1, 1).getDay(); // 0=Sun

  const prevMonth = () => {
    if (viewMonth === 1) { setViewYear(viewYear - 1); setViewMonth(12); }
    else setViewMonth(viewMonth - 1);
  };
  const nextMonth = () => {
    if (viewMonth === 12) { setViewYear(viewYear + 1); setViewMonth(1); }
    else setViewMonth(viewMonth + 1);
  };

  const selectDate = (day: number) => {
    const v = `${viewYear}-${String(viewMonth).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
    onChange(v);
    setOpen(false);
  };

  const today = new Date();
  const todayStr = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}-${String(today.getDate()).padStart(2, "0")}`;

  const days: (number | null)[] = [];
  for (let i = 0; i < firstDayOfWeek; i++) days.push(null);
  for (let d = 1; d <= daysInMonth; d++) days.push(d);

  return (
    <div className="w-full relative" ref={ref}>
      {label && (
        <label className="block text-sm font-medium text-txt-primary mb-1">{label}</label>
      )}
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="w-full px-3 py-2 border border-border rounded-lg text-sm text-txt-primary bg-bg-primary focus:outline-none focus:ring-2 focus:ring-accent focus:border-transparent text-left flex items-center justify-between"
      >
        <span>{value || "날짜 선택"}</span>
        <svg className="w-4 h-4 text-txt-secondary" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" />
        </svg>
      </button>

      {open && (
        <div className="absolute z-[100] mt-1 bg-bg-primary border border-border rounded-lg shadow-lg p-3 w-[280px]">
          {/* Header: 이전/다음 월 */}
          <div className="flex items-center justify-between mb-2">
            <button type="button" onClick={prevMonth} className="w-7 h-7 flex items-center justify-center rounded hover:bg-bg-secondary text-txt-secondary">
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" /></svg>
            </button>
            <span className="text-sm font-semibold text-txt-primary">
              {viewYear}년 {viewMonth}월
            </span>
            <button type="button" onClick={nextMonth} className="w-7 h-7 flex items-center justify-center rounded hover:bg-bg-secondary text-txt-secondary">
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" /></svg>
            </button>
          </div>

          {/* 요일 헤더 */}
          <div className="grid grid-cols-7 mb-1">
            {["일", "월", "화", "수", "목", "금", "토"].map((d) => (
              <div key={d} className="text-center text-xs text-txt-secondary py-1">{d}</div>
            ))}
          </div>

          {/* 날짜 그리드 */}
          <div className="grid grid-cols-7">
            {days.map((day, i) => {
              if (day === null) return <div key={`e-${i}`} />;
              const dateStr = `${viewYear}-${String(viewMonth).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
              const isSelected = dateStr === value;
              const isToday = dateStr === todayStr;

              return (
                <button
                  key={day}
                  type="button"
                  onClick={() => selectDate(day)}
                  className={`w-9 h-9 flex items-center justify-center rounded-full text-sm transition-colors
                    ${isSelected ? "bg-accent text-accent-contrast font-bold" : ""}
                    ${isToday && !isSelected ? "bg-bg-secondary font-bold text-accent" : ""}
                    ${!isSelected && !isToday ? "text-txt-primary hover:bg-bg-secondary" : ""}
                  `}
                >
                  {day}
                </button>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
