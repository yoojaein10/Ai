import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import apiClient from "./client";

export type TargetStatus = "DRAFT" | "SUBMITTED" | "APPROVED" | "REJECTED";

export interface PerfTarget {
  id: number;
  emp_id: number;
  round_id: number;
  kpi_id: number | null;
  target_value: string | null;
  is_organization: boolean;
  status: TargetStatus;
  weight_percent: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface PerfTargetCreatePayload {
  emp_id: number;
  round_id: number;
  kpi_id?: number | null;
  target_value?: string | null;
  is_organization?: boolean;
  weight_percent?: string | number | null;
}

export interface PerfTargetUpdatePayload {
  kpi_id?: number | null;
  target_value?: string | null;
  is_organization?: boolean;
  weight_percent?: string | number | null;
}

export function usePerfTargets(params: { emp_id?: number | null; round_id?: number | null }) {
  return useQuery({
    queryKey: ["eval", "perf", "targets", params],
    queryFn: async () => {
      const { data } = await apiClient.get<PerfTarget[]>("/eval/perf/targets", {
        params: {
          emp_id: params.emp_id ?? undefined,
          round_id: params.round_id ?? undefined,
        },
      });
      return data;
    },
  });
}

export function useCreatePerfTarget() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (body: PerfTargetCreatePayload) => {
      const { data } = await apiClient.post<PerfTarget>("/eval/perf/targets", body);
      return data;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["eval", "perf", "targets"] });
    },
  });
}

export function useUpdatePerfTarget(id: number | null) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (body: PerfTargetUpdatePayload) => {
      const { data } = await apiClient.put<PerfTarget>(`/eval/perf/targets/${id}`, body);
      return data;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["eval", "perf", "targets"] });
    },
  });
}

export function useSubmitPerfTarget() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (id: number) => {
      const { data } = await apiClient.put<PerfTarget>(`/eval/perf/targets/${id}/submit`);
      return data;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["eval", "perf", "targets"] });
    },
  });
}

export function useApprovePerfTarget() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (id: number) => {
      const { data } = await apiClient.put<PerfTarget>(`/eval/perf/targets/${id}/approve`);
      return data;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["eval", "perf", "targets"] });
    },
  });
}

export function useRejectPerfTarget() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (id: number) => {
      const { data } = await apiClient.put<PerfTarget>(`/eval/perf/targets/${id}/reject`);
      return data;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["eval", "perf", "targets"] });
    },
  });
}
