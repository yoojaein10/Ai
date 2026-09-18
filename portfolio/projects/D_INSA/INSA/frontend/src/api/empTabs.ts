import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import apiClient from "./client";

// ── Generic hooks for 1:1 tabs ──

export function useTabData<T>(employeeId: number | null, tabKey: string) {
  return useQuery({
    queryKey: ["emp-tab", employeeId, tabKey],
    queryFn: async () => {
      const { data } = await apiClient.get<T>(
        `/employees/${employeeId}/${tabKey}`
      );
      return data;
    },
    enabled: employeeId !== null,
  });
}

export function useTabUpsert<T>(employeeId: number | null, tabKey: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (body: Record<string, unknown>) => {
      const { data } = await apiClient.put<T>(
        `/employees/${employeeId}/${tabKey}`,
        body
      );
      return data;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["emp-tab", employeeId, tabKey] });
    },
  });
}

// ── Generic hooks for 1:N tabs ──

export function useTabList<T>(employeeId: number | null, tabKey: string) {
  return useQuery({
    queryKey: ["emp-tab", employeeId, tabKey],
    queryFn: async () => {
      const { data } = await apiClient.get<T[]>(
        `/employees/${employeeId}/${tabKey}`
      );
      return data;
    },
    enabled: employeeId !== null,
  });
}

export function useTabCreate<T>(employeeId: number | null, tabKey: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (body: Record<string, unknown>) => {
      const { data } = await apiClient.post<T>(
        `/employees/${employeeId}/${tabKey}`,
        body
      );
      return data;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["emp-tab", employeeId, tabKey] });
    },
  });
}

export function useTabDelete(employeeId: number | null, tabKey: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (recordId: number) => {
      await apiClient.delete(
        `/employees/${employeeId}/${tabKey}/${recordId}`
      );
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["emp-tab", employeeId, tabKey] });
    },
  });
}
