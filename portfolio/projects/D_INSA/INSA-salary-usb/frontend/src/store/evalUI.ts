import { create } from "zustand";

interface EvalUIState {
  selectedRoundId: number | null;
  selectedGroupId: number | null;
  selectedTargetId: number | null;
  selectedEvaluateeId: number | null;
  setSelectedRoundId: (id: number | null) => void;
  setSelectedGroupId: (id: number | null) => void;
  setSelectedTargetId: (id: number | null) => void;
  setSelectedEvaluateeId: (id: number | null) => void;
}

export const useEvalUIStore = create<EvalUIState>((set) => ({
  selectedRoundId: null,
  selectedGroupId: null,
  selectedTargetId: null,
  selectedEvaluateeId: null,
  setSelectedRoundId: (id) => set({ selectedRoundId: id }),
  setSelectedGroupId: (id) => set({ selectedGroupId: id }),
  setSelectedTargetId: (id) => set({ selectedTargetId: id }),
  setSelectedEvaluateeId: (id) => set({ selectedEvaluateeId: id }),
}));
