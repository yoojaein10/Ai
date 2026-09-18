import { create } from "zustand";

type ActionMode = "approve" | "reject" | null;

interface ApprovalUIState {
  selectedDocId: number | null;
  actionMode: ActionMode;
  actionComment: string;
  setSelectedDocId: (id: number | null) => void;
  openAction: (mode: Exclude<ActionMode, null>, docId: number) => void;
  closeAction: () => void;
  setActionComment: (v: string) => void;
}

export const useApprovalUIStore = create<ApprovalUIState>((set) => ({
  selectedDocId: null,
  actionMode: null,
  actionComment: "",
  setSelectedDocId: (id) => set({ selectedDocId: id }),
  openAction: (mode, docId) =>
    set({ actionMode: mode, selectedDocId: docId, actionComment: "" }),
  closeAction: () => set({ actionMode: null, actionComment: "" }),
  setActionComment: (v) => set({ actionComment: v }),
}));
