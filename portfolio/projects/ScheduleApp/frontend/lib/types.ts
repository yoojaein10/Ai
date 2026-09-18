// ============================================================
// TypeScript Type Definitions (visibility-based, no JWT/groups)
// ============================================================

// 사용자 (Seat_UserInfo 기반)
export interface User {
  apwid: number;
  name: string;
  dept_code: string;
  dept_name?: string;
  team_name: string;
  phone_ext?: string;
  phone?: string;
  grade?: string;
}

// 이벤트
export interface CalendarEvent {
  event_id: number;
  creator_id: number;
  title: string;
  description?: string;
  location?: string;
  event_color: string;
  event_icon?: string;
  start_dt: string;
  end_dt: string;
  is_all_day: boolean;
  visibility: "company" | "dept" | "personal";
  dept_code?: string;
  repeat_rule?: string;
  repeat_end_dt?: string;
  is_daou_noti_enabled?: boolean;
  version: number;
  creator_name?: string;
  attendees?: EventAttendee[];
  is_deleted?: boolean;
  created_at?: string;
  updated_at?: string;
  source?: "iw_schedule";
  _forceColor?: string;
  _forceTextColor?: string;
}

// 참석자
export interface EventAttendee {
  apwid: number;
  name: string;
  status: "pending" | "accepted" | "declined" | "tentative";
  responded_at?: string;
}

// 부서
export interface Department {
  dept_code: string;
  dept_name: string;
  member_count: number;
  sort_order: number;
}

// API 응답
export interface ApiResponse<T = unknown> {
  status: string;
  data: T;
  message: string;
}

// 이벤트 생성
export interface EventCreateRequest {
  title: string;
  description?: string;
  location?: string;
  event_color?: string;
  event_icon?: string;
  start_dt: string;
  end_dt: string;
  is_all_day?: boolean;
  visibility: string;
  dept_code?: string;
  attendee_ids?: number[];
  is_daou_noti_enabled?: boolean;
}

// 이벤트 수정
export interface EventUpdateRequest {
  title?: string;
  description?: string;
  location?: string;
  event_color?: string;
  event_icon?: string;
  start_dt?: string;
  end_dt?: string;
  is_all_day?: boolean;
  visibility?: string;
  dept_code?: string;
  attendee_ids?: number[];
  is_daou_noti_enabled?: boolean;
  version: number;
}

// Color palette constants
export const CAL_COLORS = [
  { name: "Red", value: "#FF6B6B" },
  { name: "Orange", value: "#FFA94D" },
  { name: "Yellow", value: "#FFD43B" },
  { name: "Green", value: "#51CF66" },
  { name: "Blue", value: "#339AF0" },
  { name: "Purple", value: "#9775FA" },
  { name: "Pink", value: "#F06595" },
  { name: "Gray", value: "#868E96" },
] as const;

// Common emoji set for events
export const EVENT_EMOJIS = [
  "", "meeting", "birthday", "travel", "meal", "exercise",
  "study", "medical", "shopping", "movie", "music", "game",
] as const;

// Emoji display map
export const EMOJI_MAP: Record<string, string> = {
  "": "",
  meeting: "\uD83D\uDCBC",
  birthday: "\uD83C\uDF82",
  travel: "\u2708\uFE0F",
  meal: "\uD83C\uDF74",
  exercise: "\uD83C\uDFCB\uFE0F",
  study: "\uD83D\uDCDA",
  medical: "\uD83C\uDFE5",
  shopping: "\uD83D\uDED2",
  movie: "\uD83C\uDFAC",
  music: "\uD83C\uDFB5",
  game: "\uD83C\uDFAE",
};

// Visibility options
export const VISIBILITY_OPTIONS = [
  { value: "company", label: "\uC804\uC0AC \uC77C\uC815", color: "#FF6B6B" },
  { value: "dept", label: "\uBD80\uC11C \uC77C\uC815", color: "#51CF66" },
  { value: "personal", label: "\uB0B4 \uC77C\uC815", color: "#339AF0" },
] as const;

// 타임라인
export type EventType = "출장" | "휴가" | "일반";

export interface TimelineEvent {
  event_id: number;
  title: string;
  event_type: EventType;
  event_color: string;
  event_icon?: string;
  start_dt: string;
  end_dt: string;
  is_all_day: boolean;
}

export interface TimelineUser {
  apwid: number;
  name: string;
  dept_code: string;
  events: TimelineEvent[];
}

export interface TimelineDept {
  dept_code: string;
  dept_name: string;
  sort_order: number;
  users: TimelineUser[];
}

// 부서별 사용자 목록 (트리뷰용)
export interface DeptWithUsers {
  dept_code: string;
  dept_name: string;
  sort_order: number;
  users: { apwid: number; name: string }[];
}
