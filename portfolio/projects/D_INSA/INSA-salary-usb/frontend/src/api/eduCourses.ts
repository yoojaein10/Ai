import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import apiClient from "./client";

export interface EduCourse {
  id: number;
  course_code: string;
  course_name: string;
  category: string | null;
  training_type: string | null;
  hours: number | null;
  provider: string | null;
  instructor: string | null;
  description: string | null;
  is_active: boolean;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface EduCourseCreate {
  course_code: string;
  course_name: string;
  category?: string | null;
  training_type?: string | null;
  hours?: number | null;
  provider?: string | null;
  instructor?: string | null;
  description?: string | null;
  is_active?: boolean;
}

export type EduCourseUpdate = Partial<EduCourseCreate>;

export interface EduCourseListResponse {
  total: number;
  items: EduCourse[];
}

export interface EduCourseQuery {
  keyword?: string;
  category?: string;
  is_active?: boolean;
}

export function useEduCourses(q: EduCourseQuery = {}) {
  return useQuery({
    queryKey: ["edu-courses", q],
    queryFn: async () => {
      const { data } = await apiClient.get<EduCourseListResponse>(
        "/edu/courses",
        {
          params: {
            keyword: q.keyword || undefined,
            category: q.category || undefined,
            is_active: q.is_active,
          },
        }
      );
      return data;
    },
  });
}

export function useCreateEduCourse() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (data: EduCourseCreate) => {
      const { data: res } = await apiClient.post<EduCourse>(
        "/edu/courses",
        data
      );
      return res;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["edu-courses"] });
    },
  });
}

export function useUpdateEduCourse() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({
      id,
      data,
    }: {
      id: number;
      data: EduCourseUpdate;
    }) => {
      const { data: res } = await apiClient.patch<EduCourse>(
        `/edu/courses/${id}`,
        data
      );
      return res;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["edu-courses"] });
    },
  });
}

export function useDeleteEduCourse() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (id: number) => {
      await apiClient.delete(`/edu/courses/${id}`);
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["edu-courses"] });
    },
  });
}
