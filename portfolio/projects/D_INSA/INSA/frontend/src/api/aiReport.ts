import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import apiClient from "./client";

export type AiReportStatus = "PENDING" | "SUCCESS" | "FAILED";

export interface AiReportListItem {
  employee_id: number;
  employee_name: string | null;
  total_score: string | null; // Decimal serialized as string
  final_grade: string | null;
  report_id: number | null;
  version: number | null;
  status: AiReportStatus | null;
  generated_at: string | null;
  error_message: string | null;
}

export interface AiReportDetail {
  id: number;
  round_id: number;
  employee_id: number;
  version: number;
  is_latest: boolean;
  status: AiReportStatus;
  error_message: string | null;
  total_score: string | null;
  final_grade: string | null;
  multi_response_count: number | null;
  multi_included: boolean;
  content_strengths: string | null;
  content_improvements: string | null;
  content_coaching: string | null;
  content_interview_guide: string | null;
  model_version: string;
  prompt_version: string;
  generated_by: number;
  generated_at: string;
}

export interface AiReportHistoryItem {
  id: number;
  version: number;
  is_latest: boolean;
  status: AiReportStatus;
  generated_by: number;
  generated_at: string;
  model_version: string;
  prompt_version: string;
}

export interface GenerateBatchResponse {
  round_id: number;
  total: number;
  success: number;
  failed: number;
}

const BASE = "/eval/ai-reports";

export function useAiReports(roundId: number | null) {
  return useQuery({
    queryKey: ["eval", "ai-reports", { roundId }],
    queryFn: async () => {
      const { data } = await apiClient.get<AiReportListItem[]>(BASE, {
        params: { round_id: roundId },
      });
      return data;
    },
    enabled: roundId != null,
  });
}

export function useAiReportDetail(reportId: number | null) {
  return useQuery({
    queryKey: ["eval", "ai-report", reportId],
    queryFn: async () => {
      const { data } = await apiClient.get<AiReportDetail>(`${BASE}/${reportId}`);
      return data;
    },
    enabled: reportId != null,
  });
}

export function useAiReportHistory(roundId: number | null, employeeId: number | null) {
  return useQuery({
    queryKey: ["eval", "ai-report-history", { roundId, employeeId }],
    queryFn: async () => {
      const { data } = await apiClient.get<AiReportHistoryItem[]>(
        `${BASE}/employees/${employeeId}/history`,
        { params: { round_id: roundId } },
      );
      return data;
    },
    enabled: roundId != null && employeeId != null,
  });
}

export function useGenerateBatch() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (roundId: number) => {
      const { data } = await apiClient.post<GenerateBatchResponse>(`${BASE}/generate`, {
        round_id: roundId,
      });
      return data;
    },
    onSuccess: (_data, roundId) => {
      qc.invalidateQueries({ queryKey: ["eval", "ai-reports", { roundId }] });
    },
  });
}

export function useGenerateOne() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (params: { roundId: number; employeeId: number }) => {
      const { data } = await apiClient.post<AiReportDetail>(
        `${BASE}/generate/${params.employeeId}`,
        { round_id: params.roundId },
      );
      return data;
    },
    onSuccess: (_data, vars) => {
      qc.invalidateQueries({ queryKey: ["eval", "ai-reports", { roundId: vars.roundId }] });
      qc.invalidateQueries({
        queryKey: ["eval", "ai-report-history", { roundId: vars.roundId, employeeId: vars.employeeId }],
      });
    },
  });
}
