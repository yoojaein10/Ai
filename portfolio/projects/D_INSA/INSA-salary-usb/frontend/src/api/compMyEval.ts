import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import apiClient from "./client";

export interface CompEvalSelf {
  id: number;
  emp_id: number;
  round_id: number;
  indicator_id: number;
  score: number;
  comment: string | null;
  submitted_at: string | null;
}

export interface CompEvalSelfItem {
  indicator_id: number;
  score: number;
  comment?: string | null;
}

export interface CompEvalSelfBulkPayload {
  round_id: number;
  items: CompEvalSelfItem[];
}

export function useMyCompEval(round_id: number | null) {
  return useQuery({
    queryKey: ["eval", "comp", "my-eval", { round_id }],
    queryFn: async () => {
      const { data } = await apiClient.get<CompEvalSelf[]>(
        "/eval/comp/my-eval",
        { params: { round_id: round_id ?? undefined } },
      );
      return data;
    },
    enabled: round_id != null,
  });
}

export function useSubmitCompSelf() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (body: CompEvalSelfBulkPayload) => {
      const { data } = await apiClient.post<CompEvalSelf[]>(
        "/eval/comp/self",
        body,
      );
      return data;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["eval", "comp", "my-eval"] });
    },
  });
}
