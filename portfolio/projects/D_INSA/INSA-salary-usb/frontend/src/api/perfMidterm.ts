import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import apiClient from "./client";

export interface PerfMidterm {
  id: number;
  target_id: number;
  progress_rate: string | null;
  description: string | null;
  expected_rate: string | null;
  submitted_at: string | null;
}

export interface PerfMidtermUpsertPayload {
  target_id: number;
  progress_rate?: string | number | null;
  description?: string | null;
  expected_rate?: string | number | null;
}

export function usePerfMidterm(targetId: number | null) {
  return useQuery({
    queryKey: ["eval", "perf", "midterm", { target_id: targetId }],
    queryFn: async () => {
      const { data } = await apiClient.get<PerfMidterm | null>("/eval/perf/midterm", {
        params: { target_id: targetId },
      });
      return data;
    },
    enabled: targetId != null,
  });
}

export function useUpsertPerfMidterm() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (body: PerfMidtermUpsertPayload) => {
      const { data } = await apiClient.post<PerfMidterm>("/eval/perf/midterm", body);
      return data;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["eval", "perf", "midterm"] });
    },
  });
}
