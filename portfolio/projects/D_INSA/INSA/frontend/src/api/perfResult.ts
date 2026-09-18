import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import apiClient from "./client";

export interface PerfResult {
  id: number;
  emp_id: number;
  round_id: number;
  evaluator_id: number;
  score: string | null;
  grade: string | null;
  comment: string | null;
  created_at: string | null;
}

export interface PerfResultCreatePayload {
  emp_id: number;
  round_id: number;
  score?: string | number | null;
  grade?: string | null;
  comment?: string | null;
}

export function usePerfResults(params: { round_id?: number | null; dept_id?: number | null }) {
  return useQuery({
    queryKey: ["eval", "perf", "results", params],
    queryFn: async () => {
      const { data } = await apiClient.get<PerfResult[]>("/eval/perf/results", {
        params: {
          round_id: params.round_id ?? undefined,
          dept_id: params.dept_id ?? undefined,
        },
      });
      return data;
    },
  });
}

export function useCreatePerfResult() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (body: PerfResultCreatePayload) => {
      const { data } = await apiClient.post<PerfResult>("/eval/perf/results", body);
      return data;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["eval", "perf", "results"] });
    },
  });
}
