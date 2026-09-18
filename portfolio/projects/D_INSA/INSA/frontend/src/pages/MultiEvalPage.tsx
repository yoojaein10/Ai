import { useEffect, useState } from "react";
import {
  Alert,
  Breadcrumb,
  Button,
  Card,
  Empty,
  Input,
  List,
  Modal,
  Radio,
  Select,
  Space,
  Tag,
  Typography,
  message,
} from "antd";
import { useEvalRounds } from "../api/evalRounds";
import { useMultiIndicators } from "../api/multiIndicator";
import {
  useMyMultiTargets,
  useSubmitMultiResponse,
  type MyEvalTarget,
} from "../api/multiResponse";
import { useEvalUIStore } from "../store/evalUI";

const { Title, Paragraph, Text } = Typography;

interface DraftItem {
  score: number | null;
  comment: string;
}

export default function MultiEvalPage() {
  const { selectedRoundId, setSelectedRoundId } = useEvalUIStore();
  const { data: rounds } = useEvalRounds();
  const { data: targets } = useMyMultiTargets(selectedRoundId);
  const { data: indicators } = useMultiIndicators(selectedRoundId);
  const submitMutation = useSubmitMultiResponse();

  const [active, setActive] = useState<MyEvalTarget | null>(null);
  const [drafts, setDrafts] = useState<Record<number, DraftItem>>({});

  useEffect(() => {
    if (active && indicators) {
      const init: Record<number, DraftItem> = {};
      indicators.forEach((ind) => {
        init[ind.id] = { score: null, comment: "" };
      });
      setDrafts(init);
    } else {
      setDrafts({});
    }
  }, [active, indicators]);

  const handleSubmit = () => {
    if (active == null || selectedRoundId == null) return;
    const items = Object.entries(drafts)
      .filter(([, v]) => v.score != null)
      .map(([k, v]) => ({
        indicator_id: Number(k),
        score: v.score as number,
        comment: v.comment || null,
      }));
    if (items.length === 0) {
      message.warning("점수를 입력하세요");
      return;
    }
    if (items.length !== (indicators?.length ?? 0)) {
      message.warning("모든 지표에 점수를 입력하세요");
      return;
    }
    submitMutation.mutate(
      {
        round_id: selectedRoundId,
        evaluatee_id: active.evaluatee_id,
        rater_type: active.rater_type,
        items,
      },
      {
        onSuccess: () => {
          message.success("익명으로 제출되었습니다");
          setActive(null);
        },
        onError: (e: any) =>
          message.error(e?.response?.data?.detail ?? "제출 실패"),
      },
    );
  };

  return (
    <>
      <Breadcrumb
        items={[{ title: "인사평가" }, { title: "다면평가" }, { title: "입력" }]}
        style={{ marginBottom: 12 }}
      />
      <Title level={4} style={{ marginBottom: 16 }}>
        다면평가 입력
      </Title>

      <Alert
        type="info"
        showIcon
        message="익명 보장"
        description="제출된 점수는 평가자 식별 정보와 분리되어 저장됩니다. 누가 어떤 점수를 줬는지 시스템에서도 추적할 수 없습니다."
        style={{ marginBottom: 12 }}
      />

      <Card size="small" style={{ marginBottom: 12 }}>
        <Space>
          <Select
            style={{ width: 280 }}
            placeholder="회차 선택"
            value={selectedRoundId ?? undefined}
            options={(rounds ?? []).map((r) => ({
              value: r.id,
              label: `${r.year} · ${r.name}`,
            }))}
            onChange={setSelectedRoundId}
          />
        </Space>
      </Card>

      {(targets ?? []).length === 0 ? (
        <Empty description="평가할 대상이 없습니다" />
      ) : (
        <List
          grid={{ gutter: 12, column: 3 }}
          dataSource={targets ?? []}
          renderItem={(t) => (
            <List.Item key={`${t.evaluatee_id}-${t.rater_type}`}>
              <Card
                size="small"
                title={
                  <Space>
                    <span>{t.evaluatee_name}</span>
                    <Text type="secondary">{t.evaluatee_emp_no}</Text>
                  </Space>
                }
                extra={<Tag>{t.rater_type}</Tag>}
              >
                {t.submitted ? (
                  <Tag color="success">제출 완료</Tag>
                ) : (
                  <Button type="primary" onClick={() => setActive(t)}>
                    평가 시작
                  </Button>
                )}
              </Card>
            </List.Item>
          )}
        />
      )}

      <Modal
        open={active != null}
        title={active ? `${active.evaluatee_name} 평가` : ""}
        onCancel={() => setActive(null)}
        onOk={handleSubmit}
        confirmLoading={submitMutation.isPending}
        okText="익명 제출"
        cancelText="취소"
        width={680}
      >
        <Paragraph type="secondary" style={{ marginBottom: 16 }}>
          모든 지표에 점수를 입력해야 제출됩니다. 한 번 제출하면 수정할 수 없습니다.
        </Paragraph>
        <Space direction="vertical" style={{ width: "100%" }} size="middle">
          {(indicators ?? []).map((ind) => (
            <Card key={ind.id} size="small" title={ind.name}>
              {ind.description && (
                <Paragraph type="secondary">{ind.description}</Paragraph>
              )}
              <div style={{ marginBottom: 8 }}>
                <Text>점수 (1 ~ {ind.max_score})</Text>
                <br />
                <Radio.Group
                  value={drafts[ind.id]?.score ?? null}
                  onChange={(e) =>
                    setDrafts((d) => ({
                      ...d,
                      [ind.id]: {
                        ...(d[ind.id] ?? { comment: "" }),
                        score: e.target.value,
                      },
                    }))
                  }
                >
                  {Array.from({ length: ind.max_score }, (_, i) => i + 1).map(
                    (n) => (
                      <Radio.Button key={n} value={n}>
                        {n}
                      </Radio.Button>
                    ),
                  )}
                </Radio.Group>
              </div>
              <Input.TextArea
                rows={2}
                placeholder="코멘트 (선택)"
                value={drafts[ind.id]?.comment ?? ""}
                onChange={(e) =>
                  setDrafts((d) => ({
                    ...d,
                    [ind.id]: {
                      ...(d[ind.id] ?? { score: null }),
                      comment: e.target.value,
                    },
                  }))
                }
              />
            </Card>
          ))}
        </Space>
      </Modal>
    </>
  );
}
