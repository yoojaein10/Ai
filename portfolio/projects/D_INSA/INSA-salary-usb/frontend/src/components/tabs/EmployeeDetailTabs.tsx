import { Tabs, Table } from "antd";
import MasterTab from "./MasterTab";
import SingleRecordTab from "./SingleRecordTab";
import MultiRecordTab from "./MultiRecordTab";
import {
  personalFields,
  militaryFields,
  veteranFields,
  disabilityFields,
  familyColumns,
  educationColumns,
  careerColumns,
  certificateColumns,
  languageColumns,
  awardColumns,
  disciplineColumns,
  evaluationColumns,
  accountColumns,
} from "./tabConfigs";
import { useTabList } from "../../api/empTabs";

interface Props {
  employeeId: number;
  detail: Record<string, unknown>;
}

function AppointmentTab({ employeeId }: { employeeId: number }) {
  const { data, isLoading } = useTabList<Record<string, unknown>>(employeeId, "appointments");
  // appointments are under /appointments/employee/{id}, not /employees/{id}/appointments
  // so we use a direct query
  return (
    <Table
      columns={[
        { title: "발령유형", dataIndex: "appt_type", key: "appt_type" },
        { title: "발령일", dataIndex: "appt_date", key: "appt_date" },
        { title: "변경전 직급", dataIndex: "old_rank", key: "old_rank", render: (v: string | null) => v ?? "-" },
        { title: "변경후 직급", dataIndex: "new_rank", key: "new_rank", render: (v: string | null) => v ?? "-" },
        { title: "설명", dataIndex: "description", key: "description", render: (v: string | null) => v ?? "-" },
      ]}
      dataSource={data ?? []}
      rowKey="id"
      size="small"
      loading={isLoading}
      pagination={false}
    />
  );
}

function AccountTab({ employeeId }: { employeeId: number }) {
  return (
    <MultiRecordTab
      employeeId={employeeId}
      tabKey="accounts"
      columns={accountColumns}
    />
  );
}

export default function EmployeeDetailTabs({ employeeId, detail }: Props) {
  return (
    <Tabs
      defaultActiveKey="master"
      style={{ padding: "0 18px" }}
      items={[
        {
          key: "master",
          label: "마스터",
          children: <MasterTab employeeId={employeeId} detail={detail} />,
        },
        {
          key: "personal",
          label: "신상",
          children: <SingleRecordTab employeeId={employeeId} tabKey="personal" fields={personalFields} />,
        },
        {
          key: "military",
          label: "병역",
          children: <SingleRecordTab employeeId={employeeId} tabKey="military" fields={militaryFields} />,
        },
        {
          key: "veteran",
          label: "보훈",
          children: <SingleRecordTab employeeId={employeeId} tabKey="veteran" fields={veteranFields} />,
        },
        {
          key: "disability",
          label: "장애",
          children: <SingleRecordTab employeeId={employeeId} tabKey="disability" fields={disabilityFields} />,
        },
        {
          key: "families",
          label: "가족",
          children: <MultiRecordTab employeeId={employeeId} tabKey="families" columns={familyColumns} />,
        },
        {
          key: "educations",
          label: "학력",
          children: <MultiRecordTab employeeId={employeeId} tabKey="educations" columns={educationColumns} />,
        },
        {
          key: "careers",
          label: "경력",
          children: <MultiRecordTab employeeId={employeeId} tabKey="careers" columns={careerColumns} />,
        },
        {
          key: "certificates",
          label: "자격",
          children: <MultiRecordTab employeeId={employeeId} tabKey="certificates" columns={certificateColumns} />,
        },
        {
          key: "languages",
          label: "어학",
          children: <MultiRecordTab employeeId={employeeId} tabKey="languages" columns={languageColumns} />,
        },
        {
          key: "appointments",
          label: "발령",
          children: <AppointmentTab employeeId={employeeId} />,
        },
        {
          key: "awards",
          label: "포상",
          children: <MultiRecordTab employeeId={employeeId} tabKey="awards" columns={awardColumns} />,
        },
        {
          key: "disciplines",
          label: "징계",
          children: <MultiRecordTab employeeId={employeeId} tabKey="disciplines" columns={disciplineColumns} />,
        },
        {
          key: "evaluations",
          label: "평가",
          children: (
            <MultiRecordTab
              employeeId={employeeId}
              tabKey="evaluations"
              columns={evaluationColumns}
              editable={false}
            />
          ),
        },
        {
          key: "accounts",
          label: "계좌",
          children: <AccountTab employeeId={employeeId} />,
        },
      ]}
    />
  );
}
