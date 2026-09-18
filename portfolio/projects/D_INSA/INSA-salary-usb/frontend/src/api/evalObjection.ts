import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import apiClient from "./client";

export type ObjectionStatus = "PENDING" | "REVIEWED" | "ACCEPTED" | "REJECTED";
export type ReviewDecision = "ACCEPTED" | "REJECTED";

export interface ObjectionResponse {
  id: number;
  emp_id: number;
  round_id: number;
  reason: string;
  status: ObjectionStatus;
  created_at: string;
}

export interface ObjectionCreatePayload {
  round_id: number;
  reason: string;
}

export interface ObjectionReviewPayload {
  objection_id: number;
  decision: ReviewDecision;
  comment?: string | null;
}

export function useObjections(round_id: number | null) {
  return useQuery({
    queryKey: ["eval", "objections", "list", { round_id }],
    queryFn: async () => {
      const { data } = await apiClient.get<ObjectionResponse[]>(
        "/eval/objections",
        { params: { round_id: round_id ?? undefined } },
      );
      return data;
    },
    enabled: round_id != null,
  });
}

export function useCreateObjection() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (body: ObjectionCreatePayload) => {
      const { data } = await apiClient.post<ObjectionResponse>(
        "/eval/objections",
        body,
      );
      return data;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["eval", "objections", "list"] });
    },
  });
}

export function useReviewObjection() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (payload: ObjectionReviewPayload) => {
      const { data } = await apiClient.put(
        `/eval/objections/${payload.objection_id}/review`,
        { decision: payload.decision, comment: payload.comment ?? null },
      );
      return data;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["eval", "objections", "list"] });
    },
  });
}
