import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import apiClient from "./client";

export interface PerfKpi {
  id: number;
  round_id: number;
  code: string;
  name: string;
  measure_type: string | null;
  weight: string | null;
  perspective: string | null;
  created_at: string | null;
}

export interface PerfKpiCreatePayload {
  round_id: number;
  code: string;
  name: string;
  measure_type?: string | null;
  weight?: string | number | null;
  perspective?: string | null;
}

export interface PerfKpiUpdatePayload {
  code?: string;
  name?: string;
  measure_type?: string | null;
  weight?: string | number | null;
  perspective?: string | null;
}

export function usePerfKpis(roundId: number | null) {
  return useQuery({
    queryKey: ["eval", "perf", "kpis", { round_id: roundId }],
    queryFn: async () => {
      const { data } = await apiClient.get<PerfKpi[]>("/eval/perf/kpis", {
        params: { round_id: roundId },
      });
      return data;
    },
    enabled: roundId != null,
  });
}

export function useCreatePerfKpi() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (body: PerfKpiCreatePayload) => {
      const { data } = await apiClient.post<PerfKpi>("/eval/perf/kpis", body);
      return data;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["eval", "perf", "kpis"] });
    },
  });
}

export function useUpdatePerfKpi(id: number | null) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (body: PerfKpiUpdatePayload) => {
      const { data } = await apiClient.put<PerfKpi>(`/eval/perf/kpis/${id}`, body);
      return data;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["eval", "perf", "kpis"] });
    },
  });
}

export function useDeletePerfKpi() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (id: number) => {
      await apiClient.delete(`/eval/perf/kpis/${id}`);
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["eval", "perf", "kpis"] });
    },
  });
}
