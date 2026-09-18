import { useQuery } from "@tanstack/react-query";
import apiClient from "./client";

export interface AttendanceDailyRow {
  emp_no: string;
  name: string;
  dept_name: string | null;
  matched: boolean;
  check_in: string | null;
  check_out: string | null;
  work_minutes: number | null;
  tag_count: number;
}

export interface AttendanceDailyResponse {
  work_date: string;
  total: number;
  matched_count: number;
  rows: AttendanceDailyRow[];
}

export function useDailyAttendance(date: string | null) {
  return useQuery({
    queryKey: ["attendance", "daily", date],
    queryFn: async () => {
      const { data } = await apiClient.get<AttendanceDailyResponse>(
        "/attendance/daily",
        { params: { date } }
      );
      return data;
    },
    enabled: !!date,
  });
}

export interface AttendanceSummaryRow {
  emp_no: string;
  name: string;
  dept_name: string | null;
  matched: boolean;
  work_days: number;
  work_hours: number;
  leave_days: number;
  gong_days: number;
  trip_days: number;
}

export interface AttendanceSummaryResponse {
  year: number;
  month: number;
  total: number;
  matched_count: number;
  rows: AttendanceSummaryRow[];
}

export function useMonthlySummary(year: number, month: number) {
  return useQuery({
    queryKey: ["attendance", "summary", year, month],
    queryFn: async () => {
      const { data } = await apiClient.get<AttendanceSummaryResponse>(
        "/attendance/summary",
        { params: { year, month } }
      );
      return data;
    },
  });
}

export interface AttendanceDetailDay {
  work_date: string;
  weekday: string;
  is_weekend: boolean;
  check_in: string | null;
  check_out: string | null;
  work_minutes: number | null;
  tag_count: number;
  leave_type: string | null;
  leave_half: boolean;
  leave_remark: string | null;
  trip: boolean;
  trip_places: string[];
}

export interface AttendanceDetailResponse {
  emp_no: string;
  name: string;
  dept_name: string | null;
  year: number;
  month: number;
  work_days: number;
  work_hours: number;
  leave_days: number;
  gong_days: number;
  trip_days: number;
  days: AttendanceDetailDay[];
}

export function usePersonalDetail(
  emp_no: string | null,
  year: number,
  month: number
) {
  return useQuery({
    queryKey: ["attendance", "detail", emp_no, year, month],
    queryFn: async () => {
      const { data } = await apiClient.get<AttendanceDetailResponse>(
        "/attendance/detail",
        { params: { emp_no, year, month } }
      );
      return data;
    },
    enabled: !!emp_no,
  });
}

async function downloadXlsx(url: string, params: Record<string, number>, filename: string) {
  const response = await apiClient.get(url, {
    params,
    responseType: "blob",
  });
  const blob = new Blob([response.data], {
    type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  });
  const objectUrl = window.URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = objectUrl;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  window.URL.revokeObjectURL(objectUrl);
}

export async function exportAttendanceSummary(year: number, month: number) {
  await downloadXlsx(
    "/attendance/export/summary",
    { year, month },
    `출퇴근현황_${year}${String(month).padStart(2, "0")}.xlsx`
  );
}

export async function exportAttendanceHistory(year: number, month: number) {
  await downloadXlsx(
    "/attendance/export/history",
    { year, month },
    `출퇴근이력_${year}${String(month).padStart(2, "0")}.xlsx`
  );
}
