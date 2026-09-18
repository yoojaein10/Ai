import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import apiClient from "./client";

export interface GradeCriterion {
  grade: string;
  min: number;
  max: number;
  default_ratio: number;
}

export interface EvalSetting {
  id: number;
  year: number;
  weight_config: Record<string, number>;
  grade_criteria: GradeCriterion[];
  updated_at: string | null;
}

export interface EvalSettingUpsertPayload {
  year: number;
  weight_config: Record<string, number>;
  grade_criteria: GradeCriterion[];
}

export function useEvalSetting(year: number | null) {
  return useQuery({
    queryKey: ["eval", "setting", { year }],
    queryFn: async () => {
      const { data } = await apiClient.get<EvalSetting | null>("/eval/settings", {
        params: { year },
      });
      return data;
    },
    enabled: year !== null,
  });
}

export function useUpsertEvalSetting() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (body: EvalSettingUpsertPayload) => {
      const { data } = await apiClient.put<EvalSetting>("/eval/settings", body);
      return data;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["eval", "setting"] });
    },
  });
}
