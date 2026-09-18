import { useQuery } from "@tanstack/react-query";
import apiClient from "./client";

export interface LeaveRow {
  emp_no: string | null;
  name: string;
  dept_name: string | null;
  matched: boolean;
  leave_date: string;
  weekday: string;
  leave_type: string;
  half: boolean;
  remark: string | null;
}

export interface LeaveSummary {
  annual: number;
  half: number;
  gong: number;
  special: number;
  bereavement: number;
  family_care: number;
  etc: number;
}

export interface LeaveListResponse {
  year: number;
  month: number;
  total: number;
  summary: LeaveSummary;
  rows: LeaveRow[];
}

export function useLeaves(
  year: number,
  month: number,
  leaveType?: string,
  keyword?: string
) {
  return useQuery({
    queryKey: ["leaves", year, month, leaveType ?? "", keyword ?? ""],
    queryFn: async () => {
      const { data } = await apiClient.get<LeaveListResponse>("/leaves", {
        params: {
          year,
          month,
          leave_type: leaveType || undefined,
          keyword: keyword || undefined,
        },
      });
      return data;
    },
  });
}
