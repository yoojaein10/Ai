import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import apiClient from "./client";

export type EvalType = "PERF" | "COMP" | "MULTI";
export type RaterType = "BOSS" | "PEER" | "SUBORDINATE";

export interface EvalApprover {
  id: number;
  round_id: number;
  evaluatee_id: number;
  evaluator_id: number;
  eval_type: EvalType;
  rater_type: RaterType | null;
  created_at: string | null;
}

export interface EvalApproverItem {
  evaluatee_id: number;
  evaluator_id: number;
  eval_type: EvalType;
  rater_type?: RaterType | null;
}

export interface EvalApproverBulkPayload {
  round_id: number;
  items: EvalApproverItem[];
}

export function useEvalApprovers(roundId: number | null, evalType?: EvalType) {
  return useQuery({
    queryKey: ["eval", "approvers", { roundId, evalType }],
    queryFn: async () => {
      const { data } = await apiClient.get<EvalApprover[]>("/eval/approvers", {
        params: {
          round_id: roundId,
          ...(evalType ? { eval_type: evalType } : {}),
        },
      });
      return data;
    },
    enabled: roundId !== null,
  });
}

export function useBulkUpsertEvalApprovers() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (body: EvalApproverBulkPayload) => {
      const { data } = await apiClient.post<EvalApprover[]>("/eval/approvers", body);
      return data;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["eval", "approvers"] });
    },
  });
}

export function useDeleteEvalApprover() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (id: number) => {
      await apiClient.delete(`/eval/approvers/${id}`);
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["eval", "approvers"] });
    },
  });
}
