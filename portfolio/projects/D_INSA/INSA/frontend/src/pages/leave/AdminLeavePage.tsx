import { useMemo, useState } from "react";
import {
  App,
  Button,
  Card,
  Drawer,
  Form,
  Input,
  InputNumber,
  Modal,
  Select,
  Space,
  Switch,
  Table,
  Tag,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import { PageShell } from "../../shell/PageShell";
import {
  LeaveBalance,
  LeaveTransaction,
  LeaveTransactionType,
  useAdjustBalance,
  useBalanceList,
  useCarryOverExempt,
  useGrantInitial,
  useTransactions,
} from "../../api/leave";

const TYPE_LABELS: Record<LeaveTransactionType, string> = {
  INITIAL_GRANT: "연초 부여",
  MONTHLY_GRANT: "월차 부여",
  ADDITIONAL: "추가 부여",
  USE: "사용",
  CANCEL: "취소",
  EXPIRE: "소멸",
  CARRY_OVER: "이월",
  ADJUST: "조정",
};

function thisYear(): number {
  return new Date().getFullYear();
}

type AdjustForm = {
  amount: number;
  reason: string;
};

export default function AdminLeavePage() {
  const { message } = App.useApp();
  const [year, setYear] = useState<number>(thisYear());
  const [keyword, setKeyword] = useState<string>("");
  const [adjustTarget, setAdjustTarget] = useState<LeaveBalance | null>(null);
  const [txTarget, setTxTarget] = useState<LeaveBalance | null>(null);
  const [form] = Form.useForm<AdjustForm>();

  const { data: rows = [], isLoading } = useBalanceList(
    year,
    undefined,
    keyword || undefined
  );
  const { data: txs = [] } = useTransactions(txTarget?.emp_id ?? null, year);

  const adjustMut = useAdjustBalance();
  const exemptMut = useCarryOverExempt();
  const grantMut = useGrantInitial();

  const yearOptions = useMemo(() => {
    const y = thisYear();
    return [y - 1, y, y + 1].map((v) => ({ value: v, label: `${v}년` }));
  }, []);

  const columns: ColumnsType<LeaveBalance> = [
    { title: "사번", dataIndex: "emp_no", width: 110 },
    { title: "이름", dataIndex: "emp_name", width: 110 },
    { title: "부서", dataIndex: "dept_name", width: 130 },
    { title: "입사일", dataIndex: "hire_date", width: 120 },
    {
      title: "부여",
      key: "granted",
      width: 90,
      align: "right",
      render: (_, r) =>
        (
          Number(r.initial_days) +
          Number(r.carried_over_days) +
          Number(r.additional_days)
        ).toFixed(1),
    },
    {
      title: "사용",
      dataIndex: "used_days",
      width: 80,
      align: "right",
      render: (v: string) => Number(v).toFixed(1),
    },
    {
      title: "잔여",
      key: "remaining",
      width: 80,
      align: "right",
      render: (_, r) => Number(r.remaining ?? 0).toFixed(1),
    },
    {
      title: "이월예외",
      dataIndex: "carry_over_exempt",
      width: 100,
      align: "center",
      render: (v: boolean, r) => (
        <Switch
          size="small"
          checked={v}
          loading={exemptMut.isPending}
          onChange={(next) =>
            exemptMut.mutate(
              { emp_id: r.emp_id, year: r.year, exempt: next },
              {
                onSuccess: () =>
                  message.success(next ? "이월예외 적용" : "이월예외 해제"),
                onError: () => message.error("실패"),
              }
            )
          }
        />
      ),
    },
    {
      title: "",
      key: "actions",
      width: 200,
      render: (_, r) => (
        <Space size={4}>
          <Button size="small" onClick={() => setTxTarget(r)}>
            이력
          </Button>
          <Button
            size="small"
            type="primary"
            onClick={() => {
              setAdjustTarget(r);
              form.resetFields();
            }}
          >
            조정
          </Button>
        </Space>
      ),
    },
  ];

  const txColumns: ColumnsType<LeaveTransaction> = [
    {
      title: "날짜",
      dataIndex: "created_at",
      width: 150,
      render: (v: string | null) => (v ? v.slice(0, 16).replace("T", " ") : "-"),
    },
    {
      title: "구분",
      dataIndex: "transaction_type",
      width: 100,
      render: (v: LeaveTransactionType) => <Tag>{TYPE_LABELS[v]}</Tag>,
    },
    {
      title: "일수",
      dataIndex: "amount",
      width: 80,
      align: "right",
      render: (v: string) => {
        const n = Number(v);
        return `${n > 0 ? "+" : ""}${n.toFixed(1)}`;
      },
    },
    {
      title: "잔여",
      dataIndex: "balance_after",
      width: 80,
      align: "right",
      render: (v: string) => Number(v).toFixed(1),
    },
    { title: "사유", dataIndex: "reason", render: (v: string | null) => v || "-" },
  ];

  function submitAdjust() {
    if (!adjustTarget) return;
    form.validateFields().then((values) => {
      adjustMut.mutate(
        {
          emp_id: adjustTarget.emp_id,
          amount: values.amount,
          reason: values.reason,
          year,
        },
        {
          onSuccess: () => {
            message.success("조정 완료");
            setAdjustTarget(null);
          },
          onError: (err: unknown) => {
            const msg =
              (err as { response?: { data?: { detail?: string } } })?.response
                ?.data?.detail ?? "조정 실패";
            message.error(msg);
          },
        }
      );
    });
  }

  return (
    <PageShell
      title="연차 잔여 관리"
      subtitle="직원별 연차 잔여 · 조정 · 이력"
      actions={
        <Space size="small">
          <Select
            size="small"
            value={year}
            options={yearOptions}
            onChange={setYear}
            style={{ width: 120 }}
          />
        </Space>
      }
      toolbar={
        <Space size="small">
          <Input.Search
            size="small"
            placeholder="이름 · 사번"
            onSearch={setKeyword}
            style={{ width: 220 }}
            allowClear
          />
        </Space>
      }
    >
      <Card size="small">
        <Table
          size="small"
          columns={columns}
          dataSource={rows}
          rowKey="id"
          loading={isLoading}
          pagination={{ pageSize: 30, showSizeChanger: false }}
          locale={{ emptyText: "자료가 없습니다. 연간 리셋 또는 개별 부여가 필요합니다." }}
        />
      </Card>

      <Modal
        open={adjustTarget !== null}
        title={`연차 조정 — ${adjustTarget?.emp_name} (${adjustTarget?.emp_no})`}
        onCancel={() => setAdjustTarget(null)}
        onOk={submitAdjust}
        okText="저장"
        cancelText="취소"
        confirmLoading={adjustMut.isPending}
        destroyOnHidden
      >
        <Form form={form} layout="vertical" requiredMark={false}>
          <Form.Item
            name="amount"
            label="조정 일수 (양수 = 부여, 음수 = 차감)"
            rules={[
              { required: true, message: "필수" },
              {
                validator: async (_, v) => {
                  if (v === 0) throw new Error("0은 불가");
                },
              },
            ]}
          >
            <InputNumber
              step={0.5}
              style={{ width: "100%" }}
              placeholder="예: 1.5 또는 -0.5"
            />
          </Form.Item>
          <Form.Item
            name="reason"
            label="사유"
            rules={[{ required: true, message: "필수", whitespace: true }]}
          >
            <Input.TextArea rows={3} maxLength={200} />
          </Form.Item>
        </Form>
      </Modal>

      <Drawer
        open={txTarget !== null}
        onClose={() => setTxTarget(null)}
        title={
          txTarget
            ? `${txTarget.emp_name} 연차 이력 (${year}년)`
            : "연차 이력"
        }
        width={720}
        extra={
          txTarget ? (
            <Button
              size="small"
              loading={grantMut.isPending}
              onClick={() =>
                grantMut.mutate(
                  { emp_id: txTarget.emp_id, year },
                  {
                    onSuccess: () => message.success("연초 부여 완료"),
                    onError: () => message.error("이미 부여되었거나 규칙 없음"),
                  }
                )
              }
            >
              연초 재부여 (멱등)
            </Button>
          ) : null
        }
      >
        <Table
          size="small"
          columns={txColumns}
          dataSource={txs}
          rowKey="id"
          pagination={{ pageSize: 50, showSizeChanger: false }}
        />
      </Drawer>
    </PageShell>
  );
}
