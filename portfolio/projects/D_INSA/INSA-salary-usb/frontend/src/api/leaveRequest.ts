import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import apiClient from "./client";

export type HalfType = "AM" | "PM";

export interface CalculateDaysBody {
  leave_type_id: number;
  start_date: string;
  end_date: string;
  half_type?: HalfType | null;
}

export interface CalculateDaysResponse {
  days: string;
  business_days: number;
  excluded_holidays: string[];
  unit: "DAY" | "HALF_DAY" | "HOUR";
}

export interface LeaveRequestCreateBody {
  leave_type_id: number;
  line_template_id: number;
  title?: string | null;
  start_date: string;
  end_date: string;
  half_type?: HalfType | null;
  reason?: string | null;
  delegate_emp_id?: number | null;
  contact_during_leave?: string | null;
  evidence_file_url?: string | null;
}

export interface LeaveRequestRow {
  doc_id: number;
  doc_no: string | null;
  title: string;
  status: string;
  drafter_id: number;
  drafter_name: string | null;
  drafter_emp_no: string | null;
  dept_name: string | null;
  leave_type_id: number;
  leave_type_name: string | null;
  start_date: string;
  end_date: string;
  half_type: string | null;
  days: string;
  reason: string | null;
  drafted_at: string | null;
  completed_at: string | null;
}

// ── Mutations ──────────────────────────────────────────────

export function useCalculateDays() {
  return useMutation({
    mutationFn: async (body: CalculateDaysBody) => {
      const { data } = await apiClient.post<CalculateDaysResponse>(
        "/leave-request/calculate-days",
        body,
      );
      return data;
    },
  });
}

function invalidateLeaveRequests(qc: ReturnType<typeof useQueryClient>) {
  qc.invalidateQueries({ queryKey: ["leave-request"] });
  qc.invalidateQueries({ queryKey: ["leave", "balance"] });
  qc.invalidateQueries({ queryKey: ["approval"] });
}

export function useCreateLeaveDraft() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (body: LeaveRequestCreateBody) => {
      const { data } = await apiClient.post<{
        doc_id: number;
        detail_id: number;
        status: string;
      }>("/leave-request", body);
      return data;
    },
    onSuccess: () => invalidateLeaveRequests(qc),
  });
}

export function useSubmitLeave() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (docId: number) => {
      const { data } = await apiClient.post<{ doc_id: number; status: string }>(
        `/leave-request/${docId}/submit`,
      );
      return data;
    },
    onSuccess: () => invalidateLeaveRequests(qc),
  });
}

export function useCancelLeave() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (docId: number) => {
      const { data } = await apiClient.post<{ doc_id: number; status: string }>(
        `/leave-request/${docId}/cancel`,
      );
      return data;
    },
    onSuccess: () => invalidateLeaveRequests(qc),
  });
}

// ── Queries ────────────────────────────────────────────────

export function useMyLeaveRequests(params?: { year?: number; status?: string }) {
  return useQuery({
    queryKey: ["leave-request", "my", params?.year ?? "all", params?.status ?? "all"],
    queryFn: async () => {
      const { data } = await apiClient.get<LeaveRequestRow[]>(
        "/leave-request/my",
        {
          params: {
            ...(params?.year ? { year: params.year } : {}),
            ...(params?.status ? { status: params.status } : {}),
          },
        },
      );
      return data;
    },
  });
}

export function useTeamLeaveRequests(params?: { year?: number; status?: string }) {
  return useQuery({
    queryKey: ["leave-request", "team", params?.year ?? "all", params?.status ?? "all"],
    queryFn: async () => {
      const { data } = await apiClient.get<LeaveRequestRow[]>(
        "/leave-request/team",
        {
          params: {
            ...(params?.year ? { year: params.year } : {}),
            ...(params?.status ? { status: params.status } : {}),
          },
        },
      );
      return data;
    },
  });
}
