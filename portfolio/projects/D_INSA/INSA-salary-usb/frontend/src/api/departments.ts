import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import apiClient from "./client";

export interface Department {
  id: number;
  code: string;
  name: string;
  parent_id: number | null;
  head_employee_id: number | null;
  is_active: boolean;
}

export interface DepartmentTreeNode extends Department {
  children: DepartmentTreeNode[];
}

export function useDepartments(includeInactive = false) {
  return useQuery({
    queryKey: ["departments", includeInactive],
    queryFn: async () => {
      const { data } = await apiClient.get<Department[]>("/departments", {
        params: { include_inactive: includeInactive },
      });
      return data;
    },
  });
}

export function useDepartmentTree() {
  return useQuery({
    queryKey: ["departments", "tree"],
    queryFn: async () => {
      const { data } = await apiClient.get<DepartmentTreeNode[]>(
        "/departments/tree"
      );
      return data;
    },
  });
}

export function useCreateDepartment() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (body: { code: string; name: string; parent_id?: number | null }) => {
      const { data } = await apiClient.post<Department>("/departments", body);
      return data;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["departments"] });
    },
  });
}

export function useUpdateDepartment() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ id, ...body }: { id: number; name?: string; parent_id?: number | null; is_active?: boolean; head_employee_id?: number | null }) => {
      const { data } = await apiClient.patch<Department>(`/departments/${id}`, body);
      return data;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["departments"] });
    },
  });
}

export function useDeleteDepartment() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (id: number) => {
      const { data } = await apiClient.delete<{ message: string }>(`/departments/${id}`);
      return data;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["departments"] });
    },
  });
}
