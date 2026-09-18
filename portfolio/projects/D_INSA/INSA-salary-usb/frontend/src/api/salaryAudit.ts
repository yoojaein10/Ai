import { useQuery } from "@tanstack/react-query";
import apiClient from "./client";

export type SalaryAction =
  | "OPEN"
  | "UNLOCK_FAIL"
  | "SAVE"
  | "CREATE_VAULT"
  | "LOCK"
  | "PASSWORD_CHANGE"
  | "DELEGATE"
  | "IP_DENIED"
  | "POLICY_CHANGE";

export interface AccessLogRow {
  id: number;
  user_id: number;
  action: SalaryAction;
  target_user_id: number | null;
  record_count: number | null;
  ip_address: string | null;
  user_agent: string | null;
  occurred_at: string;
}

/**
 * 접근 기록을 남긴다. 1회 재시도하고, 실패해도 절대 throw하지 않는다.
 *
 * 파일은 INSA 밖에서도 열 수 있으므로 로그가 완전성을 보증하지 못한다.
 * 로그 서버 장애로 급여 업무가 멈추는 쪽이 더 나쁘다 (스펙 §10.4).
 */
export async function recordAccess(
  action: SalaryAction,
  opts?: { recordCount?: number; targetUserId?: number },
): Promise<void> {
  const body = {
    action,
    record_count: opts?.recordCount ?? null,
    target_user_id: opts?.targetUserId ?? null,
  };
  for (let attempt = 0; attempt < 2; attempt += 1) {
    try {
      await apiClient.post("/salary/access-logs", body);
      return;
    } catch (error) {
      if (attempt === 1) {
        console.error("연봉 접근 기록 전송에 실패했습니다:", error);
      }
    }
  }
}

export interface AccessLogFilters {
  userId?: number;
  action?: SalaryAction;
}

export function useAccessLogs(filters: AccessLogFilters) {
  return useQuery({
    queryKey: ["salary", "access-logs", filters],
    queryFn: async () => {
      const { data } = await apiClient.get<{
        items: AccessLogRow[];
        total: number;
      }>("/salary/access-logs", {
        params: { user_id: filters.userId, action: filters.action },
      });
      return data;
    },
  });
}
