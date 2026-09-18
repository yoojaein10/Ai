"use client";

import React, {
  Suspense,
  startTransition,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { useSearchParams } from "next/navigation";
import Link from "next/link";
import { getDailyList, getHolidays, DailyListUser, DailyListDoc } from "@/lib/api";

// ═══════════════════════════════════════════════════════════════════════════════
// Config
// ═══════════════════════════════════════════════════════════════════════════════

const ALLOWED_EMPNOS = [4220, 4317, 3023, 4210, 4079, 4140];

const DEPT_ORDER = ["pg1", "pg2", "su"] as const;
const DEPT_META: Record<string, { label: string; accent: string }> = {
  pg1: { label: "평가1팀",   accent: "#5C7CFA" },
  pg2: { label: "평가2팀",   accent: "#51CF66" },
  su:  { label: "수습평가사", accent: "#FF922B" },
};

// LStatus 배지 색상
function getLStatusStyle(s: string): { background: string; color: string } {
  if (!s) return { background: "#f3f4f6", color: "#9ca3af" };
  if (s.includes("발송"))                              return { background: "#e9ecef", color: "#495057" };
  if (s.includes("2차심사") || s.includes("1차심사")) return { background: "#f3d9fa", color: "#862e9c" };
  if (s.includes("심사"))                              return { background: "#e5dbff", color: "#7048e8" };
  if (s.includes("작성"))                               return { background: "#d3f9d8", color: "#2f9e44" };
  if (s.includes("출장"))                              return { background: "#ffe8cc", color: "#d9480f" };
  if (s.includes("접수"))                              return { background: "#dbe4ff", color: "#3b5bdb" };
  return { background: "#f1f3f5", color: "#495057" };
}

// ═══════════════════════════════════════════════════════════════════════════════
// Layout 상수
// ═══════════════════════════════════════════════════════════════════════════════

const BORDER     = "1px solid var(--border-color,#e5e7eb)";
const WEEKEND_BG = "rgba(0,0,0,0.018)";
const TODAY_BG   = "rgba(92,124,250,0.06)";
const TODAY_INSET= "inset 2px 0 0 rgba(92,124,250,0.4), inset -2px 0 0 rgba(92,124,250,0.4)";
const NAME_W     = 90;
const NAME_SX    = { borderRight: BORDER };
const DOC_W      = 110;
const DOC_LEFT   = NAME_W;
const DOC_SX     = { borderRight: BORDER };
const ADDR_W     = 100;
const ADDR_LEFT  = NAME_W + DOC_W;
const ADDR_SX    = { borderRight: BORDER };
const META_W     = 72;
const META_LEFT  = NAME_W + DOC_W + ADDR_W;
const META_SX    = { borderRight: BORDER };
const CELL_W     = 70;

// ═══════════════════════════════════════════════════════════════════════════════
// StatusTooltip
// ═══════════════════════════════════════════════════════════════════════════════

interface TooltipItem  { label: string; color: string; days?: number[] }
interface TooltipState { x: number; y: number; dateLabel: string; items: TooltipItem[] }

function fmtDays(days?: number[]): string {
  if (!days || days.length === 0) return "";
  const s = [...days].sort((a, b) => a - b);
  if (s.length === 1) return `(${s[0]}일)`;
  const consecutive = s.every((d, i) => i === 0 || d === s[i - 1] + 1);
  return consecutive ? `(${s[0]}~${s[s.length - 1]}일)` : `(${s.join("·")}일)`;
}

function StatusTooltip({ x, y, dateLabel, items }: TooltipState) {
  // 툴팁 예상 높이: 상하 패딩(16) + 헤더(26) + 항목당 20px
  const estimatedH = 16 + 26 + items.length * 20;
  const left = x + 14 + 160 > window.innerWidth ? x - 160 - 6 : x + 14;
  // 아래로 넘치면 커서 위쪽으로 뒤집기
  const top  = y + estimatedH > window.innerHeight ? y - estimatedH - 4 : y - 10;
  return (
    <div style={{
      position: "fixed", left, top, zIndex: 9999,
      background: "#1c1d20", color: "#fff", borderRadius: 8,
      padding: "8px 12px", boxShadow: "0 4px 20px rgba(0,0,0,0.4)",
      pointerEvents: "none", minWidth: 130,
    }}>
      <div style={{ fontSize: 11, color: "#868e96", marginBottom: 6, fontWeight: 600 }}>{dateLabel}</div>
      {items.map((item, i) => (
        <div key={i} style={{ display: "flex", alignItems: "center", gap: 7, marginBottom: i < items.length - 1 ? 4 : 0 }}>
          <span style={{ width: 8, height: 8, borderRadius: "50%", background: item.color, flexShrink: 0 }} />
          <span style={{ fontSize: 12, fontWeight: 500, whiteSpace: "nowrap" }}>
            {item.label}<span style={{ fontSize: 11, opacity: 0.7, marginLeft: 2 }}>{fmtDays(item.days)}</span>
          </span>
        </div>
      ))}
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════════════════
// UserSection
// ═══════════════════════════════════════════════════════════════════════════════

interface UserSectionProps {
  user:             DailyListUser;
  isCollapsed:      boolean;
  onToggle:         (apwid: number) => void;
  days:             number[];
  visibleStart:     number;
  getDow:           (d: number) => number;
  todayDay:         number;
  year:             number;
  month:            number;
  monthState:       "past" | "current" | "future";
  firstBusinessDay: number;
  ganttStartDay:    number | null;
  ganttEndDay:      number | null;
  onCellHover:      (x: number, y: number, dateLabel: string, items: TooltipItem[]) => void;
  onCellLeave:      () => void;
}

const UserSection = React.memo(function UserSection({
  user, isCollapsed, onToggle, days, visibleStart, getDow, todayDay, year, month,
  monthState, firstBusinessDay, ganttStartDay, ganttEndDay, onCellHover, onCellLeave,
}: UserSectionProps) {
  const docCount  = user.docs.length;
  const canToggle = docCount > 0;

  return (
    <React.Fragment>
      {/* 담당자 행 */}
      <tr
        style={{ borderBottom: BORDER, cursor: canToggle ? "pointer" : "default" }}
        className={canToggle ? "hover:bg-bg-secondary/25 transition-colors" : ""}
        onClick={() => canToggle && onToggle(user.apwid)}
      >
        <td className="sticky left-0 bg-bg-primary align-middle" style={{ padding: "0 8px", height: 32, minWidth: NAME_W, zIndex: 40, ...NAME_SX }}>
          <div className="flex items-center gap-1.5" style={{ overflow: "visible" }}>
            {canToggle && (
              <svg className="w-3.5 h-3.5 flex-shrink-0 transition-transform duration-200" style={{ color: "var(--txt-secondary,#9ca3af)", transform: isCollapsed ? "rotate(-90deg)" : "rotate(0)" }} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
              </svg>
            )}
            <span className="text-xs font-semibold text-txt-primary whitespace-nowrap">{user.name}</span>
            {canToggle && (
              <span className="flex-shrink-0 rounded-full font-semibold" style={{ fontSize: 10, lineHeight: 1.4, padding: "1px 6px", background: "rgba(92,124,250,0.1)", color: "#5C7CFA" }}>
                {docCount}
              </span>
            )}
          </div>
        </td>
        <td className="sticky bg-bg-primary align-middle" style={{ left: DOC_LEFT, padding: "0 8px", height: 32, zIndex: 40, ...DOC_SX }}>
          {!canToggle && <span className="text-xs" style={{ color: "var(--txt-secondary,#9ca3af)", opacity: 0.4 }}>—</span>}
        </td>
        <td className="sticky bg-bg-primary" style={{ left: ADDR_LEFT, height: 32, zIndex: 40, ...ADDR_SX }} />
        <td className="sticky bg-bg-primary" style={{ left: META_LEFT, height: 32, zIndex: 40, ...META_SX }} />
        {days.map((d) => {
          const dow = getDow(d);
          const isToday = d === todayDay;
          const isWeekend = dow === 0 || dow === 6;
          return (
            <td key={d} style={{ height: 32, padding: 0, background: isToday ? TODAY_BG : isWeekend ? WEEKEND_BG : undefined, boxShadow: isToday ? TODAY_INSET : undefined }} />
          );
        })}
      </tr>

      {/* 감정서 행들 */}
      {!isCollapsed && user.docs.map((doc) => (
        <tr key={doc.docNo} style={{ borderBottom: BORDER }} className="hover:bg-bg-secondary/30 transition-colors">
          <td className="sticky left-0 bg-bg-primary" style={{ height: 32, zIndex: 40, ...NAME_SX }} />
          {/* 감정서 번호 + lStatus */}
          <td className="sticky bg-bg-primary align-middle" style={{ left: DOC_LEFT, padding: "0 8px", height: 32, zIndex: 40, ...DOC_SX }}>
            <div className="flex flex-col justify-center" style={{ gap: 2 }}>
              <span className="text-txt-secondary whitespace-nowrap" style={{ fontSize: 11, fontFamily: "'Roboto Mono','Consolas',monospace" }}>
                {doc.docNo}
              </span>
              {doc.lStatus && (
                <span style={{ fontSize: 10, fontWeight: 600, padding: "1px 6px", borderRadius: 99, display: "inline-block", width: "fit-content", ...getLStatusStyle(doc.lStatus) }}>
                  {doc.lStatus}
                </span>
              )}
            </div>
          </td>
          {/* 주소 */}
          <td className="sticky bg-bg-primary align-middle" style={{ left: ADDR_LEFT, padding: "0 6px", height: 32, zIndex: 40, ...ADDR_SX }} title={doc.address || undefined}>
            {doc.address && (
              <span className="truncate block" style={{ fontSize: 11, fontWeight: 600, color: "#4C6EF5", maxWidth: ADDR_W - 12 }}>
                {doc.address}
              </span>
            )}
          </td>
          {/* 업무구분(위) / 물건종류(아래) — 셀 반분 */}
          <td className="sticky bg-bg-primary" style={{ left: META_LEFT, padding: 0, height: 32, zIndex: 40, ...META_SX }}>
            <div style={{ display: "flex", flexDirection: "column", height: "100%" }}>
              <div className="flex items-center" style={{ flex: 1, padding: "0 6px", borderBottom: BORDER, overflow: "hidden" }}>
                <span className="whitespace-nowrap truncate" style={{ fontSize: 10, fontWeight: 500, color: "var(--txt-secondary,#6b7280)" }}>
                  {doc.workType}
                </span>
              </div>
              <div className="flex items-center" style={{ flex: 1, padding: "0 6px", overflow: "hidden" }}>
                <span className="whitespace-nowrap truncate" style={{ fontSize: 10, fontWeight: 600, color: "var(--txt-primary,#111827)" }}>
                  {doc.category}
                </span>
              </div>
            </div>
          </td>
          {/* 날짜 셀 — 파란 구간 colspan 병합으로 접수 라벨 진짜 가운데 정렬 */}
          {(() => {
            const pad = (n: number) => String(n).padStart(2, "0");
            const monthPrefix = `${year}-${pad(month)}`;

            // culJangDays: 미래 월은 전체 제외, 현재 월은 오늘 이하만, 과거 월은 전체 표시
            const allCulJangDays = doc.events
              .filter((e) => e.status === "출장" && e.date.startsWith(monthPrefix))
              .map((e) => parseInt(e.date.slice(8), 10))
              .sort((a, b) => a - b);
            const culJangDays =
              monthState === "future" ? [] :
              monthState === "current" ? allCulJangDays.filter((d) => d <= todayDay) :
              allCulJangDays; // "past": 전체

            // receiptDate가 이전 달이고 오늘까지의 당월 출장이 있으면 첫 업무일로 보정
            const receiptDateYM = doc.receiptDate ? doc.receiptDate.slice(0, 7) : null;
            const receiptDay =
              receiptDateYM === monthPrefix
                ? parseInt(doc.receiptDate!.slice(8), 10)
                : receiptDateYM !== null && receiptDateYM < monthPrefix && culJangDays.length > 0
                  ? firstBusinessDay
                  : null;

            const lastCulJang = culJangDays.length > 0 ? Math.max(...culJangDays) : null;

            // 평가작성종료(code 05)
            const jaksungDay = doc.events
              .filter((e) => e.status.includes("작성종료") && e.date.startsWith(monthPrefix))
              .map((e) => parseInt(e.date.slice(8), 10))
              .sort((a, b) => a - b)[0] ?? null;

            // 발송대기(code 69)
            const simsaDate = doc.events
              .filter((e) => e.status.includes("발송대기") && e.date.startsWith(monthPrefix))
              .map((e) => parseInt(e.date.slice(8), 10))
              .sort((a, b) => a - b)[0] ?? null;

            // 완료처리(code 72)
            const wanryoDate = doc.events
              .filter((e) => e.status.includes("완료처리") && e.date.startsWith(monthPrefix))
              .map((e) => parseInt(e.date.slice(8), 10))
              .sort((a, b) => a - b)[0] ?? null;

            // 접수 구간
            const blueStart = receiptDay;
            // 출장보다 작성완료가 빠른 경우: 접수는 작성완료 전날까지, 작성완료~출장 전날 별도 구간
            const preJaksung      = jaksungDay !== null && culJangDays.length > 0 && jaksungDay < culJangDays[0];
            // 접수 바 종료: 출장 전날 or 오늘 중 이른 쪽 (미래로 연장 방지)
            const rawBlueEnd      = culJangDays.length > 0
              ? (preJaksung ? jaksungDay! - 1 : culJangDays[0] - 1)
              : receiptDay;
            const blueEnd         = rawBlueEnd !== null && todayDay > 0
              ? Math.min(rawBlueEnd, todayDay)
              : rawBlueEnd;
            const preJaksungStart = preJaksung ? jaksungDay! : null;
            const preJaksungEnd   = preJaksung ? culJangDays[0] - 1 : null;

            // 작성·심사 시작점
            const afterStart = lastCulJang !== null
              ? lastCulJang + 1
              : receiptDay !== null ? receiptDay + 1 : null;

            // jaksungDay 가 afterStart 보다 이전이면 afterStart 기준
            const jaksungEff = jaksungDay !== null && afterStart !== null
              ? Math.max(jaksungDay, afterStart)
              : null;

            // 작성 구간: afterStart ~ jaksungEff(작성완료) or 오늘(작성중)
            let wStart: number | null = null;
            let wEnd:   number | null = null;
            let wLabel  = "작성중";
            // 심사 구간: 작성완료 이후 ~ 발송대기 전날 or 오늘
            let sStart: number | null = null;
            let sEnd:   number | null = null;
            let sLabel  = "심사중";
            // 발송대기 구간 (code 69): simsaDate ~ 완료처리 전날 or 오늘
            let bStart: number | null = null;
            let bEnd:   number | null = null;
            // 완료처리 구간 (code 72): 당일만
            let cStart: number | null = null;
            let cEnd:   number | null = null;

            // afterStart가 오늘 이후면 아직 출장 중 → 작성/심사 바 없음
            const afterInRange = afterStart !== null && (todayDay <= 0 || afterStart <= todayDay);

            // 작성완료가 출장일 이하 → 출장 셀에서 이미 표시됨, post-출장 작성 바 불필요
            const jaksungOnOrBeforeCul = jaksungDay !== null && lastCulJang !== null && jaksungDay <= lastCulJang;

            // 심사·발송대기·완료처리 구간 계산 헬퍼
            const calcSC = (start: number) => {
              if (simsaDate !== null) {
                if (simsaDate > start) {
                  // 정상: 심사 구간이 1일 이상 존재
                  sStart = start; sEnd = simsaDate - 1; sLabel = "심사완료";
                  if (wanryoDate !== null && wanryoDate > simsaDate) {
                    bStart = simsaDate; bEnd = wanryoDate - 1;
                    cStart = wanryoDate; cEnd = wanryoDate;
                  } else if (wanryoDate !== null && wanryoDate <= simsaDate) {
                    cStart = wanryoDate; cEnd = wanryoDate;
                  } else {
                    bStart = simsaDate; bEnd = todayDay > 0 ? todayDay : simsaDate;
                  }
                } else if (simsaDate === start) {
                  // 발송대기 = 작성완료 다음날: 심사완료 1칸 표시 후 발송대기는 다음날부터
                  const bNext = start + 1;
                  if (wanryoDate !== null && wanryoDate <= start) {
                    // 완료처리가 발송대기와 같은 날 → 완료처리 바만 (심사완료 바 생략)
                    cStart = wanryoDate; cEnd = wanryoDate;
                  } else {
                    sStart = start; sEnd = start; sLabel = "심사완료";
                    if (wanryoDate !== null && wanryoDate > bNext) {
                      bStart = bNext; bEnd = wanryoDate - 1;
                      cStart = wanryoDate; cEnd = wanryoDate;
                    } else if (wanryoDate !== null && wanryoDate <= bNext) {
                      cStart = wanryoDate; cEnd = wanryoDate;
                    } else {
                      bStart = bNext; bEnd = todayDay > 0 ? todayDay : bNext;
                    }
                  }
                } else {
                  // simsaDate < start: 발송대기가 출장 당일/이전 → 심사 바 없음, 원본 로직 유지
                  if (wanryoDate !== null && wanryoDate > simsaDate) {
                    bStart = simsaDate; bEnd = wanryoDate - 1;
                    cStart = wanryoDate; cEnd = wanryoDate;
                  } else if (wanryoDate !== null && wanryoDate <= simsaDate) {
                    cStart = wanryoDate; cEnd = wanryoDate;
                  } else {
                    bStart = simsaDate; bEnd = todayDay > 0 ? todayDay : simsaDate;
                  }
                }
              } else if (wanryoDate !== null && wanryoDate >= start) {
                // 발송대기 없이 완료처리만 있는 경우 → 심사중 구간 + 완료처리
                sStart = start; sEnd = wanryoDate - 1; sLabel = "심사중";
                cStart = wanryoDate; cEnd = wanryoDate;
              } else if (wanryoDate !== null) {
                // 완료처리가 start 이전 (작성완료와 같은 날) → 완료처리 바만
                cStart = wanryoDate; cEnd = wanryoDate;
              } else {
                // 심사중 (진행 중)
                sStart = start; sEnd = todayDay > 0 ? todayDay : start; sLabel = "심사중";
              }
            };

            if (afterInRange && afterStart !== null) {
              if (preJaksung || jaksungOnOrBeforeCul) {
                calcSC(afterStart);
              } else if (jaksungEff !== null) {
                const effEnd = todayDay > 0 ? Math.min(jaksungEff, todayDay) : jaksungEff;
                if (simsaDate !== null && simsaDate <= effEnd) {
                  // 발송대기가 작성완료 당일 → 작성완료 바를 simsaDate-1까지, 발송대기 직접 설정
                  wStart = afterStart; wEnd = simsaDate - 1; wLabel = "작성완료";
                  if (wanryoDate !== null && wanryoDate > simsaDate) {
                    bStart = simsaDate; bEnd = wanryoDate - 1;
                    cStart = wanryoDate; cEnd = wanryoDate;
                  } else if (wanryoDate !== null && wanryoDate <= simsaDate) {
                    cStart = wanryoDate; cEnd = wanryoDate;
                  } else {
                    bStart = simsaDate; bEnd = todayDay > 0 ? todayDay : simsaDate;
                  }
                } else {
                  // 완료처리가 작성완료 당일이면 작성완료 바를 하루 줄여 완료처리 바 렌더링 공간 확보
                  const wEndActual = (wanryoDate !== null && simsaDate === null && wanryoDate <= effEnd)
                    ? wanryoDate - 1
                    : effEnd;
                  wStart = afterStart; wEnd = wEndActual; wLabel = "작성완료";
                  if (wEndActual < todayDay || todayDay <= 0) {
                    calcSC(wEndActual + 1);
                  }
                }
              } else {
                if (wanryoDate !== null && wanryoDate <= afterStart) {
                  // 완료처리가 작성 시작 전/당일 (반려 등) → 완료처리 바만
                  cStart = wanryoDate; cEnd = wanryoDate;
                } else if (wanryoDate !== null) {
                  // 완료처리가 작성 도중 → 작성중 바를 완료처리 전날까지
                  wStart = afterStart; wEnd = wanryoDate - 1; wLabel = "작성중";
                  cStart = wanryoDate; cEnd = wanryoDate;
                } else {
                  wStart = afterStart;
                  wEnd   = todayDay > 0 ? todayDay : null;
                  wLabel = "작성중";
                }
              }
            }

            // 발송대기가 있으면 심사는 완료된 것
            if (simsaDate !== null && sLabel === "심사중") sLabel = "심사완료";

            // 같은 날 겹치는 이벤트 계산 (StatusTooltip 용)
            const KEY_EVENTS: TooltipItem[] = [
              { color: "#4C6EF5", label: "접수" },
              { color: "#F76707", label: "출장" },
              { color: "#2F9E44", label: jaksungDay !== null ? "작성완료" : "작성중" },
              { color: "#7048E8", label: sLabel },
              { color: "#F59F00", label: "발송대기" },
              { color: "#495057", label: "완료처리" },
            ];
            const KEY_DAYS = [
              receiptDay !== null ? [receiptDay] : [],
              culJangDays,
              jaksungDay !== null ? [jaksungDay] : [],
              (jaksungDay !== null && simsaDate !== null && jaksungDay === simsaDate) ? [jaksungDay] : [], // 작성완료=발송대기 동일날이면 툴팁 노출
              simsaDate !== null ? [simsaDate] : [],       // 발송대기 시작일
              wanryoDate !== null ? [wanryoDate] : [],     // 완료처리일
            ];
            // 특정 구간에 해당하는 모든 상태 항목 반환 (primary 포함, 일자 포함)
            const getDayItems = (start: number, end: number, primaryIdx: number): TooltipItem[] => {
              const items: TooltipItem[] = [{
                ...KEY_EVENTS[primaryIdx],
                days: KEY_DAYS[primaryIdx].filter(dd => dd >= start && dd <= end),
              }];
              KEY_EVENTS.forEach((ke, i) => {
                const daysIn = KEY_DAYS[i].filter(dd => dd >= start && dd <= end);
                if (i !== primaryIdx && daysIn.length > 0)
                  items.push({ ...ke, days: daysIn });
              });
              return items;
            };
            const dotEl = (items: TooltipItem[]) =>
              items.length > 1 ? (
                <span style={{ display: "inline-flex", marginLeft: 4, alignItems: "center" }}>
                  <span style={{ width: 5, height: 5, borderRadius: "50%", background: "#fff", opacity: 0.85, flexShrink: 0 }} />
                </span>
              ) : null;
            // 겹치는 이벤트 중 가장 나중 진행상태 반환 (바 색상·라벨에 사용)
            const getDisplayItem = (items: TooltipItem[]): TooltipItem => {
              let best = items[0];
              let bestIdx = KEY_EVENTS.findIndex(ke => ke.color === best.color);
              items.forEach((it) => {
                const idx = KEY_EVENTS.findIndex(ke => ke.color === it.color);
                if (idx > bestIdx) { best = it; bestIdx = idx; }
              });
              return best;
            };

            // 겹치는 이벤트가 있을 때(흰 점)만 hover 핸들러 반환, 없으면 undefined
            const mkHover = (startD: number, endD: number, primaryIdx: number) => {
              const its = getDayItems(startD, endD, primaryIdx);
              if (its.length <= 1) return undefined;
              const dateLabel = startD === endD
                ? `${month}월 ${startD}일`
                : `${month}월 ${startD}일 ~ ${endD}일`;
              return (e: React.MouseEvent) => onCellHover(e.clientX, e.clientY, dateLabel, its);
            };

            // ── 간트 범위 클리핑 (5영업일) ──────────────────────────────────────────
            const clip = (s: number | null, e: number | null): [number | null, number | null] => {
              if (s === null || e === null || ganttStartDay === null || ganttEndDay === null) return [s, e];
              const cs = Math.max(s, ganttStartDay), ce = Math.min(e, ganttEndDay);
              return cs <= ce ? [cs, ce] : [null, null];
            };
            const [blueS, blueE] = clip(blueStart, blueEnd);
            const [preJS, preJE] = clip(preJaksungStart, preJaksungEnd);
            const culJangG = ganttStartDay !== null && ganttEndDay !== null
              ? culJangDays.filter(cd => cd >= ganttStartDay! && cd <= ganttEndDay!)
              : culJangDays;
            const lastCulG = culJangG.length > 0 ? Math.max(...culJangG) : null;
            const [wS, wE] = clip(wStart, wEnd);
            const [sS, sE] = clip(sStart, sEnd);
            const [bS, bE] = clip(bStart, bEnd);
            const [cS, cE] = clip(cStart, cEnd);

            const lastDay = days[days.length - 1];
            const cells: React.ReactNode[] = [];
            let d = visibleStart;
            while (d <= lastDay) {
              const dow       = getDow(d);
              const isToday   = d === todayDay;
              const isWeekend = dow === 0 || dow === 6;
              const bg     = isToday ? TODAY_BG : isWeekend ? WEEKEND_BG : undefined;
              const shadow = isToday ? TODAY_INSET : undefined;

              // 바 클리핑 헬퍼: 바가 visibleStart 이전에 시작하면 visibleStart부터 렌더
              const effS = (s: number) => Math.max(s, visibleStart);

              // 접수(파란) 구간
              if (blueS !== null && blueE !== null && blueE >= d && d === effS(blueS)) {
                const span     = blueE - d + 1;
                const clipped  = blueStart! < d;
                const hasRight = culJangG.length > 0 || wS !== null || sS !== null || bS !== null || cS !== null;
                const items    = getDayItems(blueStart!, blueEnd!, 0);
                const hoverFn  = mkHover(blueStart!, blueEnd!, 0);
                cells.push(
                  <td key={d} colSpan={span}
                    onMouseMove={hoverFn} onMouseLeave={hoverFn ? onCellLeave : undefined}
                    style={{ height: 32, padding: "0 3px", background: bg, boxShadow: shadow, verticalAlign: "middle", cursor: "default" }}>
                    <div style={{ background: "#4C6EF5", borderRadius: clipped ? (hasRight ? "0" : "0 4px 4px 0") : (hasRight ? "4px 0 0 4px" : "4px"), height: 18, display: "flex", alignItems: "center", justifyContent: "center" }}>
                      <span style={{ fontSize: 10, fontWeight: 700, color: "#fff", letterSpacing: "0.03em" }}>접수</span>
                      {dotEl(items)}
                    </div>
                  </td>
                );
                d = blueE + 1;

              // 출장 전 작성완료 구간
              } else if (preJS !== null && preJE !== null && preJE >= d && d === effS(preJS)) {
                const span    = preJE - d + 1;
                const items   = getDayItems(preJaksungStart!, preJaksungEnd!, 2);
                const hoverFn = mkHover(preJaksungStart!, preJaksungEnd!, 2);
                cells.push(
                  <td key={d} colSpan={span}
                    onMouseMove={hoverFn} onMouseLeave={hoverFn ? onCellLeave : undefined}
                    style={{ height: 32, padding: "0 3px", background: bg, boxShadow: shadow, verticalAlign: "middle", cursor: "default" }}>
                    <div style={{ background: "#2F9E44", borderRadius: "0", height: 18, display: "flex", alignItems: "center", justifyContent: "center" }}>
                      <span style={{ fontSize: 10, fontWeight: 700, color: "#fff", letterSpacing: "0.03em" }}>작성완료</span>
                      {dotEl(items)}
                    </div>
                  </td>
                );
                d = preJE + 1;

              // 출장(주황) 셀
              } else if (culJangG.includes(d)) {
                const isLastCul = d === lastCulG;
                const hasAfter  = wS !== null || sS !== null || bS !== null || cS !== null;
                const items     = getDayItems(d, d, 1);
                const display   = getDisplayItem(items);
                const hoverFn   = mkHover(d, d, 1);
                cells.push(
                  <td key={d}
                    onMouseMove={hoverFn} onMouseLeave={hoverFn ? onCellLeave : undefined}
                    style={{ height: 32, padding: "0 3px", background: bg, boxShadow: shadow, verticalAlign: "middle", cursor: "default" }}>
                    <div style={{ background: display.color, borderRadius: isLastCul && !hasAfter ? "0 4px 4px 0" : "0", height: 18, display: "flex", alignItems: "center", justifyContent: "center" }}>
                      <span style={{ fontSize: 10, fontWeight: 700, color: "#fff", letterSpacing: "0.03em" }}>{display.label}</span>
                      {dotEl(items)}
                    </div>
                  </td>
                );
                d++;

              // 작성(중/완료) 구간
              } else if (wS !== null && wE !== null && wE >= d && d === effS(wS)) {
                const span     = wE - d + 1;
                const clipped  = wStart! < d;
                const hasRight = sS !== null || bS !== null || cS !== null;
                const items    = getDayItems(wStart!, wEnd!, 2);
                const hoverFn  = mkHover(wStart!, wEnd!, 2);
                cells.push(
                  <td key={d} colSpan={span}
                    onMouseMove={hoverFn} onMouseLeave={hoverFn ? onCellLeave : undefined}
                    style={{ height: 32, padding: "0 3px", background: bg, boxShadow: shadow, verticalAlign: "middle", cursor: "default" }}>
                    <div style={{ background: "#2F9E44", borderRadius: clipped ? (hasRight ? "0" : "0 4px 4px 0") : (hasRight ? "0" : "0 4px 4px 0"), height: 18, display: "flex", alignItems: "center", justifyContent: "center" }}>
                      <span style={{ fontSize: 10, fontWeight: 700, color: "#fff", letterSpacing: "0.03em" }}>{wLabel}</span>
                      {dotEl(items)}
                    </div>
                  </td>
                );
                d = wE + 1;

              // 심사중/완료 구간
              } else if (sS !== null && sE !== null && sE >= d && d === effS(sS)) {
                const span     = sE - d + 1;
                const clipped  = sStart! < d;
                const hasRight = bS !== null || cS !== null;
                const items    = getDayItems(sStart!, sEnd!, 3);
                const hoverFn  = mkHover(sStart!, sEnd!, 3);
                cells.push(
                  <td key={d} colSpan={span}
                    onMouseMove={hoverFn} onMouseLeave={hoverFn ? onCellLeave : undefined}
                    style={{ height: 32, padding: "0 3px", background: bg, boxShadow: shadow, verticalAlign: "middle", cursor: "default" }}>
                    <div style={{ background: "#7048E8", borderRadius: clipped ? (hasRight ? "0" : "0 4px 4px 0") : (hasRight ? "0" : "0 4px 4px 0"), height: 18, display: "flex", alignItems: "center", justifyContent: "center" }}>
                      <span style={{ fontSize: 10, fontWeight: 700, color: "#fff", letterSpacing: "0.03em" }}>{sLabel}</span>
                      {dotEl(items)}
                    </div>
                  </td>
                );
                d = sE + 1;

              // 발송대기 구간
              } else if (bS !== null && bE !== null && bE >= d && d === effS(bS)) {
                const span     = bE - d + 1;
                const clipped  = bStart! < d;
                const hasRight = cS !== null;
                const items    = getDayItems(bStart!, bEnd!, 4);
                const hoverFn  = mkHover(bStart!, bEnd!, 4);
                cells.push(
                  <td key={d} colSpan={span}
                    onMouseMove={hoverFn} onMouseLeave={hoverFn ? onCellLeave : undefined}
                    style={{ height: 32, padding: "0 3px", background: bg, boxShadow: shadow, verticalAlign: "middle", cursor: "default" }}>
                    <div style={{ background: "#F59F00", borderRadius: clipped ? (hasRight ? "0" : "0 4px 4px 0") : (hasRight ? "0" : "0 4px 4px 0"), height: 18, display: "flex", alignItems: "center", justifyContent: "center" }}>
                      <span style={{ fontSize: 10, fontWeight: 700, color: "#fff", letterSpacing: "0.03em" }}>발송대기</span>
                      {dotEl(items)}
                    </div>
                  </td>
                );
                d = bE + 1;

              // 완료처리 구간
              } else if (cS !== null && cE !== null && cE >= d && d === effS(cS)) {
                const span    = cE - d + 1;
                const items   = getDayItems(cStart!, cEnd!, 5);
                const hoverFn = mkHover(cStart!, cEnd!, 5);
                cells.push(
                  <td key={d} colSpan={span}
                    onMouseMove={hoverFn} onMouseLeave={hoverFn ? onCellLeave : undefined}
                    style={{ height: 32, padding: "0 3px", background: bg, boxShadow: shadow, verticalAlign: "middle", cursor: "default" }}>
                    <div style={{ background: "#495057", borderRadius: "0 4px 4px 0", height: 18, display: "flex", alignItems: "center", justifyContent: "center" }}>
                      <span style={{ fontSize: 10, fontWeight: 700, color: "#fff", letterSpacing: "0.03em" }}>완료처리</span>
                      {dotEl(items)}
                    </div>
                  </td>
                );
                d = cE + 1;

              // 빈 셀
              } else {
                cells.push(
                  <td key={d} style={{ height: 32, padding: 0, background: bg, boxShadow: shadow }} />
                );
                d++;
              }
            }
            return cells;
          })()}
        </tr>
      ))}
    </React.Fragment>
  );
});

// ═══════════════════════════════════════════════════════════════════════════════
// DailyGrid
// ═══════════════════════════════════════════════════════════════════════════════

function DailyGrid({ users, year, month, holidays }: { users: DailyListUser[]; year: number; month: number; holidays: string[] }) {
  const today    = new Date();
  const todayDay = today.getFullYear() === year && today.getMonth() + 1 === month ? today.getDate() : -1;

  const monthState = useMemo((): "past" | "current" | "future" => {
    const yr = today.getFullYear(); const mo = today.getMonth() + 1;
    if (year < yr || (year === yr && month < mo)) return "past";
    if (year === yr && month === mo) return "current";
    return "future";
  }, [year, month]); // eslint-disable-line react-hooks/exhaustive-deps

  // 첫 업무일: 주말 · 공휴일 제외
  const firstBusinessDay = useMemo(() => {
    const holidaySet = new Set(holidays);
    const pad = (n: number) => String(n).padStart(2, "0");
    const daysInM = new Date(year, month, 0).getDate();
    for (let d = 1; d <= daysInM; d++) {
      const dow = new Date(year, month - 1, d).getDay();
      if (dow === 0 || dow === 6) continue;
      if (holidaySet.has(`${year}-${pad(month)}-${pad(d)}`)) continue;
      return d;
    }
    return 1;
  }, [year, month, holidays]);

  const daysInMonth = useMemo(() => new Date(year, month, 0).getDate(), [year, month]);

  const visibleStart = useMemo(() => Math.max(1, (todayDay > 0 ? todayDay : 1) - 7), [todayDay]);
  const visibleEnd   = useMemo(() => Math.min(daysInMonth, (todayDay > 0 ? todayDay : daysInMonth) + 7), [todayDay, daysInMonth]);

  // 간트바 표시 범위: 기준일 포함 5영업일 (날짜 컬럼 범위와 별개)
  const { ganttStartDay, ganttEndDay } = useMemo((): { ganttStartDay: number | null; ganttEndDay: number | null } => {
    const holidaySet = new Set(holidays);
    const pad = (n: number) => String(n).padStart(2, "0");
    const isBusinessDay = (d: number) => {
      const dow = new Date(year, month - 1, d).getDay();
      return dow !== 0 && dow !== 6 && !holidaySet.has(`${year}-${pad(month)}-${pad(d)}`);
    };
    if (monthState === "future") return { ganttStartDay: null, ganttEndDay: null };
    let refDay: number;
    if (monthState === "current") {
      refDay = todayDay;
    } else {
      refDay = daysInMonth;
      while (refDay >= 1 && !isBusinessDay(refDay)) refDay--;
      if (refDay < 1) refDay = daysInMonth;
    }
    let start = refDay;
    let cnt = 0;
    while (cnt < 4 && start > 1) { start--; if (isBusinessDay(start)) cnt++; }
    start = Math.max(start, firstBusinessDay);
    return { ganttStartDay: start, ganttEndDay: refDay };
  }, [year, month, monthState, todayDay, daysInMonth, holidays, firstBusinessDay]);

  const days = useMemo(() => Array.from({ length: visibleEnd - visibleStart + 1 }, (_, i) => i + visibleStart), [visibleStart, visibleEnd]);
  const firstDayOfWeek = useMemo(() => new Date(year, month - 1, 1).getDay(), [year, month]);
  const getDow         = useCallback((d: number) => (firstDayOfWeek + d - 1) % 7, [firstDayOfWeek]);
  const DOW_KR         = ["일", "월", "화", "수", "목", "금", "토"];

  const [tooltip, setTooltip] = useState<TooltipState | null>(null);
  const handleCellHover = useCallback((x: number, y: number, dateLabel: string, items: TooltipItem[]) => {
    setTooltip({ x, y, dateLabel, items });
  }, []);
  const handleCellLeave = useCallback(() => setTooltip(null), []);

  const [collapsed, setCollapsed] = useState<Set<number>>(new Set());
  const toggle = useCallback((apwid: number) => {
    startTransition(() => {
      setCollapsed((prev) => {
        const next = new Set(prev);
        next.has(apwid) ? next.delete(apwid) : next.add(apwid);
        return next;
      });
    });
  }, []);

  const grouped = useMemo(
    () => DEPT_ORDER.map((dept) => ({ dept, ...DEPT_META[dept], users: users.filter((u) => u.dept === dept) })),
    [users],
  );

  if (monthState === "future") {
    return <div className="flex-1 flex items-center justify-center text-txt-secondary text-sm">미래 월은 조회 대상이 아닙니다.</div>;
  }

  if (users.length === 0) {
    return <div className="flex-1 flex items-center justify-center text-txt-secondary text-sm">조회된 데이터가 없습니다.</div>;
  }

  const minTableWidth = NAME_W + 170 + days.length * CELL_W;

  return (
    <>
    {tooltip && <StatusTooltip {...tooltip} />}
    <div className="overflow-auto flex-1 rounded-xl" style={{ boxShadow: "0 1px 4px rgba(0,0,0,0.06), 0 0 0 1px rgba(0,0,0,0.06)" }}>
      <table className="border-collapse" style={{ tableLayout: "fixed", width: "100%", minWidth: `${minTableWidth}px`, fontSize: 13 }}>
        <colgroup>
          <col style={{ width: NAME_W }} />
          <col style={{ width: DOC_W }} />
          <col style={{ width: ADDR_W }} />
          <col style={{ width: META_W }} />
          {days.map((d) => <col key={d} style={{ width: CELL_W }} />)}
        </colgroup>

        <thead>
          <tr className="bg-bg-primary sticky top-0 z-20">
            <th className="sticky left-0 bg-bg-primary text-center" style={{ minWidth: NAME_W, padding: "6px 8px", borderBottom: BORDER, fontSize: 10, fontWeight: 600, color: "var(--txt-secondary,#6b7280)", zIndex: 40, ...NAME_SX }}>
              이름
            </th>
            <th className="sticky bg-bg-primary text-center" style={{ left: DOC_LEFT, minWidth: DOC_W, padding: "6px 8px", borderBottom: BORDER, fontSize: 10, fontWeight: 600, color: "var(--txt-secondary,#6b7280)", zIndex: 40, ...DOC_SX }}>
              감정서
            </th>
            <th className="sticky bg-bg-primary text-center" style={{ left: ADDR_LEFT, minWidth: ADDR_W, padding: "6px 8px", borderBottom: BORDER, fontSize: 10, fontWeight: 600, color: "var(--txt-secondary,#6b7280)", zIndex: 40, ...ADDR_SX }}>
              주소
            </th>
            <th className="sticky bg-bg-primary" style={{ left: META_LEFT, minWidth: META_W, padding: 0, borderBottom: BORDER, fontSize: 10, fontWeight: 600, color: "var(--txt-secondary,#6b7280)", zIndex: 40, ...META_SX }}>
              <div style={{ display: "flex", flexDirection: "column", height: "100%" }}>
                <div className="flex items-center justify-center" style={{ flex: 1, borderBottom: "1px solid var(--border-color,#e5e7eb)" }}>업무구분</div>
                <div className="flex items-center justify-center" style={{ flex: 1 }}>물건종류</div>
              </div>
            </th>
            {days.map((d) => {
              const dow = getDow(d);
              const isSat = dow === 6;
              const isSun = dow === 0;
              const isToday = d === todayDay;
              return (
                <th key={d} style={{ width: CELL_W, minWidth: CELL_W, padding: 0, borderBottom: BORDER, background: isToday ? "linear-gradient(180deg,#EEF2FF 0%,#F8F9FF 100%)" : (isSat || isSun) ? WEEKEND_BG : undefined, borderTop: isToday ? "2px solid #5C7CFA" : "2px solid transparent", boxShadow: isToday ? "inset 2px 0 0 rgba(92,124,250,0.45), inset -2px 0 0 rgba(92,124,250,0.45)" : undefined }}>
                  <div className="flex flex-col items-center justify-center py-1.5" style={{ gap: 2 }}>
                    <span style={{ fontSize: 11, fontWeight: 700, lineHeight: 1, color: isToday ? "#5C7CFA" : isSun ? "#FA5252" : isSat ? "#339AF0" : "var(--txt-secondary,#6b7280)" }}>{d}</span>
                    <span style={{ fontSize: 9, fontWeight: 500, lineHeight: 1, opacity: isToday ? 1 : 0.7, color: isToday ? "#5C7CFA" : isSun ? "#FA5252" : isSat ? "#339AF0" : "var(--txt-secondary,#9ca3af)" }}>{DOW_KR[dow]}</span>
                  </div>
                </th>
              );
            })}
          </tr>
        </thead>

        <tbody>
          {grouped.map(({ dept, label, accent, users: du }) => (
            <React.Fragment key={dept}>
              <tr>
                <td colSpan={days.length + 2} style={{ padding: "5px 12px", fontSize: 11, fontWeight: 700, letterSpacing: "0.04em", color: "var(--txt-secondary,#6b7280)", background: "var(--bg-secondary,#f9fafb)", borderTop: BORDER, borderBottom: BORDER, borderLeft: `3px solid ${accent}` }}>
                  {label}
                </td>
              </tr>
              {du.map((user) => (
                <UserSection key={user.apwid} user={user} isCollapsed={collapsed.has(user.apwid)} onToggle={toggle} days={days} visibleStart={visibleStart} getDow={getDow} todayDay={todayDay} year={year} month={month} monthState={monthState} firstBusinessDay={firstBusinessDay} ganttStartDay={ganttStartDay} ganttEndDay={ganttEndDay} onCellHover={handleCellHover} onCellLeave={handleCellLeave} />
              ))}
            </React.Fragment>
          ))}
        </tbody>
      </table>
    </div>
    </>
  );
}

// ═══════════════════════════════════════════════════════════════════════════════
// Legend / Page
// ═══════════════════════════════════════════════════════════════════════════════

function DailyListContent() {
  const searchParams = useSearchParams();
  const empno  = parseInt(searchParams.get("empno") ?? "0", 10);
  const [users,    setUsers]    = useState<DailyListUser[]>([]);
  const [holidays, setHolidays] = useState<string[]>([]);
  const [loading,  setLoading]  = useState(true);
  const [error,    setError]    = useState<string | null>(null);
  const initialized = useRef(false);
  const today = new Date();
  const [viewYear,  setViewYear]  = useState(today.getFullYear());
  const [viewMonth, setViewMonth] = useState(today.getMonth() + 1);
  const [filterMode, setFilterMode] = useState<"전체" | "진행중">("진행중");

  const moveMonth = useCallback((delta: number) => {
    startTransition(() => {
      setViewMonth((m) => {
        const next = m + delta;
        if (next < 1)  { setViewYear((y) => y - 1); return 12; }
        if (next > 12) { setViewYear((y) => y + 1); return 1;  }
        return next;
      });
    });
  }, []);

  const filteredUsers = useMemo(() => {
    if (filterMode === "전체") return users;
    return users.map((u) => ({
      ...u,
      docs: u.docs.filter((d) => !d.lStatus.includes("완료처리")),
    })).filter((u) => u.docs.length > 0);
  }, [users, filterMode]);

  const allowed = ALLOWED_EMPNOS.includes(empno);
  useEffect(() => {
    if (!allowed) return;
    setLoading(true);
    setError(null);
    const pad = (n: number) => String(n).padStart(2, "0");
    const lastDay = new Date(viewYear, viewMonth, 0).getDate();
    Promise.all([
      getDailyList(viewYear, viewMonth),
      getHolidays(`${viewYear}-${pad(viewMonth)}-01`, `${viewYear}-${pad(viewMonth)}-${pad(lastDay)}`),
    ])
      .then(([data, hols]) => {
        setUsers(data);
        setHolidays(hols.map((h) => h.date));
        initialized.current = true;
      })
      .catch(() => setError("데이터를 불러오지 못했습니다."))
      .finally(() => setLoading(false));
  }, [allowed, viewYear, viewMonth]);

  if (!allowed) {
    return (
      <div className="flex flex-col items-center justify-center h-screen gap-4 bg-bg-primary">
        <p className="text-txt-secondary text-sm">접근 권한이 없습니다.</p>
        <Link href={`/?empno=${empno}`} className="px-4 py-2 rounded-lg bg-accent text-accent-contrast text-sm font-medium hover:brightness-110 transition">
          캘린더로 돌아가기
        </Link>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-screen bg-bg-primary" style={{ fontFamily: "'Inter','Pretendard',system-ui,sans-serif" }}>
      <header className="sticky top-0 z-40 bg-bg-primary px-4 py-2.5 flex items-center gap-3 flex-wrap" style={{ borderBottom: "1px solid var(--border-color,#e5e7eb)" }}>
        <Link href={`/?empno=${empno}`} className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-bg-secondary hover:bg-bg-secondary/70 text-txt-primary text-sm font-medium transition-colors">
          <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M15 19l-7-7 7-7" />
          </svg>
          캘린더
        </Link>

        <div className="flex items-center gap-1.5">
          <button onClick={() => moveMonth(-1)} className="p-1.5 rounded-lg hover:bg-bg-secondary transition-colors">
            <svg className="w-4 h-4 text-txt-primary" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M15 19l-7-7 7-7" />
            </svg>
          </button>
          <span className="text-sm font-bold text-txt-primary min-w-[84px] text-center">{viewYear}년 {viewMonth}월</span>
          <button onClick={() => moveMonth(1)} className="p-1.5 rounded-lg hover:bg-bg-secondary transition-colors">
            <svg className="w-4 h-4 text-txt-primary" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />
            </svg>
          </button>
          <button onClick={() => { setViewYear(today.getFullYear()); setViewMonth(today.getMonth() + 1); }} className="px-2.5 py-1 text-xs font-semibold rounded-full hover:brightness-110 transition-colors" style={{ background: "#5C7CFA", color: "#fff" }}>
            이번 달
          </button>
        </div>

        <div className="flex items-center gap-2">
          {(["전체", "진행중"] as const).map((mode) => (
            <label key={mode} className="flex items-center gap-1.5 cursor-pointer select-none">
              <input
                type="checkbox"
                checked={filterMode === mode}
                onChange={() => setFilterMode(mode)}
                style={{ accentColor: "#5C7CFA", width: 14, height: 14, cursor: "pointer" }}
              />
              <span style={{ fontSize: 12, fontWeight: 600, color: filterMode === mode ? "#5C7CFA" : "var(--txt-secondary,#6b7280)" }}>
                {mode}
              </span>
            </label>
          ))}
        </div>

        <Link
          href={`/assignment?empno=${empno}&year=${viewYear}&month=${viewMonth}`}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-medium transition-colors"
          style={{ background: "#2f9e44", color: "#fff" }}
        >
          <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M3 10h18M3 6h18M3 14h12M3 18h8" />
          </svg>
          배정현황
        </Link>

        <div className="ml-auto">
          {!loading && !error && (
            <span style={{ fontSize: 11 }} className="text-txt-secondary">
              {filteredUsers.length}명 · {filteredUsers.reduce((s, u) => s + u.docs.length, 0)}건
            </span>
          )}
        </div>
      </header>

      <main className="relative flex-1 overflow-hidden p-4 flex flex-col">
        {!error && <DailyGrid users={filteredUsers} year={viewYear} month={viewMonth} holidays={holidays} />}
        {error && <div className="flex items-center justify-center flex-1 text-red-500 text-sm">{error}</div>}

        {loading && (
          <div className="absolute inset-0 flex items-center justify-center z-50" style={{ background: initialized.current ? "rgba(var(--bg-primary-rgb,255,255,255),0.65)" : "var(--bg-primary,#fff)", backdropFilter: initialized.current ? "blur(1px)" : undefined }}>
            <div className="flex flex-col items-center gap-3">
              <svg className="animate-spin" style={{ width: 28, height: 28, color: "#5C7CFA" }} fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v4l3-3-3-3v4a8 8 0 00-8 8h4l-3 3 3 3H4a8 8 0 01-8-8z" />
              </svg>
              <span style={{ fontSize: 12, color: "var(--txt-secondary,#6b7280)" }}>불러오는 중...</span>
            </div>
          </div>
        )}
      </main>
    </div>
  );
}

export default function DailyListPage() {
  return (
    <Suspense fallback={<div className="flex items-center justify-center h-screen bg-bg-primary text-txt-secondary text-sm">Loading...</div>}>
      <DailyListContent />
    </Suspense>
  );
}
