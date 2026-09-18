import { useState } from "react";
import {
  Breadcrumb,
  Button,
  Card,
  DatePicker,
  Empty,
  Input,
  Modal,
  Popconfirm,
  Select,
  Space,
  Timeline,
  Typography,
  message,
} from "antd";
import dayjs, { type Dayjs } from "dayjs";
import {
  useCompSarList,
  useCreateCompSar,
  useDeleteCompSar,
} from "../api/compSar";
import { useEmployees } from "../api/employees";
import { useMe } from "../api/me";

const { Title, Paragraph, Text } = Typography;

interface DraftSar {
  observed_date: Dayjs | null;
  situation: string;
  action: string;
  result: string;
}

const EMPTY: DraftSar = {
  observed_date: null,
  situation: "",
  action: "",
  result: "",
};

export default function CompSarPage() {
  const { data: me } = useMe();
  const myEmpId = me?.employee?.id ?? null;
  const { data: empList } = useEmployees({ page_size: 200 });

  const [targetEmpId, setTargetEmpId] = useState<number | null>(null);
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState<DraftSar>(EMPTY);

  const { data: sarList } = useCompSarList(targetEmpId);
  const createMutation = useCreateCompSar();
  const deleteMutation = useDeleteCompSar();

  const handleAdd = () => {
    if (targetEmpId == null) {
      message.warning("관찰 대상을 먼저 선택하세요");
      return;
    }
    if (!draft.observed_date) {
      message.warning("관찰일을 선택하세요");
      return;
    }
    createMutation.mutate(
      {
        target_emp_id: targetEmpId,
        observed_date: draft.observed_date.format("YYYY-MM-DD"),
        situation: draft.situation || null,
        action: draft.action || null,
        result: draft.result || null,
      },
      {
        onSuccess: () => {
          message.success("기록되었습니다");
          setOpen(false);
          setDraft(EMPTY);
        },
        onError: (e: any) =>
          message.error(e?.response?.data?.detail ?? "등록 실패"),
      },
    );
  };

  return (
    <>
      <Breadcrumb
        items={[
          { title: "인사평가" },
          { title: "역량평가" },
          { title: "SAR 관찰기록" },
        ]}
        style={{ marginBottom: 12 }}
      />
      <Title level={4} style={{ marginBottom: 16 }}>
        SAR 관찰기록
      </Title>

      <Card size="small" style={{ marginBottom: 12 }}>
        <Space wrap>
          <Select
            style={{ width: 320 }}
            showSearch
            placeholder="관찰 대상자 선택"
            value={targetEmpId ?? undefined}
            options={(empList?.items ?? []).map((e) => ({
              value: e.id,
              label: `${e.name_ko} (${e.emp_no})`,
            }))}
            optionFilterProp="label"
            onChange={setTargetEmpId}
          />
          <Button type="primary" onClick={() => setOpen(true)}>
            새 관찰 기록
          </Button>
        </Space>
      </Card>

      {targetEmpId == null ? (
        <Empty description="대상자를 선택하세요" />
      ) : (sarList ?? []).length === 0 ? (
        <Empty description="등록된 관찰 기록이 없습니다" />
      ) : (
        <Card size="small">
          <Timeline
            items={(sarList ?? []).map((s) => ({
              children: (
                <>
                  <Text strong>{s.observed_date}</Text>
                  {s.observer_id === myEmpId && (
                    <Popconfirm
                      title="삭제하시겠습니까?"
                      onConfirm={() =>
                        deleteMutation.mutate(s.id, {
                          onSuccess: () => message.success("삭제되었습니다"),
                          onError: (e: any) =>
                            message.error(
                              e?.response?.data?.detail ?? "삭제 실패",
                            ),
                        })
                      }
                    >
                      <Button
                        type="link"
                        size="small"
                        danger
                        style={{ marginLeft: 8 }}
                      >
                        삭제
                      </Button>
                    </Popconfirm>
                  )}
                  {s.situation && (
                    <Paragraph style={{ marginBottom: 4 }}>
                      <Text type="secondary">[Situation] </Text>
                      {s.situation}
                    </Paragraph>
                  )}
                  {s.action && (
                    <Paragraph style={{ marginBottom: 4 }}>
                      <Text type="secondary">[Action] </Text>
                      {s.action}
                    </Paragraph>
                  )}
                  {s.result && (
                    <Paragraph style={{ marginBottom: 4 }}>
                      <Text type="secondary">[Result] </Text>
                      {s.result}
                    </Paragraph>
                  )}
                </>
              ),
            }))}
          />
        </Card>
      )}

      <Modal
        open={open}
        title="새 관찰 기록 (SAR)"
        onCancel={() => setOpen(false)}
        onOk={handleAdd}
        confirmLoading={createMutation.isPending}
        okText="저장"
        cancelText="취소"
      >
        <Space direction="vertical" style={{ width: "100%" }}>
          <div>
            <Text>관찰일</Text>
            <DatePicker
              value={draft.observed_date}
              onChange={(d) => setDraft((s) => ({ ...s, observed_date: d ?? dayjs() }))}
              style={{ width: "100%" }}
            />
          </div>
          <div>
            <Text>Situation (상황)</Text>
            <Input.TextArea
              rows={3}
              value={draft.situation}
              onChange={(e) =>
                setDraft((s) => ({ ...s, situation: e.target.value }))
              }
            />
          </div>
          <div>
            <Text>Action (행동)</Text>
            <Input.TextArea
              rows={3}
              value={draft.action}
              onChange={(e) =>
                setDraft((s) => ({ ...s, action: e.target.value }))
              }
            />
          </div>
          <div>
            <Text>Result (결과)</Text>
            <Input.TextArea
              rows={3}
              value={draft.result}
              onChange={(e) =>
                setDraft((s) => ({ ...s, result: e.target.value }))
              }
            />
          </div>
        </Space>
      </Modal>
    </>
  );
}
