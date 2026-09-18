/** 연봉 금고 파일 포맷 v1 — 스펙 §4 참조 */

export const MAGIC = "INSASAL1";
export const MAGIC_SIZE = 8;
export const VAULT_VERSION = 1;
export const HEADER_SIZE = 41;
export const SALT_SIZE = 16;
export const IV_SIZE = 12;
export const DEFAULT_KDF_ITER = 210_000;
export const MIN_KDF_ITER = 100_000;
export const VAULT_FILENAME = "salary.enc";
export const BACKUP_FILENAME = "salary.enc.bak";

/** 직원 한 명의 한 해 연봉 기록. 식별자는 (empId, year) 조합이다. */
export interface SalaryRecord {
  empId: number;
  /** 파일 단독 판독과 퇴사자 이력 보존을 위한 스냅샷 */
  empNo: string;
  /** 같은 이유의 스냅샷 */
  empName: string;
  year: number;
  /** YYYY-MM-DD */
  effectiveDate: string;
  /** 정수(원) */
  annualSalary: number;
  /** 소수 1자리 퍼센트. 계산하지 않고 입력값 그대로 보관한다 */
  raiseRate: number | null;
  note: string | null;
}

export interface VaultData {
  schemaVersion: number;
  /** ISO 8601 */
  updatedAt: string;
  records: SalaryRecord[];
}

export interface VaultHeader {
  version: number;
  kdfIter: number;
  salt: Uint8Array;
  iv: Uint8Array;
}

export function makeEmptyVault(now: string): VaultData {
  return { schemaVersion: 1, updatedAt: now, records: [] };
}

/** (empId, year) 복합 키 */
export function recordKey(r: Pick<SalaryRecord, "empId" | "year">): string {
  return `${r.empId}:${r.year}`;
}
