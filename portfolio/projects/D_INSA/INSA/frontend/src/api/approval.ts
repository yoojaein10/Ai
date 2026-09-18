import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import apiClient from "./client";

export type DocCategory = "HR" | "ATTENDANCE" | "TRAVEL" | "CONTRACT" | "OTHER";
export type ApproverType =
  | "USER"
  | "ROLE"
  | "POSITION"
  | "DEPT_HEAD"
  | "DIRECT_MANAGER";
export type Scope = "GLOBAL" | "DEPT";
export type DocStatus =
  | "DRAFT"
  | "PENDING"
  | "IN_PROGRESS"
  | "APPROVED"
  | "REJECTED"
  | "RECALLED";
export type HistoryAction =
  | "PENDING"
  | "APPROVED"
  | "REJECTED"
  | "DELEGATED"
  | "COMMENTED"
  | "RECALLED";

export interface DocType {
  id: number;
  code: string;
  name: string;
  category: DocCategory;
  description: string | null;
  is_active: boolean;
  created_at: string;
}

export interface LineStep {
  id: number;
  template_id: number;
  step_order: number;
  approver_type: ApproverType;
  approver_ref: string | null;
  is_required: boolean;
}

export interface LineTemplate {
  id: number;
  doc_type_id: number;
  name: string;
  scope: Scope;
  scope_ref: number | null;
  is_default: boolean;
  created_at: string;
  steps: LineStep[];
}

export interface DocListItem {
  id: number;
  doc_type_id: number;
  doc_type_code: string | null;
  doc_type_name: string | null;
  doc_no: string | null;
  title: string;
  drafter_id: number;
  drafter_name: string | null;
  status: DocStatus;
  current_step: number;
  total_steps: number;
  drafted_at: string;
  completed_at: string | null;
}

export interface DocLineStepView {
  step_order: number;
  approver_type: ApproverType;
  approver_ref: string | null;
  resolved_user_id: number | null;
  resolved_name: string | null;
  is_required: boolean;
}

export interface DocHistoryItem {
  id: number;
  step_order: number;
  approver_id: number;
  approver_name: string | null;
  action: HistoryAction;
  comment: string | null;
  acted_at: string;
}

export interface DocDetail extends DocListItem {
  content: Record<string, unknown> | null;
  line_steps: DocLineStepView[];
  history: DocHistoryItem[];
}

export interface CreateDocBody {
  doc_type_id: number;
  title: string;
  content: Record<string, unknown> | null;
  line_template_id: number;
}

export interface UpdateDocBody {
  title?: string;
  content?: Record<string, unknown> | null;
}

export interface LineStepCreateBody {
  step_order: number;
  approver_type: ApproverType;
  approver_ref: string | null;
  is_required: boolean;
}

export interface CreateTemplateBody {
  doc_type_id: number;
  name: string;
  scope: Scope;
  scope_ref: number | null;
  is_default: boolean;
  steps: LineStepCreateBody[];
}

export interface UpdateTemplateBody {
  name?: string;
  scope?: Scope;
  scope_ref?: number | null;
  is_default?: boolean;
  steps?: LineStepCreateBody[];
}

// ── Queries ───────────────────────────────────────────────

export function useDocTypes(activeOnly = true) {
  return useQuery({
    queryKey: ["approval", "doc-types", activeOnly],
    queryFn: async () => {
      const { data } = await apiClient.get<DocType[]>("/approval/doc-types", {
        params: { active_only: activeOnly },
      });
      return data;
    },
  });
}

export function useLineTemplates(docTypeId?: number) {
  return useQuery({
    queryKey: ["approval", "lines", docTypeId ?? "all"],
    queryFn: async () => {
      const { data } = await apiClient.get<LineTemplate[]>("/approval/lines", {
        params: docTypeId ? { doc_type_id: docTypeId } : {},
      });
      return data;
    },
  });
}

export function useInbox(statusFilter?: DocStatus | "") {
  return useQuery({
    queryKey: ["approval", "inbox", statusFilter ?? "active"],
    queryFn: async () => {
      const { data } = await apiClient.get<DocListItem[]>(
        "/approval/docs/inbox",
        { params: statusFilter ? { status_filter: statusFilter } : {} },
      );
      return data;
    },
  });
}

export function useInboxCount() {
  return useQuery({
    queryKey: ["approval", "inbox-count"],
    queryFn: async () => {
      const { data } = await apiClient.get<{ count: number }>(
        "/approval/docs/inbox/count",
      );
      return data.count;
    },
    refetchInterval: 60_000,
  });
}

export function useDrafts(statusFilter?: DocStatus | "") {
  return useQuery({
    queryKey: ["approval", "drafts", statusFilter ?? "all"],
    queryFn: async () => {
      const { data } = await apiClient.get<DocListItem[]>(
        "/approval/docs/drafts",
        { params: statusFilter ? { status_filter: statusFilter } : {} },
      );
      return data;
    },
  });
}

export function useDocDetail(docId: number | null) {
  return useQuery({
    queryKey: ["approval", "doc", docId],
    queryFn: async () => {
      const { data } = await apiClient.get<DocDetail>(
        `/approval/docs/${docId}`,
      );
      return data;
    },
    enabled: docId !== null,
  });
}

// ── Mutations ─────────────────────────────────────────────

function invalidateApproval(qc: ReturnType<typeof useQueryClient>) {
  qc.invalidateQueries({ queryKey: ["approval"] });
}

export function useCreateDocMutation() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (body: CreateDocBody) => {
      const { data } = await apiClient.post<DocListItem>(
        "/approval/docs",
        body,
      );
      return data;
    },
    onSuccess: () => invalidateApproval(qc),
  });
}

export function useUpdateDocMutation() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ id, body }: { id: number; body: UpdateDocBody }) => {
      const { data } = await apiClient.put<DocListItem>(
        `/approval/docs/${id}`,
        body,
      );
      return data;
    },
    onSuccess: () => invalidateApproval(qc),
  });
}

export function useSubmitDocMutation() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (id: number) => {
      const { data } = await apiClient.post<DocListItem>(
        `/approval/docs/${id}/submit`,
      );
      return data;
    },
    onSuccess: () => invalidateApproval(qc),
  });
}

export function useApproveStepMutation() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ id, comment }: { id: number; comment?: string }) => {
      const { data } = await apiClient.post<DocListItem>(
        `/approval/docs/${id}/approve`,
        { comment: comment ?? null },
      );
      return data;
    },
    onSuccess: () => invalidateApproval(qc),
  });
}

export function useRejectStepMutation() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ id, comment }: { id: number; comment?: string }) => {
      const { data } = await apiClient.post<DocListItem>(
        `/approval/docs/${id}/reject`,
        { comment: comment ?? null },
      );
      return data;
    },
    onSuccess: () => invalidateApproval(qc),
  });
}

export function useRecallDocMutation() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (id: number) => {
      const { data } = await apiClient.post<DocListItem>(
        `/approval/docs/${id}/recall`,
      );
      return data;
    },
    onSuccess: () => invalidateApproval(qc),
  });
}

export function useCreateTemplateMutation() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (body: CreateTemplateBody) => {
      const { data } = await apiClient.post<LineTemplate>(
        "/approval/lines",
        body,
      );
      return data;
    },
    onSuccess: () => invalidateApproval(qc),
  });
}

export function useUpdateTemplateMutation() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({
      id,
      body,
    }: {
      id: number;
      body: UpdateTemplateBody;
    }) => {
      const { data } = await apiClient.put<LineTemplate>(
        `/approval/lines/${id}`,
        body,
      );
      return data;
    },
    onSuccess: () => invalidateApproval(qc),
  });
}

export function useDeleteTemplateMutation() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (id: number) => {
      await apiClient.delete(`/approval/lines/${id}`);
    },
    onSuccess: () => invalidateApproval(qc),
  });
}

export function useCreateDocTypeMutation() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (body: {
      code: string;
      name: string;
      category: DocCategory;
      description?: string | null;
      is_active?: boolean;
    }) => {
      const { data } = await apiClient.post<DocType>(
        "/approval/doc-types",
        body,
      );
      return data;
    },
    onSuccess: () => invalidateApproval(qc),
  });
}

export function useUpdateDocTypeMutation() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({
      id,
      body,
    }: {
      id: number;
      body: {
        name?: string;
        category?: DocCategory;
        description?: string | null;
        is_active?: boolean;
      };
    }) => {
      const { data } = await apiClient.put<DocType>(
        `/approval/doc-types/${id}`,
        body,
      );
      return data;
    },
    onSuccess: () => invalidateApproval(qc),
  });
}
