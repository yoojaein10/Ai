import { useQuery } from "@tanstack/react-query";
import apiClient from "./client";

export interface MultiIndicatorResult {
  indicator_id: number;
  indicator_name: string;
  avg_score: string | null;
  response_count: number;
}

export interface MultiResult {
  round_id: number;
  evaluatee_id: number;
  insufficient: boolean;
  min_required: number;
  indicators: MultiIndicatorResult[];
}

export interface MultiSubmissionStatus {
  round_id: number;
  expected: number;
  submitted: number;
  submission_rate: number;
  submitted_at_latest: string | null;
}

export function useMyMultiResult(emp_id: number | null, round_id: number | null) {
  return useQuery({
    queryKey: ["eval", "multi", "results", { emp_id, round_id }],
    queryFn: async () => {
      const { data } = await apiClient.get<MultiResult>(
        `/eval/multi/results/${emp_id}`,
        { params: { round_id: round_id ?? undefined } },
      );
      return data;
    },
    enabled: emp_id != null && round_id != null,
  });
}

export function useMultiStatus(round_id: number | null) {
  return useQuery({
    queryKey: ["eval", "multi", "status", { round_id }],
    queryFn: async () => {
      const { data } = await apiClient.get<MultiSubmissionStatus>(
        "/eval/multi/status",
        { params: { round_id: round_id ?? undefined } },
      );
      return data;
    },
    enabled: round_id != null,
  });
}
