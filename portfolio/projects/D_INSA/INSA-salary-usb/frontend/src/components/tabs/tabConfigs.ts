import type { FieldConfig } from "./SingleRecordTab";
import type { ColumnConfig } from "./MultiRecordTab";

// ── 1:1 tabs ──

export const personalFields: FieldConfig[] = [
  { name: "address", label: "주소" },
  { name: "phone", label: "전화번호" },
  { name: "email", label: "이메일" },
  { name: "emergency_contact", label: "비상연락처 (이름)" },
  { name: "emergency_phone", label: "비상연락처 (전화)" },
];

export const militaryFields: FieldConfig[] = [
  { name: "branch", label: "군별" },
  { name: "rank", label: "계급" },
  { name: "service_start", label: "입대일", type: "date" },
  { name: "service_end", label: "전역일", type: "date" },
  { name: "exemption_reason", label: "면제사유" },
];

export const veteranFields: FieldConfig[] = [
  { name: "veteran_no", label: "보훈번호" },
  { name: "veteran_type", label: "보훈구분" },
  { name: "veteran_grade", label: "등급" },
];

export const disabilityFields: FieldConfig[] = [
  { name: "disability_type", label: "장애유형" },
  { name: "disability_grade", label: "장애등급" },
  { name: "registered_at", label: "등록일", type: "date" },
];

// ── 1:N tabs ──

export const familyColumns: ColumnConfig[] = [
  { name: "relation", label: "관계", required: true },
  { name: "name", label: "성명", required: true },
  { name: "birth_date", label: "생년월일", type: "date" },
  { name: "is_cohabiting", label: "동거여부", type: "boolean" },
];

export const educationColumns: ColumnConfig[] = [
  { name: "school_name", label: "학교명", required: true },
  { name: "degree", label: "학위" },
  { name: "major", label: "전공" },
  { name: "graduation_year", label: "졸업년도", type: "number" },
];

export const careerColumns: ColumnConfig[] = [
  { name: "company_name", label: "회사명", required: true },
  { name: "position", label: "직위" },
  { name: "start_date", label: "시작일", type: "date" },
  { name: "end_date", label: "종료일", type: "date" },
];

export const certificateColumns: ColumnConfig[] = [
  { name: "cert_name", label: "자격명", required: true },
  { name: "issuer", label: "발급기관" },
  { name: "acquired_at", label: "취득일", type: "date" },
];

export const languageColumns: ColumnConfig[] = [
  { name: "language", label: "언어", required: true },
  { name: "test_name", label: "시험명" },
  { name: "score", label: "점수" },
  { name: "acquired_at", label: "취득일", type: "date" },
];

export const awardColumns: ColumnConfig[] = [
  { name: "award_name", label: "포상명", required: true },
  { name: "award_date", label: "포상일", type: "date" },
  { name: "description", label: "내용" },
];

export const disciplineColumns: ColumnConfig[] = [
  { name: "discipline_type", label: "징계유형", required: true },
  { name: "discipline_date", label: "징계일", type: "date" },
  { name: "reason", label: "사유" },
];

export const evaluationColumns: ColumnConfig[] = [
  { name: "eval_year", label: "평가연도", type: "number" },
  { name: "eval_grade", label: "평가등급" },
  { name: "score", label: "점수", type: "number" },
];

export const accountColumns: ColumnConfig[] = [
  { name: "bank_name", label: "은행명", required: true },
  { name: "account_no", label: "계좌번호", required: true },
  { name: "account_holder", label: "예금주", required: true },
];
