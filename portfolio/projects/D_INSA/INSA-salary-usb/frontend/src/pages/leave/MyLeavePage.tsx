import { useMemo, useState } from "react";
import { Card, Col, Row, Select, Space, Statistic, Table, Tag } from "antd";
import type { ColumnsType } from "antd/es/table";
import { PageShell } from "../../shell/PageShell";
import {
  LeaveTransaction,
  LeaveTransactionType,
  useMyBalance,
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

const TYPE_COLOR: Record<LeaveTransactionType, string> = {
  INITIAL_GRANT: "blue",
  MONTHLY_GRANT: "geekblue",
  ADDITIONAL: "green",
  USE: "red",
  CANCEL: "gold",
  EXPIRE: "default",
  CARRY_OVER: "cyan",
  ADJUST: "purple",
};

function thisYear(): number {
  return new Date().getFullYear();
}

export default function MyLeavePage() {
  const [year, setYear] = useState<number>(thisYear());
  const { data: balance, isLoading: loadingBalance } = useMyBalance(year);
  const { data: txs = [], isLoading: loadingTxs } = useTransactions(
    balance?.emp_id ?? null,
    year
  );

  const yearOptions = useMemo(() => {
    const y = thisYear();
    return [y - 1, y, y + 1].map((v) => ({ value: v, label: `${v}년` }));
  }, []);

  const columns: ColumnsType<LeaveTransaction> = [
    {
      title: "날짜",
      dataIndex: "created_at",
      key: "created_at",
      width: 170,
      render: (v: string | null) => (v ? v.slice(0, 16).replace("T", " ") : "-"),
    },
    {
      title: "구분",
      dataIndex: "transaction_type",
      key: "type",
      width: 110,
      render: (v: LeaveTransactionType) => (
        <Tag color={TYPE_COLOR[v]}>{TYPE_LABELS[v]}</Tag>
      ),
    },
    {
      title: "일수",
      dataIndex: "amount",
      key: "amount",
      width: 100,
      align: "right",
      render: (v: string) => {
        const n = Number(v);
        return (
          <span style={{ color: n < 0 ? "#c62828" : "#1a1a2e" }}>
            {n > 0 ? "+" : ""}
            {n.toFixed(1)}
          </span>
        );
      },
    },
    {
      title: "잔여",
      dataIndex: "balance_after",
      key: "balance_after",
      width: 100,
      align: "right",
      render: (v: string) => Number(v).toFixed(1),
    },
    {
      title: "사유",
      dataIndex: "reason",
      key: "reason",
      render: (v: string | null) => v || "-",
    },
  ];

  const remaining = Number(balance?.remaining ?? 0);
  const granted =
    Number(balance?.initial_days ?? 0) +
    Number(balance?.carried_over_days ?? 0) +
    Number(balance?.additional_days ?? 0);

  return (
    <PageShell
      title="내 연차"
      subtitle="연차 잔여 · 사용 내역"
      actions={
        <Select
          size="small"
          value={year}
          options={yearOptions}
          onChange={setYear}
          style={{ width: 120 }}
        />
      }
    >
      <Space direction="vertical" size="large" style={{ width: "100%" }}>
        <Row gutter={16}>
          <Col xs={24} sm={12} md={6}>
            <Card size="small" loading={loadingBalance}>
              <Statistic title="잔여" value={remaining} precision={1} suffix="일" />
            </Card>
          </Col>
          <Col xs={24} sm={12} md={6}>
            <Card size="small" loading={loadingBalance}>
              <Statistic
                title="부여"
                value={granted}
                precision={1}
                suffix="일"
              />
            </Card>
          </Col>
          <Col xs={24} sm={12} md={6}>
            <Card size="small" loading={loadingBalance}>
              <Statistic
                title="사용"
                value={Number(balance?.used_days ?? 0)}
                precision={1}
                suffix="일"
              />
            </Card>
          </Col>
          <Col xs={24} sm={12} md={6}>
            <Card size="small" loading={loadingBalance}>
              <Statistic
                title="이월"
                value={Number(balance?.carried_over_days ?? 0)}
                precision={1}
                suffix="일"
              />
            </Card>
          </Col>
        </Row>

        <Card size="small" title="트랜잭션 이력">
          <Table
            size="small"
            columns={columns}
            dataSource={txs}
            rowKey="id"
            loading={loadingTxs}
            pagination={{ pageSize: 20, showSizeChanger: false }}
            locale={{ emptyText: "내역이 없습니다" }}
          />
        </Card>
      </Space>
    </PageShell>
  );
}
