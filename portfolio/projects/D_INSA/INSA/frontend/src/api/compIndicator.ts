import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import apiClient from "./client";

export interface CompBehavior {
  id: number;
  indicator_id: number;
  level: number;
  description: string | null;
}

export interface CompIndicator {
  id: number;
  year: number;
  code: string;
  name: string;
  description: string | null;
  weight: string | null;
  created_at: string | null;
  behaviors: CompBehavior[];
}

export interface CompIndicatorCreatePayload {
  year: number;
  code: string;
  name: string;
  description?: string | null;
  weight?: string | number | null;
  behaviors?: { level: number; description?: string | null }[];
}

export function useCompIndicators(year: number | null) {
  return useQuery({
    queryKey: ["eval", "comp", "indicators", { year }],
    queryFn: async () => {
      const { data } = await apiClient.get<CompIndicator[]>(
        "/eval/comp/indicators",
        { params: { year: year ?? undefined } },
      );
      return data;
    },
  });
}

export function useCreateCompIndicator() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (body: CompIndicatorCreatePayload) => {
      const { data } = await apiClient.post<CompIndicator>(
        "/eval/comp/indicators",
        body,
      );
      return data;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["eval", "comp", "indicators"] });
    },
  });
}
