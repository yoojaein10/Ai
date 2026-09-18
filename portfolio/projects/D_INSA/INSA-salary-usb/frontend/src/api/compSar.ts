import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import apiClient from "./client";

export interface CompSarRecord {
  id: number;
  target_emp_id: number;
  observer_id: number;
  observed_date: string;
  situation: string | null;
  action: string | null;
  result: string | null;
  created_at: string | null;
}

export interface CompSarCreatePayload {
  target_emp_id: number;
  observed_date: string;
  situation?: string | null;
  action?: string | null;
  result?: string | null;
}

export interface CompSarUpdatePayload {
  observed_date?: string;
  situation?: string | null;
  action?: string | null;
  result?: string | null;
}

export function useCompSarList(emp_id: number | null) {
  return useQuery({
    queryKey: ["eval", "comp", "sar", { emp_id }],
    queryFn: async () => {
      const { data } = await apiClient.get<CompSarRecord[]>("/eval/comp/sar", {
        params: { emp_id: emp_id ?? undefined },
      });
      return data;
    },
    enabled: emp_id != null,
  });
}

export function useCreateCompSar() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (body: CompSarCreatePayload) => {
      const { data } = await apiClient.post<CompSarRecord>("/eval/comp/sar", body);
      return data;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["eval", "comp", "sar"] });
    },
  });
}

export function useUpdateCompSar(id: number | null) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (body: CompSarUpdatePayload) => {
      const { data } = await apiClient.put<CompSarRecord>(
        `/eval/comp/sar/${id}`,
        body,
      );
      return data;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["eval", "comp", "sar"] });
    },
  });
}

export function useDeleteCompSar() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (id: number) => {
      await apiClient.delete(`/eval/comp/sar/${id}`);
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["eval", "comp", "sar"] });
    },
  });
}
