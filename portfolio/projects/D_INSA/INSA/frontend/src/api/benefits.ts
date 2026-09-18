import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import apiClient from "./client";

// ── Items ─────────────────────────────────────────────────

export interface BenefitItem {
  id: number;
  code: string;
  name: string;
  category: string;
  event_type: string | null;
  default_amount: number | null;
  default_leave_days: number | null;
  description: string | null;
  is_active: boolean;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface BenefitItemCreate {
  code: string;
  name: string;
  category: string;
  event_type?: string | null;
  default_amount?: number | null;
  default_leave_days?: number | null;
  description?: string | null;
  is_active?: boolean;
}

export type BenefitItemUpdate = Partial<BenefitItemCreate>;

export interface BenefitItemListResponse {
  total: number;
  items: BenefitItem[];
}

export function useBenefitItems(
  q: { keyword?: string; category?: string; is_active?: boolean } = {}
) {
  return useQuery({
    queryKey: ["benefit-items", q],
    queryFn: async () => {
      const { data } = await apiClient.get<BenefitItemListResponse>(
        "/benefits/items",
        { params: q }
      );
      return data;
    },
  });
}

export function useCreateBenefitItem() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (data: BenefitItemCreate) => {
      const { data: res } = await apiClient.post<BenefitItem>(
        "/benefits/items",
        data
      );
      return res;
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["benefit-items"] }),
  });
}

export function useUpdateBenefitItem() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ id, data }: { id: number; data: BenefitItemUpdate }) => {
      const { data: res } = await apiClient.patch<BenefitItem>(
        `/benefits/items/${id}`,
        data
      );
      return res;
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["benefit-items"] }),
  });
}

export function useDeleteBenefitItem() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (id: number) => {
      await apiClient.delete(`/benefits/items/${id}`);
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["benefit-items"] }),
  });
}

// ── Events (경조사) ───────────────────────────────────────

export interface LinkedSchedule {
  schedule_date: string;
  gubun: string;
  bigo: string | null;
}

export interface BenefitEvent {
  id: number;
  employee_id: number;
  emp_no: string | null;
  emp_name: string | null;
  dept_name: string | null;
  item_id: number | null;
  item_code: string | null;
  item_name: string | null;
  event_type: string;
  target_person: string | null;
  event_date: string;
  amount: number | null;
  leave_days: number | null;
  remark: string | null;
  linked_schedules: LinkedSchedule[];
}

export interface BenefitEventCreate {
  employee_id: number;
  item_id?: number | null;
  event_type: string;
  target_person?: string | null;
  event_date: string;
  amount?: number | null;
  leave_days?: number | null;
  remark?: string | null;
}

export type BenefitEventUpdate = Partial<Omit<BenefitEventCreate, "employee_id">>;

export interface BenefitEventListResponse {
  total: number;
  items: BenefitEvent[];
}

export function useBenefitEvents(
  q: { year?: number; event_type?: string; keyword?: string } = {}
) {
  return useQuery({
    queryKey: ["benefit-events", q],
    queryFn: async () => {
      const { data } = await apiClient.get<BenefitEventListResponse>(
        "/benefits/events",
        {
          params: {
            year: q.year,
            event_type: q.event_type || undefined,
            keyword: q.keyword || undefined,
          },
        }
      );
      return data;
    },
  });
}

export function useCreateBenefitEvent() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (data: BenefitEventCreate) => {
      const { data: res } = await apiClient.post<BenefitEvent>(
        "/benefits/events",
        data
      );
      return res;
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["benefit-events"] }),
  });
}

export function useUpdateBenefitEvent() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({
      id,
      data,
    }: {
      id: number;
      data: BenefitEventUpdate;
    }) => {
      const { data: res } = await apiClient.patch<BenefitEvent>(
        `/benefits/events/${id}`,
        data
      );
      return res;
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["benefit-events"] }),
  });
}

export function useDeleteBenefitEvent() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (id: number) => {
      await apiClient.delete(`/benefits/events/${id}`);
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["benefit-events"] }),
  });
}

export async function uploadBenefitEvents(
  file: File
): Promise<{ created: number; skipped: number; errors: string[] }> {
  const form = new FormData();
  form.append("file", file);
  const { data } = await apiClient.post("/benefits/events/upload", form, {
    headers: { "Content-Type": "multipart/form-data" },
  });
  return data;
}

// ── Health (건강검진) ─────────────────────────────────────

export interface BenefitHealth {
  id: number;
  employee_id: number;
  emp_no: string | null;
  emp_name: string | null;
  dept_name: string | null;
  check_year: number;
  check_date: string | null;
  provider: string | null;
  check_type: string | null;
  result: string | null;
  recheck_required: boolean;
  recheck_date: string | null;
  remark: string | null;
}

export interface BenefitHealthCreate {
  employee_id: number;
  check_year: number;
  check_date?: string | null;
  provider?: string | null;
  check_type?: string | null;
  result?: string | null;
  recheck_required?: boolean;
  recheck_date?: string | null;
  remark?: string | null;
}

export type BenefitHealthUpdate = Partial<Omit<BenefitHealthCreate, "employee_id">>;

export interface BenefitHealthListResponse {
  total: number;
  items: BenefitHealth[];
}

export function useBenefitHealth(
  q: {
    year?: number;
    result?: string;
    recheck_only?: boolean;
    keyword?: string;
  } = {}
) {
  return useQuery({
    queryKey: ["benefit-health", q],
    queryFn: async () => {
      const { data } = await apiClient.get<BenefitHealthListResponse>(
        "/benefits/health",
        {
          params: {
            year: q.year,
            result: q.result || undefined,
            recheck_only: q.recheck_only || undefined,
            keyword: q.keyword || undefined,
          },
        }
      );
      return data;
    },
  });
}

export function useCreateBenefitHealth() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (data: BenefitHealthCreate) => {
      const { data: res } = await apiClient.post<BenefitHealth>(
        "/benefits/health",
        data
      );
      return res;
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["benefit-health"] }),
  });
}

export function useUpdateBenefitHealth() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({
      id,
      data,
    }: {
      id: number;
      data: BenefitHealthUpdate;
    }) => {
      const { data: res } = await apiClient.patch<BenefitHealth>(
        `/benefits/health/${id}`,
        data
      );
      return res;
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["benefit-health"] }),
  });
}

export function useDeleteBenefitHealth() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (id: number) => {
      await apiClient.delete(`/benefits/health/${id}`);
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["benefit-health"] }),
  });
}

export async function uploadBenefitHealth(
  file: File
): Promise<{ created: number; skipped: number; errors: string[] }> {
  const form = new FormData();
  form.append("file", file);
  const { data } = await apiClient.post("/benefits/health/upload", form, {
    headers: { "Content-Type": "multipart/form-data" },
  });
  return data;
}

// ── Overview ──────────────────────────────────────────────

export interface BenefitOverviewResponse {
  year: number;
  event_total_count: number;
  event_total_amount: number;
  event_total_leave_days: number;
  by_category: {
    category: string;
    count: number;
    total_amount: number;
    total_leave_days: number;
  }[];
  by_month: { month: number; count: number; total_amount: number }[];
  health: {
    total: number;
    normal: number;
    caution: number;
    abnormal: number;
    recheck_required: number;
  };
}

export function useBenefitOverview(year: number) {
  return useQuery({
    queryKey: ["benefit-overview", year],
    queryFn: async () => {
      const { data } = await apiClient.get<BenefitOverviewResponse>(
        "/benefits/overview",
        { params: { year } }
      );
      return data;
    },
  });
}
