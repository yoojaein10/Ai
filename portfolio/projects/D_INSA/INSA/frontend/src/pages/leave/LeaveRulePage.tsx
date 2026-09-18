import { useMemo, useState } from "react";
import {
  App,
  Alert,
  Button,
  Card,
  Col,
  Descriptions,
  Form,
  InputNumber,
  Modal,
  Row,
  Space,
  Switch,
  Table,
  Tag,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import { PageShell } from "../../shell/PageShell";
import {
  LeaveAccrualRule,
  LeaveType,
  useCreateRule,
  useLeaveRules,
  useLeaveTypes,
  useRunMonthly,
  useRunYearlyReset,
  useUpdateRule,
} from "../../api/leave";

function thisYear(): number {
  return new Date().getFullYear();
}

export default function LeaveRulePage() {
  const { message } = App.useApp();
  const { data: rules = [], isLoading: loadingRules } = useLeaveRules();
  const { data: types = [], isLoading: loadingTypes } = useLeaveTypes(false);
  const [editYear, setEditYear] = useState<number | null>(null);
  const [form] = Form.useForm<Partial<LeaveAccrualRule>>();

  const createMut = useCreateRule();
  const updateMut = useUpdateRule();
  const monthlyMut = useRunMonthly();
  const yearlyMut = useRunYearlyReset();

  const editing = useMemo(
    () => rules.find((r) => r.year === editYear) ?? null,
    [rules, editYear]
  );

  function openEdit(rule: LeaveAccrualRule) {
    setEditYear(rule.year);
    form.setFieldsValue(rule);
  }

  function submitEdit() {
    if (!editing) return;
    form.validateFields().then((values) => {
      updateMut.mutate(
        { year: editing.year, body: values },
        {
          onSuccess: () => {
            message.success("규칙 저장 완료");
            setEditYear(null);
          },
          onError: () => message.error("저장 실패"),
        }
      );
    });
  }

  function createNextYear() {
    const nextY = thisYear() + 1;
    if (rules.some((r) => r.year === nextY)) {
      message.warning(`${nextY} 규칙이 이미 있습니다`);
      return;
    }
    createMut.mutate(
      { year: nextY },
      {
        onSuccess: () => message.success(`${nextY} 기본 규칙 생성`),
        onError: () => message.error("생성 실패"),
      }
    );
  }

  const ruleCols: ColumnsType<LeaveAccrualRule> = [
    { title: "연도", dataIndex: "year", width: 80 },
    { title: "기본일수", dataIndex: "base_days", width: 100, align: "right" },
    {
      title: "상한",
      dataIndex: "max_days",
      width: 80,
      align: "right",
    },
    {
      title: "가산 시작(년)",
      dataIndex: "tenure_bonus_start_years",
      width: 120,
      align: "right",
    },
    {
      title: "가산 간격(년)",
      dataIndex: "tenure_bonus_interval",
      width: 120,
      align: "right",
    },
    {
      title: "월차(<1yr)",
      key: "monthly",
      width: 120,
      align: "right",
      render: (_, r) => `+${r.under_1year_monthly}/월 · 최대 ${r.under_1year_max}`,
    },
    {
      title: "이월 기본",
      dataIndex: "carry_over_enabled",
      width: 100,
      align: "center",
      render: (v: boolean) =>
        v ? <Tag color="gold">허용</Tag> : <Tag>소멸</Tag>,
    },
    {
      title: "",
      key: "actions",
      width: 90,
      render: (_, r) => (
        <Button size="small" onClick={() => openEdit(r)}>
          편집
        </Button>
      ),
    },
  ];

  const typeCols: ColumnsType<LeaveType> = [
    { title: "코드", dataIndex: "code", width: 120 },
    { title: "이름", dataIndex: "name", width: 140 },
    {
      title: "차감대상",
      dataIndex: "deduct_from",
      width: 120,
      render: (v: string) => (v === "ANNUAL" ? "연차" : "별도"),
    },
    {
      title: "단위",
      dataIndex: "unit",
      width: 100,
      render: (v: string) =>
        v === "DAY" ? "일" : v === "HALF_DAY" ? "반일" : "시간",
    },
    {
      title: "유급",
      dataIndex: "is_paid",
      width: 80,
      align: "center",
      render: (v: boolean) => (v ? "✓" : ""),
    },
    {
      title: "증빙",
      dataIndex: "requires_evidence",
      width: 80,
      align: "center",
      render: (v: boolean) => (v ? "필수" : ""),
    },
    {
      title: "상태",
      dataIndex: "is_active",
      width: 80,
      render: (v: boolean) =>
        v ? <Tag color="green">활성</Tag> : <Tag>비활성</Tag>,
    },
  ];

  return (
    <PageShell
      title="연차 규칙 · 운영"
      subtitle="발생 규칙 · 휴가 종류 · 스케줄러 수동 실행"
      actions={
        <Button
          type="primary"
          size="small"
          loading={createMut.isPending}
          onClick={createNextYear}
        >
          내년 기본 규칙 생성
        </Button>
      }
    >
      <Space direction="vertical" size="large" style={{ width: "100%" }}>
        <Alert
          type="info"
          showIcon
          message="사용촉진제가 기본입니다. 이월 필요 사원은 연차 잔여 관리에서 이월예외를 설정하세요."
        />

        <Card size="small" title="연도별 발생 규칙">
          <Table
            size="small"
            columns={ruleCols}
            dataSource={rules}
            rowKey="id"
            loading={loadingRules}
            pagination={false}
            locale={{ emptyText: "규칙이 없습니다. 먼저 생성하세요." }}
          />
        </Card>

        <Card size="small" title="휴가 종류">
          <Table
            size="small"
            columns={typeCols}
            dataSource={types}
            rowKey="id"
            loading={loadingTypes}
            pagination={false}
          />
        </Card>

        <Card size="small" title="스케줄러 수동 실행 (멱등)">
          <Row gutter={16}>
            <Col xs={24} md={12}>
              <Descriptions
                size="small"
                column={1}
                title="월차 발생"
                bordered
              >
                <Descriptions.Item label="주기">
                  매월 1일 00:05 KST
                </Descriptions.Item>
                <Descriptions.Item label="대상">
                  입사 1년 미만 직원 (월 +1일, 최대 11일)
                </Descriptions.Item>
                <Descriptions.Item label="실행">
                  <Button
                    size="small"
                    loading={monthlyMut.isPending}
                    onClick={() =>
                      monthlyMut.mutate(
                        {},
                        {
                          onSuccess: (r) =>
                            message.success(
                              `${r.year}-${r.month} 월차 부여 · ${r.granted}건`
                            ),
                          onError: () => message.error("실행 실패"),
                        }
                      )
                    }
                  >
                    이번달 월차 실행
                  </Button>
                </Descriptions.Item>
              </Descriptions>
            </Col>
            <Col xs={24} md={12}>
              <Descriptions
                size="small"
                column={1}
                title="연간 리셋"
                bordered
              >
                <Descriptions.Item label="주기">
                  매년 1/1 00:10 KST
                </Descriptions.Item>
                <Descriptions.Item label="처리">
                  전년도 잔여 소멸 · 신년도 초기 부여
                </Descriptions.Item>
                <Descriptions.Item label="실행">
                  <Button
                    size="small"
                    danger
                    loading={yearlyMut.isPending}
                    onClick={() =>
                      Modal.confirm({
                        title: "연간 리셋을 실행할까요?",
                        content: "전년도 잔여가 소멸/이월되고 신년도 잔여가 부여됩니다. 재실행 시 이전 결과는 변경되지 않습니다.",
                        okText: "실행",
                        cancelText: "취소",
                        onOk: () =>
                          yearlyMut.mutate(
                            {},
                            {
                              onSuccess: (r) =>
                                message.success(
                                  `리셋 ${r.status}: 소멸 ${r.expired} · 이월 ${r.carried} · 부여 ${r.granted}`
                                ),
                              onError: () => message.error("실행 실패"),
                            }
                          ),
                      })
                    }
                  >
                    연간 리셋 실행
                  </Button>
                </Descriptions.Item>
              </Descriptions>
            </Col>
          </Row>
        </Card>
      </Space>

      <Modal
        open={editYear !== null}
        title={`${editing?.year} 규칙 편집`}
        onCancel={() => setEditYear(null)}
        onOk={submitEdit}
        confirmLoading={updateMut.isPending}
        okText="저장"
        cancelText="취소"
        destroyOnHidden
      >
        <Form form={form} layout="vertical" requiredMark={false}>
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item name="base_days" label="기본 일수">
                <InputNumber min={0} max={365} style={{ width: "100%" }} />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="max_days" label="상한">
                <InputNumber min={0} max={365} style={{ width: "100%" }} />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item
                name="tenure_bonus_start_years"
                label="가산 시작(근속 년차)"
              >
                <InputNumber min={0} max={50} style={{ width: "100%" }} />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="tenure_bonus_interval" label="가산 간격(년)">
                <InputNumber min={1} max={50} style={{ width: "100%" }} />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="under_1year_monthly" label="<1yr 월 발생">
                <InputNumber min={0} max={31} style={{ width: "100%" }} />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="under_1year_max" label="<1yr 연간 상한">
                <InputNumber min={0} max={31} style={{ width: "100%" }} />
              </Form.Item>
            </Col>
            <Col span={24}>
              <Form.Item
                name="carry_over_enabled"
                label="이월 기본 허용"
                valuePropName="checked"
              >
                <Switch />
              </Form.Item>
            </Col>
          </Row>
        </Form>
      </Modal>
    </PageShell>
  );
}
