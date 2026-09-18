import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import apiClient from "./client";

export type RaterType = "BOSS" | "PEER" | "SUBORDINATE";

export interface MyEvalTarget {
  evaluatee_id: number;
  evaluatee_emp_no: string;
  evaluatee_name: string;
  rater_type: RaterType;
  submitted: boolean;
}

export interface MultiResponseItem {
  indicator_id: number;
  score: number | string;
  comment?: string | null;
}

export interface MultiResponseSubmitPayload {
  round_id: number;
  evaluatee_id: number;
  rater_type: RaterType;
  items: MultiResponseItem[];
}

export function useMyMultiTargets(round_id: number | null) {
  return useQuery({
    queryKey: ["eval", "multi", "my-targets", { round_id }],
    queryFn: async () => {
      const { data } = await apiClient.get<MyEvalTarget[]>(
        "/eval/multi/my-targets",
        { params: { round_id: round_id ?? undefined } },
      );
      return data;
    },
    enabled: round_id != null,
  });
}

export function useSubmitMultiResponse() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (body: MultiResponseSubmitPayload) => {
      const { data } = await apiClient.post<{ inserted: number }>(
        "/eval/multi/response",
        body,
      );
      return data;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["eval", "multi", "my-targets"] });
      qc.invalidateQueries({ queryKey: ["eval", "multi", "results"] });
    },
  });
}
