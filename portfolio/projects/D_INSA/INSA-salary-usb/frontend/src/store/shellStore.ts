import { create } from "zustand";
import { persist } from "zustand/middleware";

interface ShellState {
  siderCollapsed: boolean;
  toggleSider: () => void;
  setSiderCollapsed: (v: boolean) => void;
}

export const useShellStore = create<ShellState>()(
  persist(
    (set) => ({
      siderCollapsed: false,
      toggleSider: () => set((s) => ({ siderCollapsed: !s.siderCollapsed })),
      setSiderCollapsed: (v) => set({ siderCollapsed: v }),
    }),
    { name: "insa-shell" },
  ),
);
