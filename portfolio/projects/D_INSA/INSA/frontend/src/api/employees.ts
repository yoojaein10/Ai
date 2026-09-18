import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import apiClient from "./client";

export interface Employee {
  id: number;
  emp_no: string;
  name_ko: string;
  name_en?: string | null;
  gender?: string | null;
  birth_date?: string | null;
  hire_date?: string | null;
  hire_type?: string | null;
  workplace?: string | null;
  work_location?: string | null;
  dept_id?: number | null;
  department_name: string | null;
  job_rank: string | null;
  job_position?: string | null;
  job_title?: string | null;
  emp_status: string;
  emp_type?: string | null;
  resign_date?: string | null;
}

interface EmployeeListResponse {
  items: Employee[];
  total: number;
  page: number;
  page_size: number;
}

interface EmployeeListParams {
  page?: number;
  page_size?: number;
  search?: string;
  dept_id?: number;
  emp_status?: string;
}

export function useEmployees(params: EmployeeListParams = {}) {
  return useQuery({
    queryKey: ["employees", params],
    queryFn: async () => {
      const { data } = await apiClient.get<EmployeeListResponse>("/employees", {
        params,
      });
      return data;
    },
  });
}

export function useEmployee(id: number | null) {
  return useQuery({
    queryKey: ["employee", id],
    queryFn: async () => {
      const { data } = await apiClient.get(`/employees/${id}`);
      return data;
    },
    enabled: id !== null,
  });
}

export interface EmployeeUpdatePayload {
  name_ko?: string | null;
  name_cn?: string | null;
  name_en?: string | null;
  gender?: string | null;
  birth_date?: string | null;
  hire_type?: string | null;
  workplace?: string | null;
  work_location?: string | null;
  job_title?: string | null;
  emp_type?: string | null;
}

export function useUpdateEmployee(id: number | null) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (body: EmployeeUpdatePayload) => {
      const { data } = await apiClient.patch(`/employees/${id}`, body);
      return data;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["employee", id] });
      qc.invalidateQueries({ queryKey: ["employees"] });
    },
  });
}
