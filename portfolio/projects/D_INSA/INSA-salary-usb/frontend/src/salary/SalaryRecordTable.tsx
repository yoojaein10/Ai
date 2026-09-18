import { Button, Modal, Space, Table } from "antd";
import type { SalaryRecord } from "./types";

interface Props {
  records: SalaryRecord[];
  onEdit: (record: SalaryRecord) => void;
  onDelete: (empId: number, year: number) => void;
}

export default function SalaryRecordTable({ records, onEdit, onDelete }: Props) {
  return (
    <Table
      size="small"
      rowKey={(r) => `${r.empId}:${r.year}`}
      dataSource={records}
      pagination={{ pageSize: 20 }}
      columns={[
        { title: "직원명", dataIndex: "empName", key: "empName" },
        { title: "사번", dataIndex: "empNo", key: "empNo" },
        { title: "연도", dataIndex: "year", key: "year" },
        { title: "적용일", dataIndex: "effectiveDate", key: "effectiveDate" },
        {
          title: "연봉액",
          dataIndex: "annualSalary",
          key: "annualSalary",
          align: "right",
          render: (v: number) => (
            <span style={{ fontVariantNumeric: "tabular-nums" }}>
              {v.toLocaleString("ko-KR")}
            </span>
          ),
        },
        {
          title: "인상률",
          dataIndex: "raiseRate",
          key: "raiseRate",
          align: "right",
          render: (v: number | null) => (v === null ? "-" : `${v.toFixed(1)}%`),
        },
        {
          title: "비고",
          dataIndex: "note",
          key: "note",
          render: (v: string | null) => v ?? "-",
        },
        {
          title: "",
          key: "actions",
          render: (_: unknown, row: SalaryRecord) => (
            <Space>
              <Button size="small" type="link" onClick={() => onEdit(row)}>
                수정
              </Button>
              <Button
                size="small"
                type="link"
                onClick={() =>
                  Modal.confirm({
                    title: `${row.empName} ${row.year}년 기록을 삭제합니다`,
                    okText: "삭제",
                    cancelText: "취소",
                    onOk: () => onDelete(row.empId, row.year),
                  })
                }
              >
                삭제
              </Button>
            </Space>
          ),
        },
      ]}
    />
  );
}
