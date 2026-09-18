import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import apiClient from "./client";

export type TravelType = "DOMESTIC" | "OVERSEAS";

export interface CompanionInfo {
  emp_id: number;
  emp_no: string | null;
  name_ko: string | null;
  dept_name: string | null;
}

export interface TravelOrderCreateBody {
  line_template_id: number;
  title?: string | null;
  travel_type: TravelType;
  purpose: string;
  destination: string;
  client_company?: string | null;
  start_at: string;
  end_at: string;
  transportation?: string | null;
  estimated_cost?: string | null;
  project_code?: string | null;
  appraisal_case_no?: string | null;
  remarks?: string | null;
  companion_emp_ids: number[];
}

export interface TravelOrderDetailResponse {
  id: number;
  doc_id: number;
  travel_type: string;
  purpose: string;
  destination: string;
  client_company: string | null;
  start_at: string;
  end_at: string;
  transportation: string | null;
  estimated_cost: string | null;
  project_code: string | null;
  appraisal_case_no: string | null;
  remarks: string | null;
  created_at: string | null;
  companions: CompanionInfo[];
}

export interface TravelOrderListRow {
  doc_id: number;
  doc_no: string | null;
  title: string;
  status: string;
  drafter_id: number;
  drafter_name: string | null;
  drafter_emp_no: string | null;
  dept_name: string | null;
  travel_type: string;
  destination: string;
  purpose: string;
  start_at: string;
  end_at: string;
  appraisal_case_no: string | null;
  estimated_cost: string | null;
  companion_count: number;
  drafted_at: string | null;
  completed_at: string | null;
  has_report: boolean;
}

function invalidateTravel(qc: ReturnType<typeof useQueryClient>) {
  qc.invalidateQueries({ queryKey: ["travel"] });
  qc.invalidateQueries({ queryKey: ["approval"] });
  qc.invalidateQueries({ queryKey: ["calendar"] });
}

// ── Mutations ──────────────────────────────────────────────

export function useCreateTravelOrder() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (body: TravelOrderCreateBody) => {
      const { data } = await apiClient.post<{
        doc_id: number;
        detail_id: number;
        status: string;
      }>("/travel/orders", body);
      return data;
    },
    onSuccess: () => invalidateTravel(qc),
  });
}

export function useSubmitTravelOrder() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (docId: number) => {
      const { data } = await apiClient.post<{ doc_id: number; status: string }>(
        `/travel/orders/${docId}/submit`,
      );
      return data;
    },
    onSuccess: () => invalidateTravel(qc),
  });
}

export function useCancelTravelOrder() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (docId: number) => {
      const { data } = await apiClient.post<{ doc_id: number; status: string }>(
        `/travel/orders/${docId}/cancel`,
      );
      return data;
    },
    onSuccess: () => invalidateTravel(qc),
  });
}

// ── Queries ────────────────────────────────────────────────

export function useMyTravelOrders(params?: {
  status?: string;
  include_companion?: boolean;
}) {
  return useQuery({
    queryKey: [
      "travel",
      "orders",
      "my",
      params?.status ?? "all",
      params?.include_companion ?? true,
    ],
    queryFn: async () => {
      const { data } = await apiClient.get<TravelOrderListRow[]>(
        "/travel/orders/my",
        {
          params: {
            ...(params?.status ? { status: params.status } : {}),
            include_companion: params?.include_companion ?? true,
          },
        },
      );
      return data;
    },
  });
}

export function useTeamTravelOrders(params?: { status?: string }) {
  return useQuery({
    queryKey: ["travel", "orders", "team", params?.status ?? "all"],
    queryFn: async () => {
      const { data } = await apiClient.get<TravelOrderListRow[]>(
        "/travel/orders/team",
        {
          params: params?.status ? { status: params.status } : {},
        },
      );
      return data;
    },
  });
}

export function useTravelOrderDetail(docId: number | null) {
  return useQuery({
    queryKey: ["travel", "orders", "detail", docId],
    queryFn: async () => {
      const { data } = await apiClient.get<TravelOrderDetailResponse>(
        `/travel/orders/${docId}`,
      );
      return data;
    },
    enabled: docId !== null,
  });
}

export function useTravelOrdersByCaseNo(caseNo: string | null) {
  return useQuery({
    queryKey: ["travel", "orders", "by-case", caseNo],
    queryFn: async () => {
      const { data } = await apiClient.get<TravelOrderListRow[]>(
        `/travel/orders/by-case/${encodeURIComponent(caseNo ?? "")}`,
      );
      return data;
    },
    enabled: !!caseNo,
  });
}
