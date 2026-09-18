import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import apiClient from "./client";

export interface Appointment {
  id: number;
  employee_id: number;
  appt_type: string;
  appt_date: string;
  old_dept_id: number | null;
  new_dept_id: number | null;
  old_rank: string | null;
  new_rank: string | null;
  old_position: string | null;
  new_position: string | null;
  old_title: string | null;
  new_title: string | null;
  description: string | null;
  created_at: string | null;
}

export interface AppointmentListItem {
  id: number;
  employee_id: number;
  emp_no: string | null;
  emp_name: string | null;
  appt_type: string;
  appt_date: string;
  old_dept_name: string | null;
  new_dept_name: string | null;
  old_rank: string | null;
  new_rank: string | null;
  old_position: string | null;
  new_position: string | null;
  description: string | null;
  created_at: string | null;
}

export interface AppointmentListParams {
  appt_type?: string;
  date_from?: string;
  date_to?: string;
  search?: string;
}

export function useAllAppointments(params: AppointmentListParams = {}) {
  return useQuery({
    queryKey: ["appointments", "all", params],
    queryFn: async () => {
      const { data } = await apiClient.get<AppointmentListItem[]>("/appointments", { params });
      return data;
    },
  });
}

export function useAppointmentsByEmployee(employeeId: number | null) {
  return useQuery({
    queryKey: ["appointments", employeeId],
    queryFn: async () => {
      const { data } = await apiClient.get<Appointment[]>(
        `/appointments/employee/${employeeId}`
      );
      return data;
    },
    enabled: employeeId !== null,
  });
}

export function useCreateAppointment() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (body: {
      employee_id: number;
      appt_type: string;
      appt_date: string;
      new_dept_id?: number | null;
      new_rank?: string | null;
      new_position?: string | null;
      new_title?: string | null;
      description?: string | null;
    }) => {
      const { data } = await apiClient.post<Appointment>("/appointments", body);
      return data;
    },
    onSuccess: (_data, variables) => {
      qc.invalidateQueries({ queryKey: ["appointments", variables.employee_id] });
      qc.invalidateQueries({ queryKey: ["employees"] });
      qc.invalidateQueries({ queryKey: ["employee", variables.employee_id] });
    },
  });
}
