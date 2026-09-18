import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import apiClient from "./client";

export interface TravelReportCreateBody {
  line_template_id: number;
  title?: string | null;
  report_content: string;
  actual_cost?: string | null;
  receipts_url?: string | null;
}

export interface TravelReportResponse {
  id: number;
  travel_id: number;
  doc_id: number | null;
  report_content: string;
  actual_cost: string | null;
  receipts_url: string | null;
  reported_at: string | null;
  created_at: string | null;
}

function invalidate(qc: ReturnType<typeof useQueryClient>) {
  qc.invalidateQueries({ queryKey: ["travel"] });
  qc.invalidateQueries({ queryKey: ["approval"] });
}

export function useCreateTravelReport(orderDocId: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (body: TravelReportCreateBody) => {
      const { data } = await apiClient.post<{
        report_doc_id: number;
        report_id: number;
        status: string;
      }>(`/travel/orders/${orderDocId}/report`, body);
      return data;
    },
    onSuccess: () => invalidate(qc),
  });
}

export function useSubmitTravelReport() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (docId: number) => {
      const { data } = await apiClient.post<{ doc_id: number; status: string }>(
        `/travel/reports/${docId}/submit`,
      );
      return data;
    },
    onSuccess: () => invalidate(qc),
  });
}

export function useCancelTravelReport() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (docId: number) => {
      const { data } = await apiClient.post<{ doc_id: number; status: string }>(
        `/travel/reports/${docId}/cancel`,
      );
      return data;
    },
    onSuccess: () => invalidate(qc),
  });
}

export function useTravelReport(orderDocId: number | null) {
  return useQuery({
    queryKey: ["travel", "reports", "by-order", orderDocId],
    queryFn: async () => {
      const { data } = await apiClient.get<TravelReportResponse | null>(
        `/travel/orders/${orderDocId}/report`,
      );
      return data;
    },
    enabled: orderDocId !== null,
  });
}
