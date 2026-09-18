import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import apiClient from "./client";

export interface MultiIndicator {
  id: number;
  round_id: number;
  name: string;
  description: string | null;
  max_score: number;
  created_at: string | null;
}

export interface MultiIndicatorCreatePayload {
  round_id: number;
  name: string;
  description?: string | null;
  max_score?: number;
}

export function useMultiIndicators(round_id: number | null) {
  return useQuery({
    queryKey: ["eval", "multi", "indicators", { round_id }],
    queryFn: async () => {
      const { data } = await apiClient.get<MultiIndicator[]>(
        "/eval/multi/indicators",
        { params: { round_id: round_id ?? undefined } },
      );
      return data;
    },
    enabled: round_id != null,
  });
}

export function useCreateMultiIndicator() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (body: MultiIndicatorCreatePayload) => {
      const { data } = await apiClient.post<MultiIndicator>(
        "/eval/multi/indicators",
        body,
      );
      return data;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["eval", "multi", "indicators"] });
    },
  });
}
