import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import apiClient from "./client";

export interface ChangeRequest {
  id: number;
  employee_id: number;
  emp_name: string | null;
  emp_no: string | null;
  field_name: string;
  field_label: string | null;
  old_value: string | null;
  new_value: string | null;
  reason: string | null;
  status: "PENDING" | "APPROVED" | "REJECTED";
  requested_by: number;
  requested_at: string;
  reviewed_by: number | null;
  reviewed_at: string | null;
  review_comment: string | null;
}

export interface ChangeRequestCreate {
  field_name: string;
  new_value: string | null;
  reason?: string | null;
}

export function useMyChangeRequests() {
  return useQuery({
    queryKey: ["change-requests", "mine"],
    queryFn: async () => {
      const { data } = await apiClient.get<ChangeRequest[]>("/change-requests/mine");
      return data;
    },
  });
}

export function useAllChangeRequests(statusFilter?: string) {
  return useQuery({
    queryKey: ["change-requests", "all", statusFilter],
    queryFn: async () => {
      const { data } = await apiClient.get<ChangeRequest[]>("/change-requests", {
        params: statusFilter ? { status_filter: statusFilter } : {},
      });
      return data;
    },
  });
}

export function useCreateChangeRequest() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (body: ChangeRequestCreate) => {
      const { data } = await apiClient.post<ChangeRequest>("/change-requests", body);
      return data;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["change-requests"] });
    },
  });
}

export function useApproveChangeRequest() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ id, comment }: { id: number; comment?: string }) => {
      const { data } = await apiClient.post<ChangeRequest>(
        `/change-requests/${id}/approve`,
        { comment: comment ?? null }
      );
      return data;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["change-requests"] });
      qc.invalidateQueries({ queryKey: ["emp-tab"] });
    },
  });
}

export function useRejectChangeRequest() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ id, comment }: { id: number; comment?: string }) => {
      const { data } = await apiClient.post<ChangeRequest>(
        `/change-requests/${id}/reject`,
        { comment: comment ?? null }
      );
      return data;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["change-requests"] });
    },
  });
}
