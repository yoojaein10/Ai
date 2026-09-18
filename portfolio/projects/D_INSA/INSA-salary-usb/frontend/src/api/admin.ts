import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import apiClient from "./client";

// ── Users ─────────────────────────────────────────────────

export interface AdminUser {
  id: number;
  login_id: string;
  employee_id: number | null;
  emp_no: string | null;
  name_ko: string | null;
  dept_name: string | null;
  is_active: boolean;
  role_codes: string[];
  role_names: string[];
  created_at?: string | null;
  updated_at?: string | null;
}

export interface AdminUserCreate {
  login_id: string;
  password: string;
  employee_id?: number | null;
  is_active?: boolean;
  role_ids?: number[];
}

export interface AdminUserUpdate {
  employee_id?: number | null;
  is_active?: boolean;
  role_ids?: number[];
}

export interface AdminUserListResponse {
  total: number;
  items: AdminUser[];
}

export function useAdminUsers(q: { keyword?: string; is_active?: boolean } = {}) {
  return useQuery({
    queryKey: ["admin-users", q],
    queryFn: async () => {
      const { data } = await apiClient.get<AdminUserListResponse>(
        "/admin/users",
        { params: { keyword: q.keyword || undefined, is_active: q.is_active } }
      );
      return data;
    },
  });
}

export function useCreateAdminUser() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (data: AdminUserCreate) => {
      const { data: res } = await apiClient.post<AdminUser>(
        "/admin/users",
        data
      );
      return res;
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["admin-users"] }),
  });
}

export function useUpdateAdminUser() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ id, data }: { id: number; data: AdminUserUpdate }) => {
      const { data: res } = await apiClient.patch<AdminUser>(
        `/admin/users/${id}`,
        data
      );
      return res;
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["admin-users"] }),
  });
}

export function useResetPassword() {
  return useMutation({
    mutationFn: async ({
      id,
      new_password,
    }: {
      id: number;
      new_password: string;
    }) => {
      await apiClient.post(`/admin/users/${id}/reset-password`, {
        new_password,
      });
    },
  });
}

export function useDeleteAdminUser() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (id: number) => {
      await apiClient.delete(`/admin/users/${id}`);
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["admin-users"] }),
  });
}

// ── Roles ─────────────────────────────────────────────────

export interface AdminRole {
  id: number;
  code: string;
  name: string;
  description: string | null;
  user_count: number;
  menu_ids: number[];
}

export interface AdminRoleCreate {
  code: string;
  name: string;
  description?: string | null;
  menu_ids?: number[];
}

export interface AdminRoleUpdate {
  name?: string;
  description?: string | null;
  menu_ids?: number[];
}

export interface AdminRoleListResponse {
  total: number;
  items: AdminRole[];
}

export function useAdminRoles() {
  return useQuery({
    queryKey: ["admin-roles"],
    queryFn: async () => {
      const { data } = await apiClient.get<AdminRoleListResponse>(
        "/admin/roles"
      );
      return data;
    },
  });
}

export function useCreateAdminRole() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (data: AdminRoleCreate) => {
      const { data: res } = await apiClient.post<AdminRole>(
        "/admin/roles",
        data
      );
      return res;
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["admin-roles"] }),
  });
}

export function useUpdateAdminRole() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ id, data }: { id: number; data: AdminRoleUpdate }) => {
      const { data: res } = await apiClient.patch<AdminRole>(
        `/admin/roles/${id}`,
        data
      );
      return res;
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["admin-roles"] }),
  });
}

export function useDeleteAdminRole() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (id: number) => {
      await apiClient.delete(`/admin/roles/${id}`);
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["admin-roles"] }),
  });
}

export interface AdminMenu {
  id: number;
  code: string;
  name: string;
  parent_id: number | null;
  path: string | null;
  sort_order: number;
  is_active: boolean;
}

export function useAdminMenus() {
  return useQuery({
    queryKey: ["admin-menus"],
    queryFn: async () => {
      const { data } = await apiClient.get<{ total: number; items: AdminMenu[] }>(
        "/admin/menus"
      );
      return data;
    },
  });
}

// ── Codes ─────────────────────────────────────────────────

export interface AdminCode {
  id: number;
  group_code: string;
  group_name: string | null;
  code: string;
  name: string;
  description: string | null;
  sort_order: number;
  is_active: boolean;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface AdminCodeCreate {
  group_code: string;
  group_name?: string | null;
  code: string;
  name: string;
  description?: string | null;
  sort_order?: number;
  is_active?: boolean;
}

export interface AdminCodeUpdate {
  group_name?: string | null;
  name?: string;
  description?: string | null;
  sort_order?: number;
  is_active?: boolean;
}

export interface AdminCodeGroup {
  group_code: string;
  group_name: string | null;
  count: number;
}

export function useAdminCodeGroups() {
  return useQuery({
    queryKey: ["admin-code-groups"],
    queryFn: async () => {
      const { data } = await apiClient.get<{ groups: AdminCodeGroup[] }>(
        "/admin/codes/groups"
      );
      return data;
    },
  });
}

export function useAdminCodes(
  q: { group_code?: string; is_active?: boolean; keyword?: string } = {}
) {
  return useQuery({
    queryKey: ["admin-codes", q],
    queryFn: async () => {
      const { data } = await apiClient.get<{
        total: number;
        items: AdminCode[];
      }>("/admin/codes", {
        params: {
          group_code: q.group_code || undefined,
          is_active: q.is_active,
          keyword: q.keyword || undefined,
        },
      });
      return data;
    },
  });
}

export function useCreateAdminCode() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (data: AdminCodeCreate) => {
      const { data: res } = await apiClient.post<AdminCode>(
        "/admin/codes",
        data
      );
      return res;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin-codes"] });
      qc.invalidateQueries({ queryKey: ["admin-code-groups"] });
    },
  });
}

export function useUpdateAdminCode() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ id, data }: { id: number; data: AdminCodeUpdate }) => {
      const { data: res } = await apiClient.patch<AdminCode>(
        `/admin/codes/${id}`,
        data
      );
      return res;
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["admin-codes"] }),
  });
}

export function useDeleteAdminCode() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (id: number) => {
      await apiClient.delete(`/admin/codes/${id}`);
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin-codes"] });
      qc.invalidateQueries({ queryKey: ["admin-code-groups"] });
    },
  });
}

// ── Settings ──────────────────────────────────────────────

export interface AdminSetting {
  id: number;
  key: string;
  value: string | null;
  category: string | null;
  name: string | null;
  description: string | null;
  value_type: string;
  is_editable: boolean;
  updated_at?: string | null;
}

export interface AdminSettingCreate {
  key: string;
  value?: string | null;
  category?: string | null;
  name?: string | null;
  description?: string | null;
  value_type?: string;
  is_editable?: boolean;
}

export interface AdminSettingUpdate {
  value?: string | null;
  name?: string | null;
  description?: string | null;
  category?: string | null;
}

export function useAdminSettings(category?: string) {
  return useQuery({
    queryKey: ["admin-settings", category],
    queryFn: async () => {
      const { data } = await apiClient.get<{
        total: number;
        items: AdminSetting[];
      }>("/admin/settings", { params: { category } });
      return data;
    },
  });
}

export function useCreateAdminSetting() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (data: AdminSettingCreate) => {
      const { data: res } = await apiClient.post<AdminSetting>(
        "/admin/settings",
        data
      );
      return res;
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["admin-settings"] }),
  });
}

export function useUpdateAdminSetting() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({
      id,
      data,
    }: {
      id: number;
      data: AdminSettingUpdate;
    }) => {
      const { data: res } = await apiClient.patch<AdminSetting>(
        `/admin/settings/${id}`,
        data
      );
      return res;
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["admin-settings"] }),
  });
}

export function useDeleteAdminSetting() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (id: number) => {
      await apiClient.delete(`/admin/settings/${id}`);
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["admin-settings"] }),
  });
}
