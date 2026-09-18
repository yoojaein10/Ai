// ============================================================
// Axios Instance (no JWT, empno query parameter based)
// ============================================================

import axios from "axios";

const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api/v1";

const api = axios.create({
  baseURL: API_BASE_URL,
  timeout: 15000,
  headers: {
    "Content-Type": "application/json",
    "Cache-Control": "no-cache, no-store",
    "Pragma": "no-cache",
  },
});

export default api;

// 리소스 타임라인
export async function getTimeline(date: string) {
  const res = await api.get(`/events/timeline?date=${date}`);
  return res.data.data;
}

// 공휴일 조회
export async function getHolidays(
  startDate: string,
  endDate: string
): Promise<{ date: string; name: string }[]> {
  const res = await api.get(`/holidays?start_date=${startDate}&end_date=${endDate}`);
  return res.data.data;
}

// 일간 리스트 (평가사별 감정서 진행 현황)
export interface DailyListEvent {
  date: string;    // "YYYY-MM-DD"
  status: string;
}

export interface DailyListDoc {
  docNo:       string;
  address:     string;
  lStatus:     string;
  receiptDate: string;  // "YYYY-MM-DD"
  workType:    string;
  category:    string;
  events:      DailyListEvent[];
}

export interface DailyListUser {
  apwid: number;
  name: string;
  dept: string;   // "pg1" | "pg2" | "su"
  docs: DailyListDoc[];
}

export async function getDailyList(year: number, month: number): Promise<DailyListUser[]> {
  const res = await api.get(`/reports/daily-list?year=${year}&month=${month}`);
  return res.data.data ?? [];
}

// 배정현황 직원 목록
export interface AssignmentEmployee {
  apwid: number;
  name: string;
  rank: string;
  team: "pg1" | "pg2" | "su";
  seq: number;
  hireDate: string | null;
}

export async function getAssignmentEmployees(): Promise<AssignmentEmployee[]> {
  const res = await api.get("/reports/assignment-employees");
  return res.data.data ?? [];
}

// 배정현황 데이터
export interface AssignmentDataItem {
  apwid: number;
  day: number;
  docId: string;
  address: string;
  category: string;
  status: string;
  type: "assign" | "hold" | "npl" | "taksan" | "gongga" | "vacation" | "schedule";
}

export async function getAssignmentData(year: number, month: number): Promise<AssignmentDataItem[]> {
  const res = await api.get(`/reports/assignment-data?year=${year}&month=${month}`);
  return res.data.data ?? [];
}

// 배정현황 일정 저장 (APW_IW_SCHEDULE UPSERT)
export interface AssignmentScheduleRequest {
  apwid: number;
  gubun: string;
  date?: string;        // 단일 날짜 (하위 호환)
  start_date?: string;  // 기간 시작
  end_date?: string;    // 기간 종료
}

export interface AssignmentScheduleResult {
  apwid: number;
  name: string;
  start_date: string;
  end_date: string;
  gubun: string;
  saved_count: number;
}

export async function saveAssignmentSchedule(
  req: AssignmentScheduleRequest
): Promise<AssignmentScheduleResult> {
  const res = await api.post("/reports/assignment-schedule", req);
  return res.data.data;
}

// 배정현황 일정 삭제 (APW_IW_SCHEDULE 단일 행)
export interface AssignmentScheduleDeleteRequest {
  apwid: number;
  date: string;
}

export interface AssignmentScheduleDeleteResult {
  apwid: number;
  name: string;
  date: string;
  deleted_count: number;
}

export async function deleteAssignmentSchedule(
  req: AssignmentScheduleDeleteRequest
): Promise<AssignmentScheduleDeleteResult> {
  const res = await api.delete("/reports/assignment-schedule", { data: req });
  return res.data.data;
}

// 팀 전체 이벤트 조회 (pg1/pg2 전용)
export interface TeamEvent {
  event_id: number;
  creator_id: number;
  title: string;
  description?: string | null;
  location?: string | null;
  event_color: string;
  event_icon?: string | null;
  start_dt: string;
  end_dt: string;
  is_all_day: boolean;
  visibility: "company" | "dept" | "personal";
  dept_code?: string | null;
  repeat_rule?: string | null;
  repeat_end_dt?: string | null;
  is_daou_noti_enabled?: boolean;
  version: number;
  creator_name?: string | null;
  owner_name: string | null;
  owner_empno: number | null;
  is_mine: boolean;
}

export async function getTeamEvents(
  empno: number,
  start: string,
  end: string
): Promise<TeamEvent[]> {
  const res = await api.get(`/events/team?empno=${empno}&start=${start}&end=${end}`);
  return res.data.data ?? [];
}

// 카카오 ICS 동기화 (인증 불필요, ICS URL로 직접 가져오기)
export async function syncKakaoICS(
  empno: number
): Promise<{ created: number; updated: number; deleted: number; total: number }> {
  const res = await api.post(`/google/sync-ics?empno=${empno}`);
  return res.data.data;
}

