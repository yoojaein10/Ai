import type { EventType } from "../api/calendar";

// PHASE 13 color rules (spec lines 250-380):
// 연차=파랑, 반차=하늘, 공가=연두, 병가=주황, 경조=보라,
// 외근=노랑, 출장=빨강, 회의=회색
//
// We only store event_type (LEAVE/TRAVEL/MEETING/MANUAL/OTHER) on events;
// fine-grained subtypes (반차, 경조 etc.) come from the linked approval doc's
// metadata. For the base rendering we map the type, and callers may override
// per-event via the calendar's color_hex (which wins when set).
const TYPE_TO_COLOR: Record<EventType, string> = {
  LEAVE: "#1677ff",
  TRAVEL: "#ff4d4f",
  MEETING: "#8c8c8c",
  MANUAL: "#1677ff",
  OTHER: "#bfbfbf",
};

export function colorForEventType(t: EventType): string {
  return TYPE_TO_COLOR[t] ?? "#1677ff";
}

// Fine-grained subtype mapping for approval-linked events that carry a
// subtype hint in their description or title prefix. Exposed for future
// wiring in PHASE 15/16.
const SUBTYPE_TO_COLOR: Record<string, string> = {
  annual: "#1677ff", // 연차 파랑
  half: "#91caff", // 반차 하늘
  public: "#52c41a", // 공가 연두
  sick: "#fa8c16", // 병가 주황
  condolence: "#722ed1", // 경조 보라
  field: "#fadb14", // 외근 노랑
  travel: "#ff4d4f", // 출장 빨강
  meeting: "#8c8c8c", // 회의 회색
};

export function colorForSubtype(subtype: string | null | undefined): string | null {
  if (!subtype) return null;
  return SUBTYPE_TO_COLOR[subtype] ?? null;
}

export function resolveEventColor(
  eventType: EventType,
  calendarColor?: string | null,
  subtype?: string | null,
): string {
  return (
    colorForSubtype(subtype) ??
    calendarColor ??
    colorForEventType(eventType)
  );
}
