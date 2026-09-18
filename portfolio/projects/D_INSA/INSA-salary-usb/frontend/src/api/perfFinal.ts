import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import apiClient from "./client";

export interface PerfFinal {
  id: number;
  target_id: number;
  achievement_rate: string | null;
  description: string | null;
  self_score: string | null;
  submitted_at: string | null;
}

export interface PerfFinalUpsertPayload {
  target_id: number;
  achievement_rate?: string | number | null;
  description?: string | null;
  self_score?: string | number | null;
}

export function usePerfFinal(targetId: number | null) {
  return useQuery({
    queryKey: ["eval", "perf", "final", { target_id: targetId }],
    queryFn: async () => {
      const { data } = await apiClient.get<PerfFinal | null>("/eval/perf/final", {
        params: { target_id: targetId },
      });
      return data;
    },
    enabled: targetId != null,
  });
}

export function useUpsertPerfFinal() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (body: PerfFinalUpsertPayload) => {
      const { data } = await apiClient.post<PerfFinal>("/eval/perf/final", body);
      return data;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["eval", "perf", "final"] });
    },
  });
}
