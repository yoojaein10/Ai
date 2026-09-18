import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import apiClient from "./client";

export interface PolicyCheck {
  allowed: boolean;
  current_ip: string | null;
  login_id?: string | null;
  /** 이 사용자에게 수동 허용 정책이 있는지 */
  configured: boolean;
  /** 좌석(SEAT_USERINFO) 규칙으로 계산한 기대 IP. 매핑 없으면 null */
  seat_expected_ip?: string | null;
  /** 통과 경로: "seat" | "manual" | null(거부) */
  via?: "seat" | "manual" | null;
  reason: string | null;
}

export interface PolicyRow {
  id: number;
  owner_user_id: number;
  allowed_ip: string;
  is_active: boolean;
  updated_by: number;
  updated_at: string;
}

/**
 * 접속 자리 판정은 서버가 한다(좌석 규칙 OR 수동 허용). 서버에 닿지 못하면
 * 허용이 아니라 거부로 취급한다(fail-closed) — 판정을 못 받은 채 비밀번호
 * 입력창을 열어주면 IP 제한이 무의미해진다.
 */
export async function checkPolicy(): Promise<PolicyCheck> {
  try {
    const { data } = await apiClient.get<PolicyCheck>("/salary/policy/check");
    return data;
  } catch (error) {
    console.error("IP 정책 확인에 실패했습니다:", error);
    return {
      allowed: false,
      current_ip: null,
      configured: false,
      via: null,
      reason: "접속 위치를 확인할 수 없습니다. 서버 연결을 확인한 뒤 다시 시도하세요.",
    };
  }
}

export function usePolicyCheck() {
  return useQuery({
    queryKey: ["salary", "policy", "check"],
    queryFn: checkPolicy,
    staleTime: 0,
  });
}

export function usePolicy() {
  return useQuery({
    queryKey: ["salary", "policy"],
    queryFn: async () => {
      const { data } = await apiClient.get<PolicyRow | null>("/salary/policy");
      return data;
    },
  });
}

export function useUpsertPolicy() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (input: { owner_user_id: number; allowed_ip: string }) => {
      const { data } = await apiClient.put<PolicyRow>("/salary/policy", input);
      return data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["salary", "policy"] });
    },
  });
}
