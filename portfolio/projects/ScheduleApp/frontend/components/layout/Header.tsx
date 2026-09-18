"use client";

import React, { useState, useRef, useEffect } from "react";
import Link from "next/link";
import { useTheme } from "next-themes";
import { syncKakaoICS } from "@/lib/api";
import { useAccentColor, ACCENT_COLORS } from "@/components/accent-provider";

const DAILY_LIST_EMPNOS: number[] = [4317, 4210, 3023, 4220, 4079, 4140];

export type ViewMode = "month" | "week";

interface HeaderProps {
  currentMonth: string;
  onPrevMonth: () => void;
  onNextMonth: () => void;
  onToday: () => void;
  onToggleSidebar?: () => void;
  userName?: string;
  empno: number;
  onSync?: () => void;
  onRefresh?: () => void;
  viewMode?: ViewMode;
  onViewChange?: (mode: ViewMode) => void;
  showTeamToggle?: boolean;
  teamView?: "mine" | "team";
  onTeamViewChange?: (v: "mine" | "team") => void;
}

export default function Header({
  currentMonth,
  onPrevMonth,
  onNextMonth,
  onToday,
  onToggleSidebar,
  userName,
  empno,
  onSync,
  onRefresh,
  viewMode = "month",
  onViewChange,
  showTeamToggle,
  teamView = "mine",
  onTeamViewChange,
}: HeaderProps) {
  const [syncing, setSyncing] = useState(false);
  const [showAccentPicker, setShowAccentPicker] = useState(false);
  const accentPickerRef = useRef<HTMLDivElement>(null);
  const { theme, setTheme } = useTheme();
  const { accentColor, setAccentColor } = useAccentColor();

  const isOwner = empno === 4220;
  const canSeeDailyList = DAILY_LIST_EMPNOS.includes(empno);

  // Close accent picker on outside click
  useEffect(() => {
    if (!showAccentPicker) return;
    const handler = (e: MouseEvent) => {
      if (accentPickerRef.current && !accentPickerRef.current.contains(e.target as Node)) {
        setShowAccentPicker(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [showAccentPicker]);

  const cycleTheme = () => {
    if (theme === "light") setTheme("dark");
    else if (theme === "dark") setTheme("system");
    else setTheme("light");
  };

  const handleSync = async () => {
    setSyncing(true);
    try {
      await syncKakaoICS(empno);
      onSync?.();
    } catch (err: unknown) {
      console.error("[카카오 ICS 동기화]", err);
    } finally {
      setSyncing(false);
    }
  };

  return (
    <header className="sticky top-0 z-30 bg-bg-primary border-b border-border">
      <div className="flex items-center justify-between px-4 py-3">
        {/* Left: Menu + Navigation */}
        <div className="flex items-center gap-2">
          {onToggleSidebar && (
            <button
              onClick={onToggleSidebar}
              className="hidden md:flex p-2 rounded-lg hover:bg-bg-secondary transition-colors"
              aria-label="Toggle sidebar"
            >
              <svg className="w-5 h-5 text-txt-primary" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h16" />
              </svg>
            </button>
          )}

          <button
            onClick={onPrevMonth}
            className="p-2 rounded-lg hover:bg-bg-secondary transition-colors"
            aria-label="Previous month"
          >
            <svg className="w-5 h-5 text-txt-primary" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
            </svg>
          </button>

          <h1 className="text-lg font-bold text-txt-primary min-w-[140px] text-center">
            {currentMonth}
          </h1>

          <button
            onClick={onNextMonth}
            className="p-2 rounded-lg hover:bg-bg-secondary transition-colors"
            aria-label="Next month"
          >
            <svg className="w-5 h-5 text-txt-primary" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
            </svg>
          </button>

          <button
            onClick={onToday}
            className="ml-1 px-3 py-1 text-sm font-medium bg-accent text-accent-contrast rounded-full hover:brightness-110 transition-colors"
          >
            오늘
          </button>
        </div>

        {/* 중앙: 뷰 탭 (숨김) */}

        {/* Right: Team toggle + tools */}
        <div className="flex items-center gap-2">
          {showTeamToggle && (
            <div style={{ display: "flex", border: "1px solid var(--border-color,#e9ecef)", borderRadius: 8, overflow: "hidden" }}>
              {(["mine", "team"] as const).map((v) => (
                <button
                  key={v}
                  onClick={() => onTeamViewChange?.(v)}
                  style={{
                    padding: "4px 12px",
                    fontSize: 12,
                    fontWeight: teamView === v ? 600 : 400,
                    background: teamView === v ? "var(--accent-color,#4C6EF5)" : "transparent",
                    color: teamView === v ? "var(--accent-contrast,#fff)" : "var(--text-secondary,#868e96)",
                    border: "none",
                    cursor: "pointer",
                    transition: "background 0.15s",
                  }}
                >
                  {v === "mine" ? "내 일정" : "팀 전체"}
                </button>
              ))}
            </div>
          )}
          {canSeeDailyList && (
            <Link
              href={`/daily-list?empno=${empno}`}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-bg-secondary hover:bg-bg-secondary/70 text-txt-primary text-xs font-medium transition-colors"
              title="출장리스트"
            >
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2" />
              </svg>
              <span className="hidden md:inline">출장리스트</span>
            </Link>
          )}

          {isOwner && (
            <button
              onClick={handleSync}
              disabled={syncing}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-[#FEE500] hover:bg-[#F5DC00] transition-colors disabled:opacity-60 disabled:cursor-not-allowed"
              title="톡캘린더 동기화"
            >
              {syncing ? (
                <svg className="w-4 h-4 animate-spin text-[#3C1E1E]" fill="none" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8z" />
                </svg>
              ) : (
                <svg className="w-4 h-4" viewBox="0 0 24 24" fill="#3C1E1E">
                  <path d="M12 3C6.48 3 2 6.58 2 10.9c0 2.78 1.86 5.21 4.65 6.6-.15.53-.96 3.41-1 3.57 0 .09.03.18.1.24.08.05.18.06.26.02.35-.07 4.06-2.68 4.57-3.03.46.06.93.1 1.42.1 5.52 0 10-3.58 10-7.5C22 6.58 17.52 3 12 3z"/>
                </svg>
              )}
              <span className="text-xs font-bold text-[#3C1E1E] hidden md:inline">
                {syncing ? "동기화 중..." : "톡캘린더"}
              </span>
            </button>
          )}

          {userName && (
            <span className="hidden md:inline text-sm text-txt-secondary">
              {userName}
            </span>
          )}
          {/* Accent color picker */}
          <div className="relative" ref={accentPickerRef}>
            <button
              onClick={() => setShowAccentPicker(!showAccentPicker)}
              className="p-1.5 rounded-lg hover:bg-bg-secondary transition-colors"
              title="테마 색상"
            >
              <div
                className="w-4 h-4 rounded-full border-2 border-bg-secondary"
                style={{ backgroundColor: accentColor }}
              />
            </button>
            {showAccentPicker && (
              <div className="absolute right-0 mt-2 p-3 bg-bg-primary border border-border rounded-xl shadow-lg z-50 w-[232px]">
                <p className="text-xs font-medium text-txt-secondary mb-2">테마 색상</p>
                <div className="grid grid-cols-6 gap-1.5">
                  {ACCENT_COLORS.map((color) => (
                    <button
                      key={color}
                      onClick={() => {
                        setAccentColor(color);
                        setShowAccentPicker(false);
                      }}
                      className="w-8 h-8 rounded-lg flex items-center justify-center hover:scale-110 transition-transform"
                      style={{ backgroundColor: color }}
                      title={color}
                    >
                      {accentColor === color && (
                        <svg className="w-4 h-4 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={3}>
                          <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                        </svg>
                      )}
                    </button>
                  ))}
                </div>
              </div>
            )}
          </div>

          {/* Theme toggle */}
          <button
            onClick={cycleTheme}
            className="p-1.5 rounded-lg hover:bg-bg-secondary transition-colors"
            title={`테마: ${theme === "light" ? "라이트" : theme === "dark" ? "다크" : "시스템"}`}
          >
            {theme === "dark" ? (
              <svg className="w-4 h-4 text-txt-secondary" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M20.354 15.354A9 9 0 018.646 3.646 9.003 9.003 0 0012 21a9.003 9.003 0 008.354-5.646z" />
              </svg>
            ) : theme === "light" ? (
              <svg className="w-4 h-4 text-txt-secondary" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 3v1m0 16v1m9-9h-1M4 12H3m15.364 6.364l-.707-.707M6.343 6.343l-.707-.707m12.728 0l-.707.707M6.343 17.657l-.707.707M16 12a4 4 0 11-8 0 4 4 0 018 0z" />
              </svg>
            ) : (
              <svg className="w-4 h-4 text-txt-secondary" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9.75 17L9 20l-1 1h8l-1-1-.75-3M3 13h18M5 17h14a2 2 0 002-2V5a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" />
              </svg>
            )}
          </button>

          {onRefresh && (
            <button
              onClick={onRefresh}
              className="p-1.5 rounded-lg hover:bg-bg-secondary transition-colors"
              title="일정 새로고침"
            >
              <svg className="w-4 h-4 text-txt-secondary" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
              </svg>
            </button>
          )}
        </div>
      </div>
    </header>
  );
}
