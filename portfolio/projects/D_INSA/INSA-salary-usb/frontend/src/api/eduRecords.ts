import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import apiClient from "./client";

export interface EduRecord {
  id: number;
  employee_id: number;
  emp_no: string | null;
  emp_name: string | null;
  dept_name: string | null;
  course_id: number | null;
  course_code: string | null;
  course_name_snapshot: string;
  category: string | null;
  start_date: string | null;
  end_date: string | null;
  hours: number | null;
  score: number | null;
  result: string | null;
  certificate_no: string | null;
  remark: string | null;
}

export interface EduRecordCreate {
  employee_id: number;
  course_id?: number | null;
  course_name_snapshot: string;
  start_date?: string | null;
  end_date?: string | null;
  hours?: number | null;
  score?: number | null;
  result?: string | null;
  certificate_no?: string | null;
  remark?: string | null;
}

export type EduRecordUpdate = Partial<Omit<EduRecordCreate, "employee_id">>;

export interface EduRecordListResponse {
  total: number;
  items: EduRecord[];
}

export interface EduRecordQuery {
  year?: number;
  employee_id?: number;
  course_id?: number;
  category?: string;
  keyword?: string;
}

export interface EduRecordUploadResult {
  created: number;
  skipped: number;
  errors: string[];
}

export function useEduRecords(q: EduRecordQuery = {}) {
  return useQuery({
    queryKey: ["edu-records", q],
    queryFn: async () => {
      const { data } = await apiClient.get<EduRecordListResponse>(
        "/edu/records",
        {
          params: {
            year: q.year,
            employee_id: q.employee_id,
            course_id: q.course_id,
            category: q.category || undefined,
            keyword: q.keyword || undefined,
          },
        }
      );
      return data;
    },
  });
}

export function useCreateEduRecord() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (data: EduRecordCreate) => {
      const { data: res } = await apiClient.post<EduRecord>(
        "/edu/records",
        data
      );
      return res;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["edu-records"] });
    },
  });
}

export function useUpdateEduRecord() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({
      id,
      data,
    }: {
      id: number;
      data: EduRecordUpdate;
    }) => {
      const { data: res } = await apiClient.patch<EduRecord>(
        `/edu/records/${id}`,
        data
      );
      return res;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["edu-records"] });
    },
  });
}

export function useDeleteEduRecord() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (id: number) => {
      await apiClient.delete(`/edu/records/${id}`);
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["edu-records"] });
    },
  });
}

export async function uploadEduRecords(file: File): Promise<EduRecordUploadResult> {
  const form = new FormData();
  form.append("file", file);
  const { data } = await apiClient.post<EduRecordUploadResult>(
    "/edu/records/upload",
    form,
    { headers: { "Content-Type": "multipart/form-data" } }
  );
  return data;
}
