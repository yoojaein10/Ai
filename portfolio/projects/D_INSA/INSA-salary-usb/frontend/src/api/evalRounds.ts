import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import apiClient from "./client";

export type RoundStatus = "PLANNED" | "IN_PROGRESS" | "CLOSED";

export interface EvalRound {
  id: number;
  year: number;
  name: string;
  start_date: string | null;
  end_date: string | null;
  status: RoundStatus;
  created_at: string | null;
  updated_at: string | null;
}

export interface EvalRoundCreatePayload {
  year: number;
  name: string;
  start_date?: string | null;
  end_date?: string | null;
  status?: RoundStatus;
}

export interface EvalRoundUpdatePayload {
  name?: string;
  start_date?: string | null;
  end_date?: string | null;
  status?: RoundStatus;
}

export function useEvalRounds(year?: number) {
  return useQuery({
    queryKey: ["eval", "rounds", { year }],
    queryFn: async () => {
      const { data } = await apiClient.get<EvalRound[]>("/eval/rounds", {
        params: year ? { year } : {},
      });
      return data;
    },
  });
}

export function useCreateEvalRound() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (body: EvalRoundCreatePayload) => {
      const { data } = await apiClient.post<EvalRound>("/eval/rounds", body);
      return data;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["eval", "rounds"] });
    },
  });
}

export function useUpdateEvalRound(id: number | null) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (body: EvalRoundUpdatePayload) => {
      const { data } = await apiClient.put<EvalRound>(`/eval/rounds/${id}`, body);
      return data;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["eval", "rounds"] });
    },
  });
}

export function useCloseEvalRound() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (id: number) => {
      const { data } = await apiClient.put<EvalRound>(`/eval/rounds/${id}/close`);
      return data;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["eval", "rounds"] });
    },
  });
}
