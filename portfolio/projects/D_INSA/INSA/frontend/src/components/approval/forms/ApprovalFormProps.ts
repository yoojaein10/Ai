export interface ApprovalFormProps {
  mode: "draft" | "view";
  initialData?: Record<string, unknown>;
  onChange?: (data: Record<string, unknown>) => void;
  readOnly?: boolean;
}
