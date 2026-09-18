import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import apiClient from "./client";

export interface Notification {
  id: number;
  type: string;
  title: string;
  message: string | null;
  link: string | null;
  is_read: boolean;
  created_at: string;
}

export interface NotificationListResponse {
  items: Notification[];
  total: number;
  unread: number;
}

export interface UnreadCountResponse {
  unread: number;
}

const KEYS = {
  list: ["notifications", "list"] as const,
  unreadCount: ["notifications", "unread-count"] as const,
};

export function useNotifications(limit = 20) {
  return useQuery({
    queryKey: [...KEYS.list, limit],
    queryFn: async () => {
      const { data } = await apiClient.get<NotificationListResponse>(
        "/notifications/me",
        { params: { limit } }
      );
      return data;
    },
  });
}

export function useUnreadCount(pollMs = 60000) {
  return useQuery({
    queryKey: KEYS.unreadCount,
    queryFn: async () => {
      const { data } = await apiClient.get<UnreadCountResponse>(
        "/notifications/unread-count"
      );
      return data;
    },
    refetchInterval: pollMs,
    refetchOnWindowFocus: true,
  });
}

export function useMarkRead() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (id: number) => {
      const { data } = await apiClient.post<Notification>(
        `/notifications/${id}/read`
      );
      return data;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["notifications"] });
    },
  });
}

export function useMarkAllRead() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async () => {
      const { data } = await apiClient.post<UnreadCountResponse>(
        "/notifications/read-all"
      );
      return data;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["notifications"] });
    },
  });
}
