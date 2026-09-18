"use client";

import React, { useState, useEffect, useMemo, useCallback } from "react";
import { getTimeline } from "@/lib/api";
import { TimelineDept, TimelineEvent, EventType } from "@/lib/types";
import { getTypeColor } from "@/lib/eventColors";

// ── 상수 ────────────────────────────────────────────────
const TIMELINE_START = 9;
const TIMELINE_END   = 24;
const TIMELINE_HOURS = TIMELINE_END - TIMELINE_START;
const HOUR_PX        = 80;
const TIMELINE_WIDTH = TIMELINE_HOURS * HOUR_PX;
const NAME_COL       = 140;
const HEADER_H       = 36;
const DEPT_H         = 28;
const HOURS          = Array.from({ length: TIMELINE_HOURS + 1 }, (_, i) => i + TIMELINE_START);

const TYPE_BG: Record<EventType, string> = {
  출장: "#A889A1",
  휴가: "#FFFF8D",
  일반: "",
};

// ── 유틸 ────────────────────────────────────────────────
function toDateStr(d: Date) {
  return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,"0")}-${String(d.getDate()).padStart(2,"0")}`;
}

function parseHour(dtStr: string): number {
  const t = dtStr.split(" ")[1] ?? dtStr.split("T")[1] ?? "00:00:00";
  const [h, m] = t.split(":").map(Number);
  return h + m / 60;
}

function getEventBg(ev: TimelineEvent): string {
  return ev.event_type === "일반" ? (ev.event_color || "#868E96") : TYPE_BG[ev.event_type];
}

function getEventText(ev: TimelineEvent): string {
  return getTypeColor(ev.title)?.text ?? "#FFFFFF";
}

function getTimedPos(ev: TimelineEvent): { left: number; width: number } | null {
  if (ev.is_all_day) return null;
  const s = Math.max(TIMELINE_START, Math.min(TIMELINE_END, parseHour(ev.start_dt)));
  const e = Math.max(s + 0.1, Math.min(TIMELINE_END, parseHour(ev.end_dt)));
  if (s >= TIMELINE_END || e <= TIMELINE_START) return null;
  return {
    left:  (s - TIMELINE_START) * HOUR_PX,
    width: Math.max(6, (e - s) * HOUR_PX),
  };
}

function fmtTime(dtStr: string) {
  return (dtStr.split(" ")[1] ?? "00:00:00").slice(0, 5);
}

// ── 툴팁 ────────────────────────────────────────────────
interface TooltipState { ev: TimelineEvent; x: number; y: number }

function Tooltip({ data }: { data: TooltipState }) {
  const bg = getEventBg(data.ev);
  return (
    <div className="fixed z-[9999] pointer-events-none" style={{ left: data.x + 14, top: data.y - 12 }}>
      <div className="bg-bg-primary border border-border rounded-xl shadow-2xl p-3 w-52">
        <div className="flex items-center gap-2 mb-1.5">
          <span className="w-2.5 h-2.5 rounded-full shrink-0" style={{ backgroundColor: bg }} />
          <span className="text-sm font-semibold text-txt-primary truncate">{data.ev.title}</span>
        </div>
        {data.ev.is_all_day ? (
          <p className="text-xs text-txt-secondary">종일 일정</p>
        ) : (
          <p className="text-xs text-txt-secondary tabular-nums">
            {fmtTime(data.ev.start_dt)} ~ {fmtTime(data.ev.end_dt)}
          </p>
        )}
        {data.ev.event_type !== "일반" && (
          <span className="mt-2 inline-flex items-center text-[10px] font-bold px-2 py-0.5 rounded-full"
            style={{ backgroundColor: bg, color: getEventText(data.ev) }}>
            {data.ev.event_type}
          </span>
        )}
      </div>
    </div>
  );
}

// ── 이벤트 블록 — pill 형태 ──────────────────────────────
function EventBlock({ ev, onHover, onLeave }: {
  ev: TimelineEvent;
  onHover: (ev: TimelineEvent, x: number, y: number) => void;
  onLeave: () => void;
}) {
  const pos = getTimedPos(ev);
  if (!pos) return null;
  const bg          = getEventBg(ev);
  const isHighlight = ev.event_type !== "일반";
  return (
    <div
      className="absolute flex items-center px-2.5 overflow-hidden cursor-default select-none"
      style={{
        left: pos.left,
        width: pos.width,
        top: 6,
        bottom: 6,
        backgroundColor: bg,
        borderRadius: 999,
        zIndex: isHighlight ? 3 : 2,
        boxShadow: isHighlight
          ? "0 2px 8px rgba(0,0,0,0.20)"
          : "0 1px 3px rgba(0,0,0,0.10)",
        opacity: isHighlight ? 1 : 0.80,
      }}
      onMouseMove={(e) => onHover(ev, e.clientX, e.clientY)}
      onMouseLeave={onLeave}
    >
      <span className="text-[11px] font-semibold truncate leading-none"
        style={{ color: getEventText(ev) }}>{ev.title}</span>
    </div>
  );
}

// ── 종일 배너 — pill ─────────────────────────────────────
function AllDayBanner({ events, onHover, onLeave }: {
  events: TimelineEvent[];
  onHover: (ev: TimelineEvent, x: number, y: number) => void;
  onLeave: () => void;
}) {
  return (
    <div className="flex gap-1 px-1 py-0.5">
      {events.map((ev) => (
        <div key={ev.event_id}
          className="flex-1 h-5 flex items-center px-2.5 cursor-default select-none min-w-0"
          style={{ backgroundColor: getEventBg(ev), borderRadius: 999 }}
          onMouseMove={(e) => onHover(ev, e.clientX, e.clientY)}
          onMouseLeave={onLeave}
        >
          <span className="text-[10px] font-bold truncate"
            style={{ color: getEventText(ev) }}>
            {ev.event_type !== "일반" ? `[${ev.event_type}] ` : ""}{ev.title}
          </span>
        </div>
      ))}
    </div>
  );
}

// ── 사원 행 — zebra ──────────────────────────────────────
function UserRow({ user, rowIndex, onHover, onLeave }: {
  user: { apwid: number; name: string; events: TimelineEvent[] };
  rowIndex: number;
  onHover: (ev: TimelineEvent, x: number, y: number) => void;
  onLeave: () => void;
}) {
  const allDay       = user.events.filter((e) => e.is_all_day);
  const timed        = user.events.filter((e) => !e.is_all_day);
  const hasAllDay    = allDay.length > 0;
  const hasHighlight = user.events.some((e) => e.event_type !== "일반");
  const rowH         = hasAllDay ? 60 : 40;

  // zebra: bg-bg-secondary(짝수) / bg-bg-primary(홀수), 하이라이트 행은 별도
  const zebraClass = rowIndex % 2 === 0 ? "bg-bg-secondary" : "bg-bg-primary";
  const rowClass   = hasHighlight ? "bg-orange-500/[0.04] dark:bg-orange-400/[0.05]" : zebraClass;

  return (
    <div className={`flex border-b border-border/30 ${rowClass}`} style={{ height: rowH }}>
      {/* 이름 — sticky left, 불투명 배경 명시 */}
      <div
        className={`shrink-0 sticky left-0 z-[5] border-r border-border/30 flex items-center px-3 ${zebraClass}`}
        style={{ width: NAME_COL }}
      >
        <p className="text-sm font-medium text-txt-primary truncate">{user.name}</p>
      </div>

      {/* 타임라인 */}
      <div className="relative flex flex-col" style={{ width: TIMELINE_WIDTH, minWidth: TIMELINE_WIDTH }}>
        {/* 그리드 라인 — 3h는 실선, 1h는 점선으로 극도로 옅게 */}
        <div className="absolute inset-0 pointer-events-none">
          {HOURS.map((h) => {
            const is3h = h % 3 === 0;
            return (
              <div
                key={h}
                className="absolute top-0 bottom-0"
                style={{
                  left: (h - TIMELINE_START) * HOUR_PX,
                  width: 1,
                  backgroundColor: is3h
                    ? "rgba(0,0,0,0.09)"
                    : "rgba(0,0,0,0.04)",
                  borderLeft: is3h ? undefined : "1px dashed rgba(0,0,0,0.05)",
                }}
              />
            );
          })}
        </div>

        {/* 종일 배너 */}
        {hasAllDay && (
          <div style={{ height: 28 }} className="flex items-center">
            <div style={{ width: TIMELINE_WIDTH }}>
              <AllDayBanner events={allDay} onHover={onHover} onLeave={onLeave} />
            </div>
          </div>
        )}

        {/* 시간 이벤트 */}
        <div className="relative flex-1">
          {timed.map((ev) => (
            <EventBlock key={ev.event_id} ev={ev} onHover={onHover} onLeave={onLeave} />
          ))}
        </div>
      </div>
    </div>
  );
}

// ── 메인 ────────────────────────────────────────────────
export default function TimelineView({ selectedDate }: { selectedDate: Date }) {
  const [depts,   setDepts]   = useState<TimelineDept[]>([]);
  const [loading, setLoading] = useState(false);
  const [tooltip, setTooltip] = useState<TooltipState | null>(null);

  const dateStr = useMemo(() => toDateStr(selectedDate), [selectedDate]);

  useEffect(() => {
    setLoading(true);
    getTimeline(dateStr)
      .then((d) => setDepts(d ?? []))
      .catch((e) => console.error("[Timeline]", e))
      .finally(() => setLoading(false));
  }, [dateStr]);

  const handleHover  = useCallback((ev: TimelineEvent, x: number, y: number) => setTooltip({ ev, x, y }), []);
  const handleLeave  = useCallback(() => setTooltip(null), []);

  // 출장 / 휴가 카운트
  const stats = useMemo(() => {
    let chulgang = 0, hyuga = 0;
    for (const dept of depts)
      for (const user of dept.users)
        for (const ev of user.events) {
          if (ev.event_type === "출장") chulgang++;
          else if (ev.event_type === "휴가") hyuga++;
        }
    return { chulgang, hyuga };
  }, [depts]);

  return (
    <div className="flex-1 overflow-auto bg-bg-primary">
      <div style={{ minWidth: NAME_COL + TIMELINE_WIDTH }}>

        {/* 시간축 헤더 — sticky top */}
        <div className="flex sticky top-0 z-20 bg-bg-primary border-b-2 border-border shadow-sm"
          style={{ height: HEADER_H }}>
          {/* 코너 */}
          <div className="shrink-0 sticky left-0 z-30 bg-bg-primary border-r border-border/40 flex items-center px-3 gap-1.5"
            style={{ width: NAME_COL }}>
            <span className="text-[11px] font-semibold text-txt-secondary uppercase tracking-wide">이름</span>
            {/* 출장 / 휴가 배지 */}
            {stats.chulgang > 0 && (
              <span className="text-[9px] font-bold px-1.5 py-0.5 rounded leading-none"
                style={{ backgroundColor: TYPE_BG["출장"], color: getTypeColor("출장")?.text ?? "#FFF" }}>
                출장 {stats.chulgang}
              </span>
            )}
            {stats.hyuga > 0 && (
              <span className="text-[9px] font-bold px-1.5 py-0.5 rounded leading-none"
                style={{ backgroundColor: TYPE_BG["휴가"], color: getTypeColor("휴가")?.text ?? "#FFF" }}>
                휴가 {stats.hyuga}
              </span>
            )}
          </div>
          {/* 시간 마커 */}
          <div className="relative" style={{ width: TIMELINE_WIDTH }}>
            {HOURS.filter((h) => h % 3 === 0).map((h) => {
              const leftPx = (h - TIMELINE_START) * HOUR_PX;
              const isFirst = h === TIMELINE_START;
              return (
                <React.Fragment key={h}>
                  <span
                    className="absolute text-[11px] font-medium text-txt-primary select-none"
                    style={{
                      left: leftPx,
                      top: "50%",
                      transform: `translateY(-50%) translateX(${isFirst ? "2px" : "-50%"})`,
                    }}
                  >
                    {h === 24 ? "00:00" : `${String(h).padStart(2, "0")}:00`}
                  </span>
                  <div
                    className="absolute bottom-0"
                    style={{ left: leftPx, width: 1, height: 6, backgroundColor: "rgba(0,0,0,0.15)" }}
                  />
                </React.Fragment>
              );
            })}
          </div>
        </div>

        {/* 본문 */}
        {loading ? (
          <div className="flex items-center justify-center h-40 text-txt-secondary text-sm">불러오는 중...</div>
        ) : depts.length === 0 ? (
          <div className="flex items-center justify-center h-40 text-txt-secondary text-sm">데이터가 없습니다</div>
        ) : (
          depts.map((dept) => (
            <div key={dept.dept_code}>
              {/* 부서 헤더 — 좌측 accent 바 */}
              <div className="flex sticky z-[15] border-b border-border/30 bg-bg-secondary"
                style={{ top: HEADER_H, height: DEPT_H }}>
                <div
                  className="shrink-0 sticky left-0 z-[16] bg-bg-secondary flex items-center px-3"
                  style={{
                    width: NAME_COL,
                    borderLeft: "3px solid #4263EB",
                    borderRight: "1px solid rgba(0,0,0,0.07)",
                  }}
                >
                  <span className="text-[11px] font-bold text-txt-secondary tracking-widest uppercase">
                    {dept.dept_name}
                  </span>
                </div>
                <div style={{ width: TIMELINE_WIDTH }} />
              </div>

              {/* 사원 행 */}
              {dept.users.map((user, i) => (
                <UserRow
                  key={user.apwid}
                  user={user}
                  rowIndex={i}
                  onHover={handleHover}
                  onLeave={handleLeave}
                />
              ))}
            </div>
          ))
        )}
      </div>

      {tooltip && <Tooltip data={tooltip} />}
    </div>
  );
}
