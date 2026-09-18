import { useQuery } from "@tanstack/react-query";
import apiClient from "./client";

export interface MeResponse {
  user_id: number;
  login_id: string;
  roles: string[];
  employee?: {
    id: number;
    emp_no: string;
    name_ko: string;
    department: string | null;
    job_rank: string | null;
    job_position: string | null;
  };
}

export function useMe() {
  return useQuery({
    queryKey: ["me"],
    queryFn: async () => {
      const { data } = await apiClient.get<MeResponse>("/me");
      return data;
    },
  });
}
