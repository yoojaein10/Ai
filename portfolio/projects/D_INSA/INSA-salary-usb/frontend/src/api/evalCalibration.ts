import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import apiClient from "./client";

export interface CalibrationMember {
  id: number;
  emp_id: number;
  emp_no: string | null;
  emp_name: string | null;
}

export interface CalibrationGroup {
  id: number;
  year: number;
  name: string;
  created_by: number;
  created_at: string | null;
  member_count: number;
}

export interface CalibrationGroupDetail extends CalibrationGroup {
  members: CalibrationMember[];
}

export function useCalibrationGroups(year?: number) {
  return useQuery({
    queryKey: ["eval", "calibration", "groups", { year }],
    queryFn: async () => {
      const { data } = await apiClient.get<CalibrationGroup[]>(
        "/eval/calibration-groups",
        { params: year ? { year } : {} },
      );
      return data;
    },
  });
}

export function useCalibrationGroup(id: number | null) {
  return useQuery({
    queryKey: ["eval", "calibration", "group", id],
    queryFn: async () => {
      const { data } = await apiClient.get<CalibrationGroupDetail>(
        `/eval/calibration-groups/${id}`,
      );
      return data;
    },
    enabled: id !== null,
  });
}

export function useCreateCalibrationGroup() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (body: { year: number; name: string }) => {
      const { data } = await apiClient.post<CalibrationGroup>(
        "/eval/calibration-groups",
        body,
      );
      return data;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["eval", "calibration", "groups"] });
    },
  });
}

export function useUpdateCalibrationGroup(id: number | null) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (body: { name: string }) => {
      const { data } = await apiClient.put<CalibrationGroupDetail>(
        `/eval/calibration-groups/${id}`,
        body,
      );
      return data;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["eval", "calibration"] });
    },
  });
}

export function useAddCalibrationMembers(groupId: number | null) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (emp_ids: number[]) => {
      const { data } = await apiClient.post<{ added: number }>(
        `/eval/calibration-groups/${groupId}/members`,
        { emp_ids },
      );
      return data;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["eval", "calibration"] });
    },
  });
}

export function useRemoveCalibrationMember(groupId: number | null) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (empId: number) => {
      await apiClient.delete(
        `/eval/calibration-groups/${groupId}/members/${empId}`,
      );
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["eval", "calibration"] });
    },
  });
}
