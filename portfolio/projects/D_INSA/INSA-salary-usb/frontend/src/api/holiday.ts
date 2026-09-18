import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import apiClient from "./client";

export interface Holiday {
  id: number;
  date: string;
  name: string;
  is_recurring: boolean;
  created_at: string | null;
}

export interface HolidayCreateBody {
  date: string;
  name: string;
  is_recurring: boolean;
}

export function useHolidays(year?: number) {
  return useQuery({
    queryKey: ["holiday", "list", year ?? "all"],
    queryFn: async () => {
      const { data } = await apiClient.get<Holiday[]>("/holiday", {
        params: year ? { year } : {},
      });
      return data;
    },
  });
}

export function useCreateHoliday() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (body: HolidayCreateBody) => {
      const { data } = await apiClient.post<Holiday>("/holiday", body);
      return data;
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["holiday"] }),
  });
}

export function useDeleteHoliday() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (id: number) => {
      await apiClient.delete(`/holiday/${id}`);
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["holiday"] }),
  });
}
