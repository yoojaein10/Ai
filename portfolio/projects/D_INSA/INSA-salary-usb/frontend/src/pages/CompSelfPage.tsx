import { useEffect, useMemo, useState } from "react";
import {
  Breadcrumb,
  Button,
  Card,
  Collapse,
  Empty,
  Input,
  InputNumber,
  Select,
  Space,
  Tag,
  Typography,
  message,
} from "antd";
import { useCompIndicators } from "../api/compIndicator";
import {
  useMyCompEval,
  useSubmitCompSelf,
  type CompEvalSelfItem,
} from "../api/compMyEval";
import { useEvalRounds } from "../api/evalRounds";
import { useEvalUIStore } from "../store/evalUI";

const { Title, Paragraph, Text } = Typography;

interface DraftItem {
  score: number | null;
  comment: string;
}

export default function CompSelfPage() {
  const { selectedRoundId, setSelectedRoundId } = useEvalUIStore();
  const { data: rounds } = useEvalRounds();
  const currentYear = useMemo(() => {
    const r = (rounds ?? []).find((x) => x.id === selectedRoundId);
    return r?.year ?? null;
  }, [rounds, selectedRoundId]);

  const { data: indicators } = useCompIndicators(currentYear);
  const { data: existing } = useMyCompEval(selectedRoundId);
  const submitMutation = useSubmitCompSelf();

  const [drafts, setDrafts] = useState<Record<number, DraftItem>>({});

  useEffect(() => {
    const next: Record<number, DraftItem> = {};
    (indicators ?? []).forEach((ind) => {
      const prev = (existing ?? []).find((e) => e.indicator_id === ind.id);
      next[ind.id] = {
        score: prev?.score ?? null,
        comment: prev?.comment ?? "",
      };
    });
    setDrafts(next);
  }, [indicators, existing]);

  const setScore = (id: number, score: number | null) => {
    setDrafts((d) => ({ ...d, [id]: { ...(d[id] ?? { comment: "" }), score } }));
  };
  const setComment = (id: number, comment: string) => {
    setDrafts((d) => ({ ...d, [id]: { ...(d[id] ?? { score: null }), comment } }));
  };

  const handleSubmit = () => {
    if (selectedRoundId == null) return;
    const items: CompEvalSelfItem[] = Object.entries(drafts)
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
    submitMutation.mutate(
      { round_id: selectedRoundId, items },
      {
        onSuccess: () => message.success("저장되었습니다"),
        onError: (e: any) =>
          message.error(e?.response?.data?.detail ?? "저장 실패"),
      },
    );
  };

  return (
    <>
      <Breadcrumb
        items={[{ title: "인사평가" }, { title: "역량평가" }, { title: "본인평가" }]}
        style={{ marginBottom: 12 }}
      />
      <Title level={4} style={{ marginBottom: 16 }}>
        본인평가
      </Title>

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

      {(indicators ?? []).length === 0 ? (
        <Empty description="역량 지표가 등록되지 않았습니다" />
      ) : (
        <Card size="small">
          <Collapse
            items={(indicators ?? []).map((ind) => ({
              key: String(ind.id),
              label: (
                <Space>
                  <Text strong>{ind.code}</Text>
                  <span>{ind.name}</span>
                  {drafts[ind.id]?.score != null && (
                    <Tag color="blue">점수 {drafts[ind.id]?.score}</Tag>
                  )}
                </Space>
              ),
              children: (
                <>
                  {ind.description && (
                    <Paragraph type="secondary">{ind.description}</Paragraph>
                  )}
                  {ind.behaviors.length > 0 && (
                    <Card size="small" style={{ marginBottom: 12 }} title="행동지표">
                      {ind.behaviors
                        .slice()
                        .sort((a, b) => a.level - b.level)
                        .map((b) => (
                          <div key={b.id} style={{ marginBottom: 4 }}>
                            <Tag>L{b.level}</Tag> {b.description}
                          </div>
                        ))}
                    </Card>
                  )}
                  <Space direction="vertical" style={{ width: "100%" }}>
                    <div>
                      <Text>점수 (1~5)</Text>
                      <br />
                      <InputNumber
                        min={1}
                        max={5}
                        value={drafts[ind.id]?.score ?? null}
                        onChange={(v) => setScore(ind.id, v as number | null)}
                        style={{ width: 120 }}
                      />
                    </div>
                    <div>
                      <Text>코멘트</Text>
                      <Input.TextArea
                        rows={3}
                        value={drafts[ind.id]?.comment ?? ""}
                        onChange={(e) => setComment(ind.id, e.target.value)}
                      />
                    </div>
                  </Space>
                </>
              ),
            }))}
          />
          <div style={{ marginTop: 16, textAlign: "right" }}>
            <Button
              type="primary"
              loading={submitMutation.isPending}
              onClick={handleSubmit}
            >
              저장
            </Button>
          </div>
        </Card>
      )}
    </>
  );
}
