import { beforeEach, describe, expect, it } from "vitest";
import { useApprovalUIStore } from "../approvalUI";

const reset = () =>
  useApprovalUIStore.setState({
    selectedDocId: null,
    actionMode: null,
    actionComment: "",
  });

describe("approvalUI store", () => {
  beforeEach(() => {
    reset();
  });

  it("has empty initial state", () => {
    const s = useApprovalUIStore.getState();
    expect(s.selectedDocId).toBeNull();
    expect(s.actionMode).toBeNull();
    expect(s.actionComment).toBe("");
  });

  it("openAction records mode, docId, and clears comment", () => {
    const { openAction, setActionComment } = useApprovalUIStore.getState();
    setActionComment("leftover");
    openAction("approve", 42);
    const s = useApprovalUIStore.getState();
    expect(s.actionMode).toBe("approve");
    expect(s.selectedDocId).toBe(42);
    expect(s.actionComment).toBe("");
  });

  it("closeAction clears mode and comment but keeps selectedDocId", () => {
    const { openAction, setActionComment, closeAction } =
      useApprovalUIStore.getState();
    openAction("reject", 7);
    setActionComment("사유");
    closeAction();
    const s = useApprovalUIStore.getState();
    expect(s.actionMode).toBeNull();
    expect(s.actionComment).toBe("");
    expect(s.selectedDocId).toBe(7);
  });

  it("setActionComment updates only the comment field", () => {
    const { openAction, setActionComment } = useApprovalUIStore.getState();
    openAction("approve", 1);
    setActionComment("검토 완료");
    const s = useApprovalUIStore.getState();
    expect(s.actionComment).toBe("검토 완료");
    expect(s.actionMode).toBe("approve");
  });

  it("setSelectedDocId can set and clear", () => {
    const { setSelectedDocId } = useApprovalUIStore.getState();
    setSelectedDocId(99);
    expect(useApprovalUIStore.getState().selectedDocId).toBe(99);
    setSelectedDocId(null);
    expect(useApprovalUIStore.getState().selectedDocId).toBeNull();
  });
});
