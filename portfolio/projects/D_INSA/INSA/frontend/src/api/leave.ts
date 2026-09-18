import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import apiClient from "./client";

export type DeductFrom = "ANNUAL" | "SEPARATE";
export type LeaveUnit = "DAY" | "HALF_DAY" | "HOUR";
export type LeaveTransactionType =
  | "INITIAL_GRANT"
  | "MONTHLY_GRANT"
  | "ADDITIONAL"
  | "USE"
  | "CANCEL"
  | "EXPIRE"
  | "CARRY_OVER"
  | "ADJUST";

export interface LeaveType {
  id: number;
  code: string;
  name: string;
  deduct_from: DeductFrom;
  unit: LeaveUnit;
  is_paid: boolean;
  requires_evidence: boolean;
  sort_order: number;
  is_active: boolean;
  created_at: string | null;
}

export interface LeaveAccrualRule {
  id: number;
  year: number;
  under_1year_monthly: number;
  under_1year_max: number;
  base_days: number;
  tenure_bonus_start_years: number;
  tenure_bonus_interval: number;
  max_days: number;
  carry_over_enabled: boolean;
  updated_by: number | null;
  updated_at: string | null;
}

export interface LeaveBalance {
  id: number;
  emp_id: number;
  year: number;
  initial_days: string;
  carried_over_days: string;
  additional_days: string;
  used_days: string;
  scheduled_days: string;
  carry_over_exempt: boolean;
  updated_at: string | null;
  emp_no?: string | null;
  emp_name?: string | null;
  dept_name?: string | null;
  hire_date?: string | null;
  remaining?: string;
}

export interface LeaveTransaction {
  id: number;
  emp_id: number;
  year: number;
  transaction_type: LeaveTransactionType;
  amount: string;
  reason: string | null;
  ref_doc_id: number | null;
  balance_after: string;
  created_by: number | null;
  created_at: string | null;
}

// ── Queries ──────────────────────────────────────────────

export function useLeaveTypes(activeOnly = true) {
  return useQuery({
    queryKey: ["leave", "types", activeOnly],
    queryFn: async () => {
      const { data } = await apiClient.get<LeaveType[]>("/leave/types", {
        params: { active_only: activeOnly },
      });
      return data;
    },
  });
}

export function useLeaveRules() {
  return useQuery({
    queryKey: ["leave", "rules"],
    queryFn: async () => {
      const { data } = await apiClient.get<LeaveAccrualRule[]>("/leave/rules");
      return data;
    },
  });
}

export function useMyBalance(year?: number) {
  return useQuery({
    queryKey: ["leave", "balance", "me", year],
    queryFn: async () => {
      const { data } = await apiClient.get<LeaveBalance>(
        "/leave/balance/me",
        { params: year ? { year } : {} }
      );
      return data;
    },
  });
}

export function useBalanceList(year?: number, deptId?: number, keyword?: string) {
  return useQuery({
    queryKey: ["leave", "balance", "list", year, deptId, keyword],
    queryFn: async () => {
      const { data } = await apiClient.get<LeaveBalance[]>("/leave/balance", {
        params: {
          ...(year ? { year } : {}),
          ...(deptId ? { dept_id: deptId } : {}),
          ...(keyword ? { keyword } : {}),
        },
      });
      return data;
    },
  });
}

export function useTransactions(empId: number | null, year?: number) {
  return useQuery({
    queryKey: ["leave", "transactions", empId, year],
    enabled: empId !== null,
    queryFn: async () => {
      const { data } = await apiClient.get<LeaveTransaction[]>(
        `/leave/transactions/${empId}`,
        { params: year ? { year } : {} }
      );
      return data;
    },
  });
}

// ── Mutations ─────────────────────────────────────────────

function invalidateBalances(qc: ReturnType<typeof useQueryClient>) {
  qc.invalidateQueries({ queryKey: ["leave", "balance"] });
  qc.invalidateQueries({ queryKey: ["leave", "transactions"] });
}

export function useCreateLeaveType() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (body: Partial<LeaveType>) => {
      const { data } = await apiClient.post<LeaveType>("/leave/types", body);
      return data;
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["leave", "types"] }),
  });
}

export function useUpdateLeaveType() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ id, body }: { id: number; body: Partial<LeaveType> }) => {
      const { data } = await apiClient.put<LeaveType>(
        `/leave/types/${id}`,
        body
      );
      return data;
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["leave", "types"] }),
  });
}

export function useCreateRule() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (body: Partial<LeaveAccrualRule>) => {
      const { data } = await apiClient.post<LeaveAccrualRule>(
        "/leave/rules",
        body
      );
      return data;
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["leave", "rules"] }),
  });
}

export function useUpdateRule() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({
      year,
      body,
    }: {
      year: number;
      body: Partial<LeaveAccrualRule>;
    }) => {
      const { data } = await apiClient.put<LeaveAccrualRule>(
        `/leave/rules/${year}`,
        body
      );
      return data;
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["leave", "rules"] }),
  });
}

export function useAdjustBalance() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({
      emp_id,
      amount,
      reason,
      year,
    }: {
      emp_id: number;
      amount: number;
      reason: string;
      year?: number;
    }) => {
      const { data } = await apiClient.post<LeaveTransaction>(
        "/leave/adjust",
        { emp_id, amount, reason },
        { params: year ? { year } : {} }
      );
      return data;
    },
    onSuccess: () => invalidateBalances(qc),
  });
}

export function useCarryOverExempt() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (body: { emp_id: number; year: number; exempt: boolean }) => {
      const { data } = await apiClient.post<LeaveBalance>(
        "/leave/carry-over-exempt",
        body
      );
      return data;
    },
    onSuccess: () => invalidateBalances(qc),
  });
}

export function useRunMonthly() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ year, month }: { year?: number; month?: number } = {}) => {
      const { data } = await apiClient.post<{
        year: number;
        month: number;
        granted: number;
      }>("/leave/run-monthly", null, {
        params: {
          ...(year ? { year } : {}),
          ...(month ? { month } : {}),
        },
      });
      return data;
    },
    onSuccess: () => invalidateBalances(qc),
  });
}

export function useRunYearlyReset() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ year }: { year?: number } = {}) => {
      const { data } = await apiClient.post<{
        status: string;
        expired: number;
        carried: number;
        granted: number;
      }>("/leave/run-yearly-reset", null, {
        params: year ? { year } : {},
      });
      return data;
    },
    onSuccess: () => invalidateBalances(qc),
  });
}

export function useGrantInitial() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ emp_id, year }: { emp_id: number; year?: number }) => {
      const { data } = await apiClient.post<LeaveBalance>(
        `/leave/grant-initial/${emp_id}`,
        null,
        { params: year ? { year } : {} }
      );
      return data;
    },
    onSuccess: () => invalidateBalances(qc),
  });
}
