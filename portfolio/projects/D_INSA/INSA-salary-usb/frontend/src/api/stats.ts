import { useQuery } from "@tanstack/react-query";
import apiClient from "./client";

// ── Workforce ─────────────────────────────────────────────

export interface WorkforceDeptRow {
  dept_id: number | null;
  dept_name: string;
  count: number;
  male: number;
  female: number;
}

export interface WorkforceRankRow {
  rank: string;
  count: number;
}

export interface WorkforceAgeGroupRow {
  group: string;
  count: number;
}

export interface WorkforceTenureRow {
  group: string;
  count: number;
}

export interface WorkforceTrendRow {
  year: number;
  month: number;
  hired: number;
  resigned: number;
}

export interface WorkforceStatResponse {
  total: number;
  male: number;
  female: number;
  unknown_gender: number;
  by_dept: WorkforceDeptRow[];
  by_rank: WorkforceRankRow[];
  by_age_group: WorkforceAgeGroupRow[];
  by_tenure: WorkforceTenureRow[];
  trend_12m: WorkforceTrendRow[];
}

export function useWorkforceStat() {
  return useQuery({
    queryKey: ["stat-workforce"],
    queryFn: async () => {
      const { data } = await apiClient.get<WorkforceStatResponse>(
        "/stats/workforce"
      );
      return data;
    },
  });
}

// ── Attendance ────────────────────────────────────────────

export interface AttendanceStatMonthRow {
  month: number;
  total_work_days: number;
  avg_work_hours: number;
  total_leave_days: number;
  emp_count: number;
}

export interface AttendanceStatDeptRow {
  dept_name: string;
  emp_count: number;
  total_leave_days: number;
  avg_leave_per_emp: number;
}

export interface AttendanceStatTopRow {
  emp_no: string | null;
  name: string;
  dept_name: string | null;
  value: number;
}

export interface AttendanceStatResponse {
  year: number;
  by_month: AttendanceStatMonthRow[];
  by_dept: AttendanceStatDeptRow[];
  top_work_hours: AttendanceStatTopRow[];
  top_leave_users: AttendanceStatTopRow[];
}

export function useAttendanceStat(year: number) {
  return useQuery({
    queryKey: ["stat-attendance", year],
    queryFn: async () => {
      const { data } = await apiClient.get<AttendanceStatResponse>(
        "/stats/attendance",
        { params: { year } }
      );
      return data;
    },
  });
}

// ── Education ─────────────────────────────────────────────

export interface EducationStatCategoryRow {
  category: string;
  count: number;
  total_hours: number;
  completed: number;
}

export interface EducationStatDeptRow {
  dept_name: string;
  emp_count: number;
  record_count: number;
  total_hours: number;
  avg_hours_per_emp: number;
}

export interface EducationStatMonthRow {
  month: number;
  count: number;
}

export interface EducationStatIncompleteRow {
  emp_no: string;
  name: string;
  dept_name: string | null;
  total_hours: number;
}

export interface EducationStatResponse {
  year: number;
  total_records: number;
  total_hours: number;
  completed: number;
  completion_rate: number;
  by_category: EducationStatCategoryRow[];
  by_dept: EducationStatDeptRow[];
  by_month: EducationStatMonthRow[];
  incomplete_employees: EducationStatIncompleteRow[];
}

export function useEducationStat(year: number) {
  return useQuery({
    queryKey: ["stat-education", year],
    queryFn: async () => {
      const { data } = await apiClient.get<EducationStatResponse>(
        "/stats/education",
        { params: { year } }
      );
      return data;
    },
  });
}
