import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import apiClient from "./client";

export type ScheduleStage = "TARGET" | "MID" | "FINAL" | "COMPREHENSIVE";

export interface EvalSchedule {
  id: number;
  round_id: number;
  stage: ScheduleStage;
  start_date: string | null;
  end_date: string | null;
}

export interface EvalScheduleItem {
  stage: ScheduleStage;
  start_date?: string | null;
  end_date?: string | null;
}

export interface EvalScheduleBulkPayload {
  round_id: number;
  schedules: EvalScheduleItem[];
}

export function useEvalSchedules(roundId: number | null) {
  return useQuery({
    queryKey: ["eval", "schedules", { roundId }],
    queryFn: async () => {
      const { data } = await apiClient.get<EvalSchedule[]>("/eval/schedules", {
        params: { round_id: roundId },
      });
      return data;
    },
    enabled: roundId !== null,
  });
}

export function useBulkUpsertEvalSchedules() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (body: EvalScheduleBulkPayload) => {
      const { data } = await apiClient.post<EvalSchedule[]>("/eval/schedules", body);
      return data;
    },
    onSuccess: (_data, variables) => {
      qc.invalidateQueries({
        queryKey: ["eval", "schedules", { roundId: variables.round_id }],
      });
    },
  });
}
