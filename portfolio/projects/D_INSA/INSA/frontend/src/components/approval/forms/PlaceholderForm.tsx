import { Input, Typography } from "antd";
import type { ApprovalFormProps } from "./ApprovalFormProps";

export default function PlaceholderForm({
  mode,
  initialData,
  onChange,
  readOnly,
}: ApprovalFormProps) {
  const raw =
    initialData && Object.keys(initialData).length > 0
      ? JSON.stringify(initialData, null, 2)
      : "";

  if (mode === "view" || readOnly) {
    return (
      <div>
        <Typography.Paragraph type="secondary" style={{ marginBottom: 8 }}>
          이 문서 타입의 전용 양식은 후속 단계에서 구현됩니다. 현재는 원시
          데이터만 표시합니다.
        </Typography.Paragraph>
        <Input.TextArea
          value={raw}
          readOnly
          autoSize={{ minRows: 4, maxRows: 16 }}
          style={{ fontFamily: "var(--font-mono, monospace)" }}
        />
      </div>
    );
  }

  return (
    <div>
      <Typography.Paragraph type="secondary" style={{ marginBottom: 8 }}>
        임시 양식: JSON 형식으로 자유 입력하세요. 실제 양식은 후속 단계에서
        교체됩니다.
      </Typography.Paragraph>
      <Input.TextArea
        defaultValue={raw}
        onChange={(e) => {
          try {
            const parsed = e.target.value
              ? (JSON.parse(e.target.value) as Record<string, unknown>)
              : {};
            onChange?.(parsed);
          } catch {
            // ignore parse errors while typing
          }
        }}
        autoSize={{ minRows: 6, maxRows: 20 }}
        placeholder='{\n  "sample_field": "value"\n}'
        style={{ fontFamily: "var(--font-mono, monospace)" }}
      />
    </div>
  );
}
