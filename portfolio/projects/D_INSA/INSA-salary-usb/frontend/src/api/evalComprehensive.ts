import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import apiClient from "./client";

export interface ComprehensiveResponse {
  id: number;
  emp_id: number;
  round_id: number;
  perf_score: string | null;
  comp_score: string | null;
  multi_score: string | null;
  total_score: string | null;
  original_grade: string | null;
  final_grade: string | null;
  is_adjusted: boolean;
  adjusted_by: number | null;
  adjusted_reason: string | null;
  calculated_at: string;
  adjusted_at: string | null;
}

export interface CalculateResponse {
  round_id: number;
  upserted: number;
}

export interface GradeAdjustPayload {
  comp_id: number;
  new_grade: string;
  adjusted_reason: string;
}

export function useComprehensiveList(round_id: number | null) {
  return useQuery({
    queryKey: ["eval", "comprehensive", "list", { round_id }],
    queryFn: async () => {
      const { data } = await apiClient.get<ComprehensiveResponse[]>(
        "/eval/comprehensive",
        { params: { round_id: round_id ?? undefined } },
      );
      return data;
    },
    enabled: round_id != null,
  });
}

export function useCalculateComprehensive() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (round_id: number) => {
      const { data } = await apiClient.post<CalculateResponse>(
        "/eval/comprehensive/calculate",
        { round_id },
      );
      return data;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["eval", "comprehensive", "list"] });
    },
  });
}

export function useAdjustGrade() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (payload: GradeAdjustPayload) => {
      const { data } = await apiClient.put<ComprehensiveResponse>(
        `/eval/comprehensive/${payload.comp_id}/grade`,
        {
          new_grade: payload.new_grade,
          adjusted_reason: payload.adjusted_reason,
        },
      );
      return data;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["eval", "comprehensive", "list"] });
    },
  });
}
