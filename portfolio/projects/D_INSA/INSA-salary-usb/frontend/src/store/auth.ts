import { create } from "zustand";

interface AuthState {
  accessToken: string | null;
  userId: number | null;
  loginId: string | null;
  roles: string[];
  setAuth: (data: {
    accessToken: string;
    userId: number;
    loginId: string;
    roles: string[];
  }) => void;
  setAccessToken: (token: string) => void;
  logout: () => void;
}

export const useAuthStore = create<AuthState>((set) => ({
  accessToken: null,
  userId: null,
  loginId: null,
  roles: [],
  setAuth: (data) =>
    set({
      accessToken: data.accessToken,
      userId: data.userId,
      loginId: data.loginId,
      roles: data.roles,
    }),
  setAccessToken: (token) => set({ accessToken: token }),
  logout: () =>
    set({
      accessToken: null,
      userId: null,
      loginId: null,
      roles: [],
    }),
}));
