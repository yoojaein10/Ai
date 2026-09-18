import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import apiClient from "./client";

export interface CompEvalBoss {
  id: number;
  evaluatee_id: number;
  evaluator_id: number;
  round_id: number;
  indicator_id: number;
  score: number;
  comment: string | null;
  submitted_at: string | null;
}

export interface CompEvalBossItem {
  indicator_id: number;
  score: number;
  comment?: string | null;
}

export interface CompEvalBossBulkPayload {
  evaluatee_id: number;
  round_id: number;
  items: CompEvalBossItem[];
}

export function useCompBossEvals(params: {
  evaluatee_id?: number | null;
  round_id?: number | null;
}) {
  return useQuery({
    queryKey: ["eval", "comp", "boss", params],
    queryFn: async () => {
      const { data } = await apiClient.get<CompEvalBoss[]>("/eval/comp/boss", {
        params: {
          evaluatee_id: params.evaluatee_id ?? undefined,
          round_id: params.round_id ?? undefined,
        },
      });
      return data;
    },
    enabled: params.evaluatee_id != null && params.round_id != null,
  });
}

export function useSubmitCompBoss() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (body: CompEvalBossBulkPayload) => {
      const { data } = await apiClient.post<CompEvalBoss[]>(
        "/eval/comp/boss",
        body,
      );
      return data;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["eval", "comp", "boss"] });
    },
  });
}
