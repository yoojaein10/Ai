# 연봉 USB 암호화 저장 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 연봉 데이터를 서버 DB가 아닌 USB의 단일 AES-256-GCM 암호화 파일에 저장하고, 서버에는 접근 기록만 남기는 연봉 관리 화면을 만든다.

**Architecture:** 브라우저의 File System Access API로 USB 폴더 핸들을 받아 `salary.enc`를 직접 읽고 쓴다. 암호 로직(`crypto.ts`)과 파일 입출력(`vault.ts`)을 완전히 분리해 암호 부분을 브라우저 없이 단위 테스트한다. 서버는 연봉 데이터를 전혀 모르고, 접근 감사 로그와 IP 허용 정책만 관리한다.

**Tech Stack:** React 18 + TypeScript + Vite + Ant Design 5 + React Query + Zustand (FE) / FastAPI + SQLAlchemy + Alembic + pytest (BE) / Web Crypto API, IndexedDB, File System Access API

**Spec:** `docs/superpowers/specs/2026-08-19-salary-usb-design.md`

## Global Constraints

- 작업 위치: worktree `D:\AI\INSA-salary-usb`, 브랜치 `feature/salary-usb-vault`
- **연봉 금액·직원명·사번은 절대 서버로 전송하지 않는다.** 서버 요청 본문에 이 값이 들어가면 설계 위반이다.
- 모든 테이블은 `insa_` 접두사를 쓴다.
- PK는 `Integer`를 쓴다. 이 프로젝트는 `BigInteger`를 한 번도 쓰지 않는다.
- 불변 패턴만 사용한다. 객체를 직접 변경하지 말고 새 객체를 만든다 (`{...prev, field}`).
- 파일은 200~400줄, 최대 800줄. 함수는 50줄 이내.
- 암호화: AES-256-GCM, PBKDF2-SHA256 **210,000회**, salt 16B, IV 12B, 헤더 41B를 AAD로 사용.
- `kdfIter` 하한은 **100,000**. 미만이면 파일을 거부한다.
- 파일 magic은 ASCII `"INSASAL1"` (8바이트), version은 `0x01`.
- 감사 로그 테이블에 `emp_id` · `emp_no` · `emp_name` · `annual_salary` · `raise_rate` · `note` · `password` · `file_path` · `salt` · `iv` 컬럼을 **만들지 않는다.**
- 커밋 형식: `<type>: <description>` (feat, fix, refactor, docs, test, chore)
- 백엔드 테스트: `cd backend && python -m pytest`
- 프론트 테스트: `cd frontend && npx vitest run`

---

## File Structure

| 파일 | 책임 |
|---|---|
| `frontend/src/salary/types.ts` | 공유 타입과 포맷 상수. 로직 없음 |
| `frontend/src/salary/crypto.ts` | 바이트 ↔ `VaultData` 변환. 파일시스템·React·네트워크를 모른다 |
| `frontend/src/salary/vault.ts` | 폴더 핸들·IndexedDB·`.bak` 순서. 암호를 모른다 |
| `frontend/src/salary/useSalaryVault.ts` | 상태 기계, dirty 추적, 자동 잠금 타이머 |
| `frontend/src/api/salaryAudit.ts` | 감사 로그 전송 |
| `frontend/src/api/salaryPolicy.ts` | IP 정책 조회·설정·검사 |
| `frontend/src/pages/SalaryPage.tsx` | 연봉 화면 4개 상태 |
| `frontend/src/pages/SalaryAdminPage.tsx` | IP 정책 설정 + 접근 로그 조회 (SYSTEM_ADMIN) |
| `backend/app/db/models.py` | `SalaryAccessLog`, `SalaryVaultPolicy` 추가 |
| `backend/app/schemas/salary_audit.py` | 감사 로그 Pydantic 스키마 |
| `backend/app/schemas/salary_policy.py` | IP 정책 Pydantic 스키마 |
| `backend/app/api/v1/salary_audit.py` | 감사 로그 라우터 |
| `backend/app/api/v1/salary_policy.py` | IP 정책 라우터 |

---

## Task 1: 타입 정의와 암호 모듈

**Files:**
- Create: `frontend/src/salary/types.ts`
- Create: `frontend/src/salary/crypto.ts`
- Test: `frontend/src/salary/__tests__/crypto.test.ts`

**Interfaces:**
- Consumes: 없음 (첫 작업)
- Produces:
  - `SalaryRecord`, `VaultData`, `VaultHeader` 타입
  - `MAGIC`, `HEADER_SIZE = 41`, `DEFAULT_KDF_ITER = 210000`, `MIN_KDF_ITER = 100000`, `VAULT_VERSION = 1`
  - `encryptVault(plain: VaultData, password: string, salt?: Uint8Array): Promise<Uint8Array>`
  - `decryptVault(bytes: Uint8Array, password: string): Promise<VaultData>`
  - `parseHeader(bytes: Uint8Array): VaultHeader`
  - `class VaultFormatError extends Error`
  - `class VaultDecryptError extends Error`

- [ ] **Step 1: 타입 파일을 만든다**

`frontend/src/salary/types.ts`:

```typescript
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
```

- [ ] **Step 2: 실패하는 테스트를 작성한다**

`frontend/src/salary/__tests__/crypto.test.ts`:

```typescript
import { describe, expect, it } from "vitest";
import {
  decryptVault,
  encryptVault,
  parseHeader,
  VaultDecryptError,
  VaultFormatError,
} from "../crypto";
import { HEADER_SIZE, MIN_KDF_ITER, type VaultData } from "../types";

const PASSWORD = "REDACTED_CONFIGURE_LOCALLY";

const SAMPLE: VaultData = {
  schemaVersion: 1,
  updatedAt: "2026-08-19T01:23:45.000Z",
  records: [
    {
      empId: 123,
      empNo: "20180012",
      empName: "홍길동",
      year: 2026,
      effectiveDate: "2026-01-01",
      annualSalary: 52_000_000,
      raiseRate: 4.5,
      note: "승진 반영",
    },
  ],
};

describe("crypto", () => {
  it("1. 왕복: 암호화한 뒤 복호화하면 원본과 같다", async () => {
    const bytes = await encryptVault(SAMPLE, PASSWORD);
    const back = await decryptVault(bytes, PASSWORD);
    expect(back).toEqual(SAMPLE);
  });

  it("2. 틀린 비밀번호로는 복호화에 실패한다", async () => {
    const bytes = await encryptVault(SAMPLE, PASSWORD);
    await expect(decryptVault(bytes, "wrong password")).rejects.toBeInstanceOf(
      VaultDecryptError,
    );
  });

  it("3. 같은 평문·같은 비밀번호를 두 번 암호화하면 암호문이 서로 다르다", async () => {
    const a = await encryptVault(SAMPLE, PASSWORD);
    const b = await encryptVault(SAMPLE, PASSWORD);
    const ivA = a.slice(29, 41);
    const ivB = b.slice(29, 41);
    expect(Array.from(ivA)).not.toEqual(Array.from(ivB));
    expect(Array.from(a.slice(HEADER_SIZE))).not.toEqual(
      Array.from(b.slice(HEADER_SIZE)),
    );
  });

  it("4. 암호문을 1바이트 변조하면 태그 검증에 실패한다", async () => {
    const bytes = await encryptVault(SAMPLE, PASSWORD);
    const tampered = new Uint8Array(bytes);
    tampered[HEADER_SIZE] ^= 0xff;
    await expect(decryptVault(tampered, PASSWORD)).rejects.toBeInstanceOf(
      VaultDecryptError,
    );
  });

  it("5. 헤더의 iv를 1바이트 변조하면 AAD 불일치로 실패한다", async () => {
    const bytes = await encryptVault(SAMPLE, PASSWORD);
    const tampered = new Uint8Array(bytes);
    tampered[29] ^= 0xff;
    await expect(decryptVault(tampered, PASSWORD)).rejects.toBeInstanceOf(
      VaultDecryptError,
    );
  });

  it("6a. magic이 다르면 형식 오류다", async () => {
    const bytes = await encryptVault(SAMPLE, PASSWORD);
    const tampered = new Uint8Array(bytes);
    tampered[0] = 0x00;
    expect(() => parseHeader(tampered)).toThrow(VaultFormatError);
  });

  it("6b. 지원하지 않는 버전이면 형식 오류다", async () => {
    const bytes = await encryptVault(SAMPLE, PASSWORD);
    const tampered = new Uint8Array(bytes);
    tampered[8] = 99;
    expect(() => parseHeader(tampered)).toThrow(VaultFormatError);
  });

  it("6c. kdfIter가 하한 미만이면 형식 오류다", async () => {
    const bytes = await encryptVault(SAMPLE, PASSWORD);
    const tampered = new Uint8Array(bytes);
    new DataView(tampered.buffer).setUint32(9, MIN_KDF_ITER - 1, false);
    expect(() => parseHeader(tampered)).toThrow(VaultFormatError);
  });

  it("6d. 헤더보다 짧은 파일은 형식 오류다", () => {
    expect(() => parseHeader(new Uint8Array(10))).toThrow(VaultFormatError);
  });

  it("7. 빈 records 배열도 왕복된다", async () => {
    const empty: VaultData = {
      schemaVersion: 1,
      updatedAt: "2026-08-19T00:00:00.000Z",
      records: [],
    };
    const back = await decryptVault(await encryptVault(empty, PASSWORD), PASSWORD);
    expect(back.records).toEqual([]);
  });

  it("8. 비밀번호를 바꿔 재암호화하면 salt가 바뀌고 옛 비밀번호로는 못 연다", async () => {
    const first = await encryptVault(SAMPLE, PASSWORD);
    const saltA = first.slice(13, 29);

    const plain = await decryptVault(first, PASSWORD);
    const second = await encryptVault(plain, "brand new password");
    const saltB = second.slice(13, 29);

    expect(Array.from(saltA)).not.toEqual(Array.from(saltB));
    await expect(decryptVault(second, PASSWORD)).rejects.toBeInstanceOf(
      VaultDecryptError,
    );
    await expect(decryptVault(second, "brand new password")).resolves.toEqual(
      SAMPLE,
    );
  });
});
```

- [ ] **Step 3: 테스트가 실패하는지 확인한다**

Run: `cd frontend && npx vitest run src/salary/__tests__/crypto.test.ts`
Expected: FAIL — `Failed to resolve import "../crypto"`

- [ ] **Step 4: 암호 모듈을 구현한다**

`frontend/src/salary/crypto.ts`:

```typescript
/**
 * 연봉 금고 암호 모듈 — 스펙 §5.
 * 파일시스템·React·네트워크를 import하지 않는다. 바이트만 다룬다.
 */
import {
  DEFAULT_KDF_ITER,
  HEADER_SIZE,
  IV_SIZE,
  MAGIC,
  MAGIC_SIZE,
  MIN_KDF_ITER,
  SALT_SIZE,
  VAULT_VERSION,
  type VaultData,
  type VaultHeader,
} from "./types";

export class VaultFormatError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "VaultFormatError";
  }
}

export class VaultDecryptError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "VaultDecryptError";
  }
}

const encoder = new TextEncoder();
const decoder = new TextDecoder();

function randomBytes(size: number): Uint8Array {
  return crypto.getRandomValues(new Uint8Array(size));
}

/**
 * 파생 키는 extractable: false 로 만들어 원시 바이트가 JS 변수에 남지 않게 한다.
 */
async function deriveKey(
  password: string,
  salt: Uint8Array,
  iterations: number,
): Promise<CryptoKey> {
  const baseKey = await crypto.subtle.importKey(
    "raw",
    encoder.encode(password),
    "PBKDF2",
    false,
    ["deriveKey"],
  );
  return crypto.subtle.deriveKey(
    { name: "PBKDF2", salt, iterations, hash: "SHA-256" },
    baseKey,
    { name: "AES-GCM", length: 256 },
    false,
    ["encrypt", "decrypt"],
  );
}

function buildHeader(kdfIter: number, salt: Uint8Array, iv: Uint8Array): Uint8Array {
  const header = new Uint8Array(HEADER_SIZE);
  header.set(encoder.encode(MAGIC), 0);
  header[MAGIC_SIZE] = VAULT_VERSION;
  new DataView(header.buffer).setUint32(9, kdfIter, false);
  header.set(salt, 13);
  header.set(iv, 29);
  return header;
}

export function parseHeader(bytes: Uint8Array): VaultHeader {
  if (bytes.length < HEADER_SIZE) {
    throw new VaultFormatError("파일이 너무 짧습니다. INSA 연봉 파일이 아닙니다.");
  }
  const magic = decoder.decode(bytes.slice(0, MAGIC_SIZE));
  if (magic !== MAGIC) {
    throw new VaultFormatError("INSA 연봉 파일이 아닙니다.");
  }
  const version = bytes[MAGIC_SIZE];
  if (version !== VAULT_VERSION) {
    throw new VaultFormatError(
      `지원하지 않는 파일 버전(${version})입니다. 최신 버전 INSA에서 열어주세요.`,
    );
  }
  const kdfIter = new DataView(
    bytes.buffer,
    bytes.byteOffset,
    bytes.byteLength,
  ).getUint32(9, false);
  if (kdfIter < MIN_KDF_ITER) {
    throw new VaultFormatError("파일의 키 유도 강도가 기준에 미달합니다.");
  }
  return {
    version,
    kdfIter,
    salt: bytes.slice(13, 13 + SALT_SIZE),
    iv: bytes.slice(29, 29 + IV_SIZE),
  };
}

/**
 * salt를 넘기지 않으면 새로 생성한다. 비밀번호 변경·위임에서 이 성질을 이용한다.
 * IV는 항상 새로 생성한다. 같은 키에 IV를 재사용하면 GCM에서 평문이 복원될 수 있다.
 */
export async function encryptVault(
  plain: VaultData,
  password: string,
  salt?: Uint8Array,
): Promise<Uint8Array> {
  const useSalt = salt ?? randomBytes(SALT_SIZE);
  const iv = randomBytes(IV_SIZE);
  const header = buildHeader(DEFAULT_KDF_ITER, useSalt, iv);
  const key = await deriveKey(password, useSalt, DEFAULT_KDF_ITER);

  const cipher = new Uint8Array(
    await crypto.subtle.encrypt(
      { name: "AES-GCM", iv, additionalData: header, tagLength: 128 },
      key,
      encoder.encode(JSON.stringify(plain)),
    ),
  );

  const out = new Uint8Array(HEADER_SIZE + cipher.length);
  out.set(header, 0);
  out.set(cipher, HEADER_SIZE);
  return out;
}

export async function decryptVault(
  bytes: Uint8Array,
  password: string,
): Promise<VaultData> {
  const header = parseHeader(bytes);
  const key = await deriveKey(password, header.salt, header.kdfIter);

  let plainBytes: ArrayBuffer;
  try {
    plainBytes = await crypto.subtle.decrypt(
      {
        name: "AES-GCM",
        iv: header.iv,
        additionalData: bytes.slice(0, HEADER_SIZE),
        tagLength: 128,
      },
      key,
      bytes.slice(HEADER_SIZE),
    );
  } catch {
    throw new VaultDecryptError(
      "비밀번호가 올바르지 않거나 파일이 손상되었습니다.",
    );
  }

  try {
    return JSON.parse(decoder.decode(plainBytes)) as VaultData;
  } catch {
    throw new VaultDecryptError("파일 내용을 읽을 수 없습니다.");
  }
}
```

- [ ] **Step 5: 테스트가 통과하는지 확인한다**

Run: `cd frontend && npx vitest run src/salary/__tests__/crypto.test.ts`
Expected: PASS — 11 tests passed

PBKDF2 210,000회를 여러 번 돌리므로 테스트가 수 초 걸린다. 이는 정상이다.

- [ ] **Step 6: 커밋한다**

```bash
git add frontend/src/salary/types.ts frontend/src/salary/crypto.ts frontend/src/salary/__tests__/crypto.test.ts
git commit -m "feat(salary): 금고 파일 포맷과 AES-256-GCM 암호 모듈"
```

---

## Task 2: 파일 입출력 모듈

**Files:**
- Create: `frontend/src/salary/vault.ts`
- Test: `frontend/src/salary/__tests__/vault.test.ts`

**Interfaces:**
- Consumes: `VAULT_FILENAME`, `BACKUP_FILENAME` (Task 1의 `types.ts`)
- Produces:
  - `interface VaultFile { bytes: Uint8Array; lastModified: number }`
  - `isFileSystemAccessSupported(): boolean`
  - `pickVaultDirectory(): Promise<FileSystemDirectoryHandle>`
  - `saveHandle(dir: FileSystemDirectoryHandle): Promise<void>`
  - `loadHandle(): Promise<FileSystemDirectoryHandle | null>`
  - `verifyPermission(dir: FileSystemDirectoryHandle, mode: "read" | "readwrite"): Promise<boolean>`
  - `vaultExists(dir: FileSystemDirectoryHandle): Promise<boolean>`
  - `readVault(dir: FileSystemDirectoryHandle): Promise<VaultFile>`
  - `writeVault(dir: FileSystemDirectoryHandle, bytes: Uint8Array): Promise<void>`

**폴더 핸들을 쓰는 이유:** `FileSystemFileHandle` 하나로는 같은 폴더에 `salary.enc.bak`을 만들 수 없다. 부모 폴더 핸들이 필요하다.

- [ ] **Step 1: 실패하는 테스트를 작성한다**

`frontend/src/salary/__tests__/vault.test.ts`:

```typescript
// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from "vitest";
import { readVault, writeVault, vaultExists } from "../vault";
import { BACKUP_FILENAME, VAULT_FILENAME } from "../types";

/** File System Access API를 흉내내는 최소 구현 */
function makeFakeDir(initial: Record<string, Uint8Array> = {}) {
  const files = new Map<string, Uint8Array>(Object.entries(initial));
  const writeOrder: string[] = [];
  const failOn = { name: null as string | null };

  const dir = {
    files,
    writeOrder,
    failOn,
    async getFileHandle(name: string, opts?: { create?: boolean }) {
      if (!files.has(name) && !opts?.create) {
        const err = new Error("not found");
        err.name = "NotFoundError";
        throw err;
      }
      return {
        async getFile() {
          return {
            lastModified: 1_700_000_000_000,
            async arrayBuffer() {
              const data = files.get(name) ?? new Uint8Array();
              return data.buffer.slice(
                data.byteOffset,
                data.byteOffset + data.byteLength,
              );
            },
          };
        },
        async createWritable() {
          return {
            async write(data: Uint8Array) {
              if (failOn.name === name) throw new Error("USB removed");
              files.set(name, new Uint8Array(data));
              writeOrder.push(name);
            },
            async close() {},
          };
        },
      };
    },
  };
  return dir as unknown as FileSystemDirectoryHandle & typeof dir;
}

describe("vault", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("salary.enc 유무를 판별한다", async () => {
    const empty = makeFakeDir();
    const filled = makeFakeDir({ [VAULT_FILENAME]: new Uint8Array([1, 2, 3]) });
    await expect(vaultExists(empty)).resolves.toBe(false);
    await expect(vaultExists(filled)).resolves.toBe(true);
  });

  it("파일 내용과 lastModified를 함께 읽는다", async () => {
    const dir = makeFakeDir({ [VAULT_FILENAME]: new Uint8Array([9, 8, 7]) });
    const result = await readVault(dir);
    expect(Array.from(result.bytes)).toEqual([9, 8, 7]);
    expect(result.lastModified).toBe(1_700_000_000_000);
  });

  it(".bak을 원본 덮어쓰기보다 먼저 쓴다", async () => {
    const dir = makeFakeDir({ [VAULT_FILENAME]: new Uint8Array([1, 1, 1]) });
    await writeVault(dir, new Uint8Array([2, 2, 2]));
    expect(dir.writeOrder).toEqual([BACKUP_FILENAME, VAULT_FILENAME]);
  });

  it(".bak에는 새 내용이 아니라 저장 직전의 원본이 들어간다", async () => {
    const dir = makeFakeDir({ [VAULT_FILENAME]: new Uint8Array([1, 1, 1]) });
    await writeVault(dir, new Uint8Array([2, 2, 2]));
    expect(Array.from(dir.files.get(BACKUP_FILENAME)!)).toEqual([1, 1, 1]);
    expect(Array.from(dir.files.get(VAULT_FILENAME)!)).toEqual([2, 2, 2]);
  });

  it("원본이 없으면 백업 없이 새로 만든다", async () => {
    const dir = makeFakeDir();
    await writeVault(dir, new Uint8Array([5]));
    expect(dir.writeOrder).toEqual([VAULT_FILENAME]);
  });

  it("원본 쓰기 중 예외가 나면 .bak이 남아 복구할 수 있다", async () => {
    const dir = makeFakeDir({ [VAULT_FILENAME]: new Uint8Array([1, 1, 1]) });
    dir.failOn.name = VAULT_FILENAME;
    await expect(writeVault(dir, new Uint8Array([2, 2, 2]))).rejects.toThrow();
    expect(Array.from(dir.files.get(BACKUP_FILENAME)!)).toEqual([1, 1, 1]);
  });
});
```

- [ ] **Step 2: 테스트가 실패하는지 확인한다**

Run: `cd frontend && npx vitest run src/salary/__tests__/vault.test.ts`
Expected: FAIL — `Failed to resolve import "../vault"`

- [ ] **Step 3: 파일 입출력 모듈을 구현한다**

`frontend/src/salary/vault.ts`:

```typescript
/**
 * 연봉 금고 파일 입출력 — 스펙 §6.2.
 * 암호를 모른다. 바이트만 옮긴다.
 */
import { BACKUP_FILENAME, VAULT_FILENAME } from "./types";

export interface VaultFile {
  bytes: Uint8Array;
  lastModified: number;
}

const DB_NAME = "insa-salary";
const STORE_NAME = "handles";
const HANDLE_KEY = "vault-directory";

export function isFileSystemAccessSupported(): boolean {
  return typeof window !== "undefined" && "showDirectoryPicker" in window;
}

export async function pickVaultDirectory(): Promise<FileSystemDirectoryHandle> {
  const picker = (
    window as unknown as {
      showDirectoryPicker: (opts: { mode: string }) => Promise<FileSystemDirectoryHandle>;
    }
  ).showDirectoryPicker;
  return picker({ mode: "readwrite" });
}

function openDb(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, 1);
    request.onupgradeneeded = () => {
      request.result.createObjectStore(STORE_NAME);
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

export async function saveHandle(dir: FileSystemDirectoryHandle): Promise<void> {
  const db = await openDb();
  await new Promise<void>((resolve, reject) => {
    const tx = db.transaction(STORE_NAME, "readwrite");
    tx.objectStore(STORE_NAME).put(dir, HANDLE_KEY);
    tx.oncomplete = () => resolve();
    tx.onerror = () => reject(tx.error);
  });
  db.close();
}

export async function loadHandle(): Promise<FileSystemDirectoryHandle | null> {
  try {
    const db = await openDb();
    const handle = await new Promise<FileSystemDirectoryHandle | null>(
      (resolve, reject) => {
        const tx = db.transaction(STORE_NAME, "readonly");
        const request = tx.objectStore(STORE_NAME).get(HANDLE_KEY);
        request.onsuccess = () => resolve(request.result ?? null);
        request.onerror = () => reject(request.error);
      },
    );
    db.close();
    return handle;
  } catch (error) {
    console.error("금고 폴더 핸들을 복원하지 못했습니다:", error);
    return null;
  }
}

export async function verifyPermission(
  dir: FileSystemDirectoryHandle,
  mode: "read" | "readwrite",
): Promise<boolean> {
  const handle = dir as unknown as {
    queryPermission: (o: { mode: string }) => Promise<PermissionState>;
    requestPermission: (o: { mode: string }) => Promise<PermissionState>;
  };
  if ((await handle.queryPermission({ mode })) === "granted") return true;
  return (await handle.requestPermission({ mode })) === "granted";
}

export async function vaultExists(dir: FileSystemDirectoryHandle): Promise<boolean> {
  try {
    await dir.getFileHandle(VAULT_FILENAME);
    return true;
  } catch {
    return false;
  }
}

export async function readVault(dir: FileSystemDirectoryHandle): Promise<VaultFile> {
  const handle = await dir.getFileHandle(VAULT_FILENAME);
  const file = await handle.getFile();
  return {
    bytes: new Uint8Array(await file.arrayBuffer()),
    lastModified: file.lastModified,
  };
}

async function writeFile(
  dir: FileSystemDirectoryHandle,
  name: string,
  bytes: Uint8Array,
): Promise<void> {
  const handle = await dir.getFileHandle(name, { create: true });
  const writable = await handle.createWritable();
  try {
    await writable.write(bytes);
  } finally {
    await writable.close();
  }
}

/**
 * .bak을 반드시 먼저 쓴다. .bak의 내용은 "저장 직전의 원본"이다.
 * 원본 쓰기 도중 USB가 분리되어도 .bak에 정상 데이터가 남는다.
 */
export async function writeVault(
  dir: FileSystemDirectoryHandle,
  bytes: Uint8Array,
): Promise<void> {
  if (await vaultExists(dir)) {
    const previous = await readVault(dir);
    await writeFile(dir, BACKUP_FILENAME, previous.bytes);
  }
  await writeFile(dir, VAULT_FILENAME, bytes);
}
```

- [ ] **Step 4: 테스트가 통과하는지 확인한다**

Run: `cd frontend && npx vitest run src/salary/__tests__/vault.test.ts`
Expected: PASS — 6 tests passed

- [ ] **Step 5: 커밋한다**

```bash
git add frontend/src/salary/vault.ts frontend/src/salary/__tests__/vault.test.ts
git commit -m "feat(salary): USB 폴더 핸들 기반 파일 입출력과 .bak 백업"
```

---

## Task 3: 감사 로그 모델과 마이그레이션

**Files:**
- Modify: `backend/app/db/models.py` (파일 끝에 추가)
- Create: `backend/alembic/versions/20260819_0001_salary_access_log.py`
- Test: `backend/tests/test_salary_audit.py`

**Interfaces:**
- Consumes: 기존 `Base`, `insa_user` 테이블
- Produces: `SalaryAccessLog` ORM 모델 (`insa_salary_access_log`)

- [ ] **Step 1: 금지 필드 회귀 테스트를 먼저 작성한다**

`backend/tests/test_salary_audit.py`:

```python
"""연봉 감사 로그 — 스펙 §10."""

FORBIDDEN_COLUMNS = {
    "emp_id",
    "emp_no",
    "emp_name",
    "employee_id",
    "annual_salary",
    "raise_rate",
    "note",
    "password",
    "file_path",
    "salt",
    "iv",
}


def test_access_log_has_no_salary_columns():
    """연봉 데이터는 서버 스키마에 존재조차 하지 않아야 한다."""
    from app.db.models import SalaryAccessLog

    columns = {c.name for c in SalaryAccessLog.__table__.columns}
    assert columns & FORBIDDEN_COLUMNS == set()


def test_access_log_table_name():
    from app.db.models import SalaryAccessLog

    assert SalaryAccessLog.__tablename__ == "insa_salary_access_log"
```

- [ ] **Step 2: 테스트가 실패하는지 확인한다**

Run: `cd backend && python -m pytest tests/test_salary_audit.py -v`
Expected: FAIL — `ImportError: cannot import name 'SalaryAccessLog'`

- [ ] **Step 3: 모델을 추가한다**

`backend/app/db/models.py` 파일 맨 끝에 추가:

```python
class SalaryAccessLog(Base):
    """연봉 금고 접근 기록.

    금액·직원명·사번 컬럼을 의도적으로 두지 않는다. 다면평가 익명성과 같은 방식으로
    스키마 차원에서 저장을 불가능하게 만든다. 스펙 §10.2 참조.
    """

    __tablename__ = "insa_salary_access_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("insa_user.id"), nullable=False)
    # OPEN / UNLOCK_FAIL / SAVE / CREATE_VAULT / LOCK / PASSWORD_CHANGE
    # / DELEGATE / IP_DENIED / POLICY_CHANGE
    action = Column(String(20), nullable=False)
    # DELEGATE일 때의 후임자. 연봉 데이터가 아니라 접근 통제 메타데이터다.
    target_user_id = Column(Integer, ForeignKey("insa_user.id"), nullable=True)
    # 레코드 "건수"이며 금액이 아니다.
    record_count = Column(Integer, nullable=True)
    ip_address = Column(String(45), nullable=True)
    user_agent = Column(String(255), nullable=True)
    occurred_at = Column(DateTime, nullable=False, server_default=func.now())
```

`models.py` 상단은 이미 `Boolean`, `Column`, `DateTime`, `ForeignKey`, `Integer`, `String`, `func`를 import하고 있다. import를 추가할 필요가 없다.

- [ ] **Step 4: 테스트가 통과하는지 확인한다**

Run: `cd backend && python -m pytest tests/test_salary_audit.py -v`
Expected: PASS — 2 passed

- [ ] **Step 5: Alembic 마이그레이션을 작성한다**

먼저 현재 head를 확인한다:

```bash
cd backend && ls -t alembic/versions/*.py | head -1
```

`backend/alembic/versions/20260819_0001_salary_access_log.py`:

```python
"""add insa_salary_access_log table

연봉 금고 접근 기록. 금액·직원명 컬럼은 의도적으로 없다 (스펙 §10.2).

Revision ID: 20260819_0001
Revises: 20260506_0001
Create Date: 2026-08-19
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "20260819_0001"
down_revision: Union[str, None] = "20260506_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "insa_salary_access_log",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("insa_user.id"), nullable=False),
        sa.Column("action", sa.String(20), nullable=False),
        sa.Column(
            "target_user_id", sa.Integer(), sa.ForeignKey("insa_user.id"), nullable=True
        ),
        sa.Column("record_count", sa.Integer(), nullable=True),
        sa.Column("ip_address", sa.String(45), nullable=True),
        sa.Column("user_agent", sa.String(255), nullable=True),
        sa.Column("occurred_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index(
        "ix_salary_access_log_user_occurred",
        "insa_salary_access_log",
        ["user_id", "occurred_at"],
    )
    op.create_index(
        "ix_salary_access_log_occurred", "insa_salary_access_log", ["occurred_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_salary_access_log_occurred", table_name="insa_salary_access_log")
    op.drop_index(
        "ix_salary_access_log_user_occurred", table_name="insa_salary_access_log"
    )
    op.drop_table("insa_salary_access_log")
```

`down_revision`은 Step 5 처음에 확인한 실제 최신 revision id로 맞춘다.

- [ ] **Step 6: 전체 백엔드 테스트가 깨지지 않았는지 확인한다**

Run: `cd backend && python -m pytest -q`
Expected: 기존 테스트 전부 통과 + 신규 2개 통과

- [ ] **Step 7: 커밋한다**

```bash
git add backend/app/db/models.py backend/alembic/versions/20260819_0001_salary_access_log.py backend/tests/test_salary_audit.py
git commit -m "feat(salary): insa_salary_access_log 테이블 + 금지 필드 회귀 테스트"
```

---

## Task 4: 감사 로그 API

**Files:**
- Create: `backend/app/schemas/salary_audit.py`
- Create: `backend/app/api/v1/salary_audit.py`
- Modify: `backend/app/api/v1/router.py`
- Test: `backend/tests/test_salary_audit.py` (Task 3에서 만든 파일에 추가)

**Interfaces:**
- Consumes: `SalaryAccessLog` (Task 3), `require_roles` (`app/core/deps.py:34`)
- Produces:
  - `POST /api/v1/salary/access-logs` — `SYSTEM_ADMIN`, `HR_ADMIN`
  - `GET /api/v1/salary/access-logs` — `SYSTEM_ADMIN` 전용
  - `AccessLogCreate`, `AccessLogRow`, `AccessLogListResponse` 스키마
  - `log_access(db, user_id, action, request, target_user_id, record_count)` 헬퍼 — Task 6에서 재사용

- [ ] **Step 1: conftest에 SYSTEM_ADMIN 픽스처를 추가한다**

기존 `backend/tests/conftest.py`에는 `HR_ADMIN` 픽스처만 있다. 파일 끝에 추가:

```python
@pytest.fixture
def system_admin_user(db_session):
    role = Role(code="SYSTEM_ADMIN", name="시스템 관리자")
    db_session.add(role)
    db_session.flush()

    user = User(
        login_id="sysadmin",
        password_hash=hash_password("password123"),
        is_active=True,
    )
    db_session.add(user)
    db_session.flush()

    db_session.add(UserRole(user_id=user.id, role_id=role.id))
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture
def system_admin_headers(system_admin_user):
    token = create_access_token(
        str(system_admin_user.id), extra={"roles": ["SYSTEM_ADMIN"]}
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def plain_user(db_session):
    role = Role(code="EMPLOYEE", name="일반 직원")
    db_session.add(role)
    db_session.flush()

    user = User(
        login_id="employee",
        password_hash=hash_password("password123"),
        is_active=True,
    )
    db_session.add(user)
    db_session.flush()

    db_session.add(UserRole(user_id=user.id, role_id=role.id))
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture
def plain_headers(plain_user):
    token = create_access_token(str(plain_user.id), extra={"roles": ["EMPLOYEE"]})
    return {"Authorization": f"Bearer {token}"}
```

- [ ] **Step 2: 실패하는 API 테스트를 작성한다**

`backend/tests/test_salary_audit.py` 끝에 추가:

```python
def test_employee_cannot_post_log(client, plain_headers):
    res = client.post(
        "/api/v1/salary/access-logs",
        json={"action": "OPEN", "record_count": 3},
        headers=plain_headers,
    )
    assert res.status_code == 403


def test_hr_admin_can_post_log(client, auth_headers):
    res = client.post(
        "/api/v1/salary/access-logs",
        json={"action": "OPEN", "record_count": 3},
        headers=auth_headers,
    )
    assert res.status_code == 201


def test_server_fills_user_and_time_ignoring_client(client, auth_headers, admin_user):
    """클라이언트가 보낸 user_id·occurred_at은 무시하고 서버 값을 쓴다."""
    res = client.post(
        "/api/v1/salary/access-logs",
        json={
            "action": "SAVE",
            "record_count": 5,
            "user_id": 99999,
            "occurred_at": "1999-01-01T00:00:00",
        },
        headers=auth_headers,
    )
    assert res.status_code == 201
    body = res.json()
    assert body["user_id"] == admin_user.id
    assert not body["occurred_at"].startswith("1999")


def test_delegate_stores_target_user(client, auth_headers, system_admin_user):
    res = client.post(
        "/api/v1/salary/access-logs",
        json={"action": "DELEGATE", "target_user_id": system_admin_user.id},
        headers=auth_headers,
    )
    assert res.status_code == 201
    assert res.json()["target_user_id"] == system_admin_user.id


def test_target_user_id_rejected_for_non_delegate(client, auth_headers, system_admin_user):
    res = client.post(
        "/api/v1/salary/access-logs",
        json={"action": "OPEN", "target_user_id": system_admin_user.id},
        headers=auth_headers,
    )
    assert res.status_code == 422


def test_unknown_target_user_rejected(client, auth_headers):
    res = client.post(
        "/api/v1/salary/access-logs",
        json={"action": "DELEGATE", "target_user_id": 987654},
        headers=auth_headers,
    )
    assert res.status_code == 400


def test_invalid_action_rejected(client, auth_headers):
    res = client.post(
        "/api/v1/salary/access-logs",
        json={"action": "NOT_A_REAL_ACTION"},
        headers=auth_headers,
    )
    assert res.status_code == 422


def test_hr_admin_cannot_read_logs(client, auth_headers):
    """본인이 본인 감사 기록을 관리하면 감사가 아니다."""
    res = client.get("/api/v1/salary/access-logs", headers=auth_headers)
    assert res.status_code == 403


def test_system_admin_can_read_logs(client, auth_headers, system_admin_headers):
    client.post(
        "/api/v1/salary/access-logs",
        json={"action": "OPEN", "record_count": 1},
        headers=auth_headers,
    )
    res = client.get("/api/v1/salary/access-logs", headers=system_admin_headers)
    assert res.status_code == 200
    assert res.json()["total"] >= 1


def test_log_response_has_no_forbidden_fields(client, auth_headers, system_admin_headers):
    client.post(
        "/api/v1/salary/access-logs",
        json={"action": "OPEN", "record_count": 1},
        headers=auth_headers,
    )
    res = client.get("/api/v1/salary/access-logs", headers=system_admin_headers)
    for row in res.json()["items"]:
        assert set(row.keys()) & FORBIDDEN_COLUMNS == set()
```

- [ ] **Step 3: 테스트가 실패하는지 확인한다**

Run: `cd backend && python -m pytest tests/test_salary_audit.py -v`
Expected: FAIL — 404 (라우터 없음)

- [ ] **Step 4: 스키마를 작성한다**

`backend/app/schemas/salary_audit.py`:

```python
from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, model_validator

SalaryAction = Literal[
    "OPEN",
    "UNLOCK_FAIL",
    "SAVE",
    "CREATE_VAULT",
    "LOCK",
    "PASSWORD_CHANGE",
    "DELEGATE",
    "IP_DENIED",
    "POLICY_CHANGE",
]


class AccessLogCreate(BaseModel):
    """클라이언트가 보낼 수 있는 값은 이 셋뿐이다.

    user_id·ip_address·user_agent·occurred_at은 서버가 채운다.
    """

    action: SalaryAction
    record_count: Optional[int] = None
    target_user_id: Optional[int] = None

    @model_validator(mode="after")
    def target_only_for_delegate(self) -> "AccessLogCreate":
        if self.target_user_id is not None and self.action != "DELEGATE":
            raise ValueError("target_user_id는 DELEGATE에만 사용할 수 있습니다")
        return self


class AccessLogRow(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    action: str
    target_user_id: Optional[int]
    record_count: Optional[int]
    ip_address: Optional[str]
    user_agent: Optional[str]
    occurred_at: datetime


class AccessLogListResponse(BaseModel):
    items: list[AccessLogRow]
    total: int
```

- [ ] **Step 5: 라우터를 작성한다**

`backend/app/api/v1/salary_audit.py`:

```python
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.core.deps import require_roles
from app.db.models import SalaryAccessLog, User
from app.db.session import get_db
from app.schemas.salary_audit import (
    AccessLogCreate,
    AccessLogListResponse,
    AccessLogRow,
)

router = APIRouter(prefix="/salary", tags=["salary"])


def client_ip(request: Request) -> Optional[str]:
    """nginx 뒤에서도 실제 클라이언트 IP를 얻는다.

    uvicorn을 --proxy-headers로 띄우면 request.client.host가 이미
    X-Forwarded-For의 첫 값으로 치환되어 있다.
    """
    return request.client.host if request.client else None


def log_access(
    db: Session,
    *,
    user_id: int,
    action: str,
    request: Request,
    target_user_id: Optional[int] = None,
    record_count: Optional[int] = None,
) -> SalaryAccessLog:
    """다른 라우터(IP 정책)에서도 재사용한다."""
    row = SalaryAccessLog(
        user_id=user_id,
        action=action,
        target_user_id=target_user_id,
        record_count=record_count,
        ip_address=client_ip(request),
        user_agent=(request.headers.get("user-agent") or "")[:255] or None,
        occurred_at=datetime.now(),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.post(
    "/access-logs", response_model=AccessLogRow, status_code=status.HTTP_201_CREATED
)
def create_access_log(
    data: AccessLogCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles("SYSTEM_ADMIN", "HR_ADMIN")),
) -> AccessLogRow:
    if data.target_user_id is not None:
        exists = db.query(User).filter(User.id == data.target_user_id).first()
        if exists is None:
            raise HTTPException(status_code=400, detail="후임자를 찾을 수 없습니다")

    row = log_access(
        db,
        user_id=current_user.id,
        action=data.action,
        request=request,
        target_user_id=data.target_user_id,
        record_count=data.record_count,
    )
    return AccessLogRow.model_validate(row)


@router.get("/access-logs", response_model=AccessLogListResponse)
def list_access_logs(
    user_id: Optional[int] = Query(None),
    action: Optional[str] = Query(None),
    limit: int = Query(100, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    _: User = Depends(require_roles("SYSTEM_ADMIN")),
) -> AccessLogListResponse:
    query = db.query(SalaryAccessLog)
    if user_id is not None:
        query = query.filter(SalaryAccessLog.user_id == user_id)
    if action is not None:
        query = query.filter(SalaryAccessLog.action == action)

    total = query.count()
    rows = (
        query.order_by(desc(SalaryAccessLog.occurred_at))
        .offset(offset)
        .limit(limit)
        .all()
    )
    return AccessLogListResponse(
        items=[AccessLogRow.model_validate(r) for r in rows], total=total
    )
```

- [ ] **Step 6: 라우터를 등록한다**

`backend/app/api/v1/router.py`의 import 블록에 알파벳 순서로 추가:

```python
from app.api.v1.salary_audit import router as salary_audit_router
```

그리고 `api_router.include_router(...)` 목록 끝부분에 추가:

```python
api_router.include_router(salary_audit_router)
```

- [ ] **Step 7: 테스트가 통과하는지 확인한다**

Run: `cd backend && python -m pytest tests/test_salary_audit.py -v`
Expected: PASS — 12 passed

- [ ] **Step 8: 커밋한다**

```bash
git add backend/app/schemas/salary_audit.py backend/app/api/v1/salary_audit.py backend/app/api/v1/router.py backend/tests/conftest.py backend/tests/test_salary_audit.py
git commit -m "feat(salary): 감사 로그 API + 역할 가드"
```

---

## Task 5: IP 정책 모델과 마이그레이션

**Files:**
- Modify: `backend/app/db/models.py`
- Create: `backend/alembic/versions/20260819_0002_salary_vault_policy.py`
- Test: `backend/tests/test_salary_policy.py`

**Interfaces:**
- Consumes: 기존 `Base`, `insa_user`
- Produces: `SalaryVaultPolicy` ORM 모델 (`insa_salary_vault_policy`)

- [ ] **Step 1: 실패하는 테스트를 작성한다**

`backend/tests/test_salary_policy.py`:

```python
"""연봉 금고 IP 접근 정책 — 스펙 §9.2."""


def test_policy_table_name_and_columns():
    from app.db.models import SalaryVaultPolicy

    assert SalaryVaultPolicy.__tablename__ == "insa_salary_vault_policy"
    columns = {c.name for c in SalaryVaultPolicy.__table__.columns}
    assert {"owner_user_id", "allowed_ip", "is_active", "updated_by", "updated_at"} <= columns
```

- [ ] **Step 2: 테스트가 실패하는지 확인한다**

Run: `cd backend && python -m pytest tests/test_salary_policy.py -v`
Expected: FAIL — `ImportError: cannot import name 'SalaryVaultPolicy'`

- [ ] **Step 3: 모델을 추가한다**

`backend/app/db/models.py` 파일 맨 끝, `SalaryAccessLog` 다음에 추가:

```python
class SalaryVaultPolicy(Base):
    """연봉 금고를 열 수 있는 담당자와 허용 IP.

    활성 행은 1개만 존재한다 (담당자 1명 전제). 스펙 §9.2.2 참조.
    """

    __tablename__ = "insa_salary_vault_policy"

    id = Column(Integer, primary_key=True, autoincrement=True)
    owner_user_id = Column(
        Integer, ForeignKey("insa_user.id"), nullable=False, unique=True
    )
    allowed_ip = Column(String(45), nullable=False)
    is_active = Column(Boolean, nullable=False, default=True)
    updated_by = Column(Integer, ForeignKey("insa_user.id"), nullable=False)
    updated_at = Column(DateTime, nullable=False, server_default=func.now())
```

- [ ] **Step 4: 테스트가 통과하는지 확인한다**

Run: `cd backend && python -m pytest tests/test_salary_policy.py -v`
Expected: PASS — 1 passed

- [ ] **Step 5: Alembic 마이그레이션을 작성한다**

`backend/alembic/versions/20260819_0002_salary_vault_policy.py`:

```python
"""add insa_salary_vault_policy table

연봉 금고 허용 IP 정책. 활성 행은 1개만 존재한다 (스펙 §9.2.2).

Revision ID: 20260819_0002
Revises: 20260819_0001
Create Date: 2026-08-19
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "20260819_0002"
down_revision: Union[str, None] = "20260819_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "insa_salary_vault_policy",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "owner_user_id",
            sa.Integer(),
            sa.ForeignKey("insa_user.id"),
            nullable=False,
            unique=True,
        ),
        sa.Column("allowed_ip", sa.String(45), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("updated_by", sa.Integer(), sa.ForeignKey("insa_user.id"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("insa_salary_vault_policy")
```

- [ ] **Step 6: 전체 백엔드 테스트를 돌린다**

Run: `cd backend && python -m pytest -q`
Expected: 전부 통과

- [ ] **Step 7: 커밋한다**

```bash
git add backend/app/db/models.py backend/alembic/versions/20260819_0002_salary_vault_policy.py backend/tests/test_salary_policy.py
git commit -m "feat(salary): insa_salary_vault_policy 테이블"
```

---

## Task 6: IP 정책 API

**Files:**
- Create: `backend/app/schemas/salary_policy.py`
- Create: `backend/app/api/v1/salary_policy.py`
- Modify: `backend/app/api/v1/router.py`
- Test: `backend/tests/test_salary_policy.py` (Task 5 파일에 추가)

**Interfaces:**
- Consumes: `SalaryVaultPolicy` (Task 5), `log_access` (Task 4의 `salary_audit.py`), `require_roles`
- Produces:
  - `GET /api/v1/salary/policy/check` → `{"allowed": bool, "current_ip": str|null, "configured": bool, "reason": str|null}`
  - `GET /api/v1/salary/policy` → `PolicyRow | null` (`SYSTEM_ADMIN`)
  - `PUT /api/v1/salary/policy` → `PolicyRow` (`SYSTEM_ADMIN`)

- [ ] **Step 1: 실패하는 테스트를 작성한다**

`backend/tests/test_salary_policy.py` 끝에 추가:

```python
def test_check_allows_when_policy_not_configured(client, auth_headers):
    """기본 거부로 하면 최초 설정 자체가 불가능해진다 (스펙 §9.2.4)."""
    res = client.get("/api/v1/salary/policy/check", headers=auth_headers)
    assert res.status_code == 200
    body = res.json()
    assert body["allowed"] is True
    assert body["configured"] is False


def test_hr_admin_cannot_write_policy(client, auth_headers, admin_user):
    res = client.put(
        "/api/v1/salary/policy",
        json={"owner_user_id": admin_user.id, "allowed_ip": "192.0.2.10"},
        headers=auth_headers,
    )
    assert res.status_code == 403


def test_system_admin_can_write_policy(client, system_admin_headers, admin_user):
    res = client.put(
        "/api/v1/salary/policy",
        json={"owner_user_id": admin_user.id, "allowed_ip": "192.0.2.10"},
        headers=system_admin_headers,
    )
    assert res.status_code == 200
    assert res.json()["allowed_ip"] == "192.0.2.10"


def test_policy_write_leaves_policy_change_log(
    client, system_admin_headers, admin_user, db_session
):
    from app.db.models import SalaryAccessLog

    client.put(
        "/api/v1/salary/policy",
        json={"owner_user_id": admin_user.id, "allowed_ip": "192.0.2.10"},
        headers=system_admin_headers,
    )
    logs = (
        db_session.query(SalaryAccessLog)
        .filter(SalaryAccessLog.action == "POLICY_CHANGE")
        .all()
    )
    assert len(logs) == 1


def test_invalid_ip_rejected(client, system_admin_headers, admin_user):
    res = client.put(
        "/api/v1/salary/policy",
        json={"owner_user_id": admin_user.id, "allowed_ip": "not-an-ip"},
        headers=system_admin_headers,
    )
    assert res.status_code == 422


def test_check_denies_from_other_ip(client, system_admin_headers, auth_headers, admin_user):
    """TestClient의 요청 IP는 testclient이므로 다른 IP를 등록하면 거부된다."""
    client.put(
        "/api/v1/salary/policy",
        json={"owner_user_id": admin_user.id, "allowed_ip": "192.0.2.10"},
        headers=system_admin_headers,
    )
    res = client.get("/api/v1/salary/policy/check", headers=auth_headers)
    assert res.status_code == 200
    assert res.json()["allowed"] is False


def test_denied_check_writes_ip_denied_log(
    client, system_admin_headers, auth_headers, admin_user, db_session
):
    from app.db.models import SalaryAccessLog

    client.put(
        "/api/v1/salary/policy",
        json={"owner_user_id": admin_user.id, "allowed_ip": "192.0.2.10"},
        headers=system_admin_headers,
    )
    client.get("/api/v1/salary/policy/check", headers=auth_headers)

    logs = (
        db_session.query(SalaryAccessLog)
        .filter(SalaryAccessLog.action == "IP_DENIED")
        .all()
    )
    assert len(logs) == 1


def test_check_allows_from_matching_ip(client, system_admin_headers, auth_headers, admin_user):
    """TestClient가 보고하는 IP를 그대로 등록하면 허용된다."""
    current = client.get("/api/v1/salary/policy/check", headers=auth_headers).json()
    client.put(
        "/api/v1/salary/policy",
        json={"owner_user_id": admin_user.id, "allowed_ip": current["current_ip"]},
        headers=system_admin_headers,
    )
    res = client.get("/api/v1/salary/policy/check", headers=auth_headers)
    assert res.json()["allowed"] is True
```

- [ ] **Step 2: 테스트가 실패하는지 확인한다**

Run: `cd backend && python -m pytest tests/test_salary_policy.py -v`
Expected: FAIL — 404 (라우터 없음)

- [ ] **Step 3: 스키마를 작성한다**

`backend/app/schemas/salary_policy.py`:

```python
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, field_validator


class PolicyUpsert(BaseModel):
    owner_user_id: int
    allowed_ip: str

    @field_validator("allowed_ip")
    @classmethod
    def valid_ip(cls, v: str) -> str:
        import ipaddress

        try:
            ipaddress.ip_address(v)
        except ValueError as exc:
            raise ValueError("올바른 IP 주소가 아닙니다") from exc
        return v


class PolicyRow(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    owner_user_id: int
    allowed_ip: str
    is_active: bool
    updated_by: int
    updated_at: datetime


class PolicyCheckResponse(BaseModel):
    allowed: bool
    current_ip: Optional[str]
    configured: bool
    reason: Optional[str] = None
```

`allowed_ip` 검증에 `ipaddress`를 쓰는 이유: TestClient는 `testclient`라는 IP가 아닌 문자열을 보고할 수 있다. 그 경우 위 `test_check_allows_from_matching_ip`가 422로 실패하므로, 실패하면 그 테스트에서 `current_ip` 대신 `"127.0.0.1"`을 등록하고 `client` 픽스처에 `TestClient(app, client=("127.0.0.1", 123))`을 지정하도록 conftest를 고친다.

- [ ] **Step 4: 라우터를 작성한다**

`backend/app/api/v1/salary_policy.py`:

```python
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.api.v1.salary_audit import client_ip, log_access
from app.core.deps import require_roles
from app.db.models import SalaryVaultPolicy, User
from app.db.session import get_db
from app.schemas.salary_policy import PolicyCheckResponse, PolicyRow, PolicyUpsert

router = APIRouter(prefix="/salary", tags=["salary"])


def _active_policy(db: Session) -> Optional[SalaryVaultPolicy]:
    return (
        db.query(SalaryVaultPolicy)
        .filter(SalaryVaultPolicy.is_active == True)  # noqa: E712
        .first()
    )


@router.get("/policy/check", response_model=PolicyCheckResponse)
def check_policy(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles("SYSTEM_ADMIN", "HR_ADMIN")),
) -> PolicyCheckResponse:
    ip = client_ip(request)
    policy = _active_policy(db)

    # 정책 미설정 상태에서 기본 거부로 하면 최초 설정 자체가 불가능해진다.
    if policy is None:
        return PolicyCheckResponse(allowed=True, current_ip=ip, configured=False)

    if policy.allowed_ip == ip:
        return PolicyCheckResponse(allowed=True, current_ip=ip, configured=True)

    log_access(db, user_id=current_user.id, action="IP_DENIED", request=request)
    return PolicyCheckResponse(
        allowed=False,
        current_ip=ip,
        configured=True,
        reason="이 자리에서는 연봉 금고를 열 수 없습니다.",
    )


@router.get("/policy", response_model=Optional[PolicyRow])
def get_policy(
    db: Session = Depends(get_db),
    _: User = Depends(require_roles("SYSTEM_ADMIN")),
) -> Optional[PolicyRow]:
    policy = _active_policy(db)
    return PolicyRow.model_validate(policy) if policy else None


@router.put("/policy", response_model=PolicyRow)
def upsert_policy(
    data: PolicyUpsert,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles("SYSTEM_ADMIN")),
) -> PolicyRow:
    owner = db.query(User).filter(User.id == data.owner_user_id).first()
    if owner is None:
        raise HTTPException(status_code=400, detail="담당자를 찾을 수 없습니다")

    policy = _active_policy(db)
    if policy is None:
        policy = SalaryVaultPolicy(
            owner_user_id=data.owner_user_id,
            allowed_ip=data.allowed_ip,
            is_active=True,
            updated_by=current_user.id,
            updated_at=datetime.now(),
        )
        db.add(policy)
    else:
        policy.owner_user_id = data.owner_user_id
        policy.allowed_ip = data.allowed_ip
        policy.updated_by = current_user.id
        policy.updated_at = datetime.now()

    db.commit()
    db.refresh(policy)

    log_access(
        db,
        user_id=current_user.id,
        action="POLICY_CHANGE",
        request=request,
        target_user_id=data.owner_user_id,
    )
    return PolicyRow.model_validate(policy)
```

`log_access`의 `target_user_id`는 `AccessLogCreate` 스키마의 `DELEGATE` 제약을 거치지 않는다. 그 제약은 클라이언트 입력 검증용이고, 여기서는 서버가 직접 ORM을 만든다. 정책 변경 대상 담당자를 남기는 것이 감사에 유용하므로 그대로 둔다.

- [ ] **Step 5: 라우터를 등록한다**

`backend/app/api/v1/router.py` import 블록에 추가:

```python
from app.api.v1.salary_policy import router as salary_policy_router
```

include 목록에 추가:

```python
api_router.include_router(salary_policy_router)
```

- [ ] **Step 6: 테스트가 통과하는지 확인한다**

Run: `cd backend && python -m pytest tests/test_salary_policy.py -v`
Expected: PASS — 9 passed

`test_check_allows_from_matching_ip`가 422로 실패하면 Step 3 하단의 안내대로 conftest의 `client` 픽스처를 `TestClient(app, client=("127.0.0.1", 123))`로 고치고 테스트에서 `"127.0.0.1"`을 등록한다.

- [ ] **Step 7: 전체 백엔드 테스트를 돌린다**

Run: `cd backend && python -m pytest -q`
Expected: 전부 통과

- [ ] **Step 8: 커밋한다**

```bash
git add backend/app/schemas/salary_policy.py backend/app/api/v1/salary_policy.py backend/app/api/v1/router.py backend/tests/test_salary_policy.py
git commit -m "feat(salary): IP 접근 정책 API + IP_DENIED / POLICY_CHANGE 기록"
```

---

## Task 7: 프론트엔드 API 훅

**Files:**
- Create: `frontend/src/api/salaryAudit.ts`
- Create: `frontend/src/api/salaryPolicy.ts`

**Interfaces:**
- Consumes: Task 4·6의 엔드포인트, 기존 `apiClient` (`frontend/src/api/client.ts`)
- Produces:
  - `type SalaryAction`
  - `recordAccess(action: SalaryAction, opts?: { recordCount?: number; targetUserId?: number }): Promise<void>` — 실패해도 throw하지 않는다
  - `useAccessLogs(filters)` — React Query
  - `checkPolicy(): Promise<PolicyCheck>`
  - `usePolicy()`, `useUpsertPolicy()`
  - `interface PolicyCheck { allowed: boolean; current_ip: string | null; configured: boolean; reason: string | null }`

- [ ] **Step 1: 감사 로그 API 모듈을 만든다**

`frontend/src/api/salaryAudit.ts`:

```typescript
import { useQuery } from "@tanstack/react-query";
import apiClient from "./client";

export type SalaryAction =
  | "OPEN"
  | "UNLOCK_FAIL"
  | "SAVE"
  | "CREATE_VAULT"
  | "LOCK"
  | "PASSWORD_CHANGE"
  | "DELEGATE"
  | "IP_DENIED"
  | "POLICY_CHANGE";

export interface AccessLogRow {
  id: number;
  user_id: number;
  action: SalaryAction;
  target_user_id: number | null;
  record_count: number | null;
  ip_address: string | null;
  user_agent: string | null;
  occurred_at: string;
}

/**
 * 접근 기록을 남긴다. 1회 재시도하고, 실패해도 절대 throw하지 않는다.
 *
 * 파일은 INSA 밖에서도 열 수 있으므로 로그가 완전성을 보증하지 못한다.
 * 로그 서버 장애로 급여 업무가 멈추는 쪽이 더 나쁘다 (스펙 §10.4).
 */
export async function recordAccess(
  action: SalaryAction,
  opts?: { recordCount?: number; targetUserId?: number },
): Promise<void> {
  const body = {
    action,
    record_count: opts?.recordCount ?? null,
    target_user_id: opts?.targetUserId ?? null,
  };
  for (let attempt = 0; attempt < 2; attempt += 1) {
    try {
      await apiClient.post("/salary/access-logs", body);
      return;
    } catch (error) {
      if (attempt === 1) {
        console.error("연봉 접근 기록 전송에 실패했습니다:", error);
      }
    }
  }
}

export interface AccessLogFilters {
  userId?: number;
  action?: SalaryAction;
}

export function useAccessLogs(filters: AccessLogFilters) {
  return useQuery({
    queryKey: ["salary", "access-logs", filters],
    queryFn: async () => {
      const { data } = await apiClient.get<{
        items: AccessLogRow[];
        total: number;
      }>("/salary/access-logs", {
        params: { user_id: filters.userId, action: filters.action },
      });
      return data;
    },
  });
}
```

- [ ] **Step 2: IP 정책 API 모듈을 만든다**

`frontend/src/api/salaryPolicy.ts`:

```typescript
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import apiClient from "./client";

export interface PolicyCheck {
  allowed: boolean;
  current_ip: string | null;
  configured: boolean;
  reason: string | null;
}

export interface PolicyRow {
  id: number;
  owner_user_id: number;
  allowed_ip: string;
  is_active: boolean;
  updated_by: number;
  updated_at: string;
}

/**
 * 서버 장애로 급여 업무가 멈추면 안 되므로, 호출이 실패하면 허용으로 간주한다.
 * IP 제한은 어차피 소프트 제한이다 (스펙 §9.2.1, §11).
 */
export async function checkPolicy(): Promise<PolicyCheck> {
  try {
    const { data } = await apiClient.get<PolicyCheck>("/salary/policy/check");
    return data;
  } catch (error) {
    console.error("IP 정책 확인에 실패했습니다:", error);
    return {
      allowed: true,
      current_ip: null,
      configured: false,
      reason: "정책 확인 실패 — 서버에 연결할 수 없습니다.",
    };
  }
}

export function usePolicyCheck() {
  return useQuery({
    queryKey: ["salary", "policy", "check"],
    queryFn: checkPolicy,
    staleTime: 0,
  });
}

export function usePolicy() {
  return useQuery({
    queryKey: ["salary", "policy"],
    queryFn: async () => {
      const { data } = await apiClient.get<PolicyRow | null>("/salary/policy");
      return data;
    },
  });
}

export function useUpsertPolicy() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (input: { owner_user_id: number; allowed_ip: string }) => {
      const { data } = await apiClient.put<PolicyRow>("/salary/policy", input);
      return data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["salary", "policy"] });
    },
  });
}
```

- [ ] **Step 3: 타입 체크가 통과하는지 확인한다**

Run: `cd frontend && npx tsc --noEmit`
Expected: 0 errors

- [ ] **Step 4: 커밋한다**

```bash
git add frontend/src/api/salaryAudit.ts frontend/src/api/salaryPolicy.ts
git commit -m "feat(salary): 감사 로그 · IP 정책 API 훅"
```

---

## Task 8: 금고 상태 훅

**Files:**
- Create: `frontend/src/salary/useSalaryVault.ts`
- Test: `frontend/src/salary/__tests__/useSalaryVault.test.ts`

**Interfaces:**
- Consumes: Task 1 `crypto.ts`, Task 2 `vault.ts`, Task 7 `recordAccess`
- Produces:
  - `type VaultStatus = "DISCONNECTED" | "LOCKED" | "UNLOCKED" | "ERROR"`
  - `useSalaryVault()` 훅 반환값:
    - `status`, `records`, `dirty`, `errorMessage`, `lockCountdown`
    - `connect(): Promise<void>` — 폴더 선택
    - `unlock(password: string): Promise<void>`
    - `createVault(password: string): Promise<void>`
    - `lock(): void`
    - `save(): Promise<void>`
    - `upsertRecord(record: SalaryRecord): void`
    - `removeRecord(empId: number, year: number): void`
    - `reencrypt(newPassword: string, opts?: { targetUserId?: number }): Promise<void>`
    - `suspendAutoLock(suspended: boolean): void`

**자동 잠금:** 10분 무입력. 잠기기 30초 전부터 `lockCountdown`이 남은 초를 반환한다.

- [ ] **Step 1: 실패하는 테스트를 작성한다**

`frontend/src/salary/__tests__/useSalaryVault.test.ts`:

```typescript
// @vitest-environment jsdom
import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AUTO_LOCK_MS, useSalaryVault, WARN_BEFORE_MS } from "../useSalaryVault";

vi.mock("../../api/salaryAudit", () => ({
  recordAccess: vi.fn().mockResolvedValue(undefined),
}));

/**
 * 폴더 핸들이 이미 복원된 상태로 시작한다. loadHandle이 null을 주면
 * dirRef가 비어 createVault가 "USB 폴더가 선택되지 않았습니다"로 던진다.
 * vi.mock은 호이스팅되므로 팩토리 밖의 변수를 참조하면 안 된다.
 */
vi.mock("../vault", () => ({
  isFileSystemAccessSupported: () => true,
  pickVaultDirectory: vi.fn().mockResolvedValue({}),
  saveHandle: vi.fn().mockResolvedValue(undefined),
  loadHandle: vi.fn().mockResolvedValue({}),
  verifyPermission: vi.fn().mockResolvedValue(true),
  vaultExists: vi.fn().mockResolvedValue(false),
  readVault: vi.fn().mockResolvedValue({
    bytes: new Uint8Array(),
    lastModified: 1_700_000_000_000,
  }),
  writeVault: vi.fn().mockResolvedValue(undefined),
}));

/**
 * PBKDF2 210,000회를 테스트마다 돌리면 느리고, jsdom 환경에는 crypto.subtle이
 * 없을 수 있다. 이 훅의 관심사는 상태 전이이지 암호가 아니므로 모킹한다.
 * 암호 자체는 Task 1의 crypto.test.ts가 실제로 검증한다.
 */
vi.mock("../crypto", () => ({
  encryptVault: vi.fn().mockResolvedValue(new Uint8Array([1, 2, 3])),
  decryptVault: vi.fn().mockResolvedValue({
    schemaVersion: 1,
    updatedAt: "2026-08-19T00:00:00.000Z",
    records: [],
  }),
  parseHeader: vi.fn(),
  VaultDecryptError: class VaultDecryptError extends Error {},
  VaultFormatError: class VaultFormatError extends Error {},
}));

describe("useSalaryVault", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("초기 상태는 DISCONNECTED다", () => {
    const { result } = renderHook(() => useSalaryVault());
    expect(result.current.status).toBe("DISCONNECTED");
    expect(result.current.records).toEqual([]);
    expect(result.current.dirty).toBe(false);
  });

  it("AUTO_LOCK_MS는 10분, 경고는 30초 전이다", () => {
    expect(AUTO_LOCK_MS).toBe(10 * 60 * 1000);
    expect(WARN_BEFORE_MS).toBe(30 * 1000);
  });

  it("lock()은 상태를 LOCKED로 바꾸고 레코드를 비운다", async () => {
    const { result } = renderHook(() => useSalaryVault());
    await act(async () => {
      await result.current.createVault("password-1234");
    });
    expect(result.current.status).toBe("UNLOCKED");

    act(() => {
      result.current.lock();
    });
    expect(result.current.status).toBe("LOCKED");
    expect(result.current.records).toEqual([]);
  });

  it("무입력 10분이 지나면 자동으로 잠긴다", async () => {
    const { result } = renderHook(() => useSalaryVault());
    await act(async () => {
      await result.current.createVault("password-1234");
    });

    await act(async () => {
      vi.advanceTimersByTime(AUTO_LOCK_MS + 1000);
    });
    expect(result.current.status).toBe("LOCKED");
  });

  it("suspendAutoLock(true) 동안에는 잠기지 않는다", async () => {
    const { result } = renderHook(() => useSalaryVault());
    await act(async () => {
      await result.current.createVault("password-1234");
    });

    act(() => {
      result.current.suspendAutoLock(true);
    });
    await act(async () => {
      vi.advanceTimersByTime(AUTO_LOCK_MS + 1000);
    });
    expect(result.current.status).toBe("UNLOCKED");
  });

  it("upsertRecord는 원본을 변경하지 않고 dirty를 세운다", async () => {
    const { result } = renderHook(() => useSalaryVault());
    await act(async () => {
      await result.current.createVault("password-1234");
    });
    const before = result.current.records;

    act(() => {
      result.current.upsertRecord({
        empId: 1,
        empNo: "20200001",
        empName: "김철수",
        year: 2026,
        effectiveDate: "2026-01-01",
        annualSalary: 40_000_000,
        raiseRate: null,
        note: null,
      });
    });

    expect(before).toEqual([]);
    expect(result.current.records).toHaveLength(1);
    expect(result.current.dirty).toBe(true);
  });

  it("같은 (empId, year)를 다시 넣으면 교체된다", async () => {
    const { result } = renderHook(() => useSalaryVault());
    await act(async () => {
      await result.current.createVault("password-1234");
    });
    const base = {
      empId: 1,
      empNo: "20200001",
      empName: "김철수",
      year: 2026,
      effectiveDate: "2026-01-01",
      raiseRate: null,
      note: null,
    };

    act(() => {
      result.current.upsertRecord({ ...base, annualSalary: 40_000_000 });
    });
    act(() => {
      result.current.upsertRecord({ ...base, annualSalary: 45_000_000 });
    });

    expect(result.current.records).toHaveLength(1);
    expect(result.current.records[0].annualSalary).toBe(45_000_000);
  });
});
```

- [ ] **Step 2: 테스트가 실패하는지 확인한다**

Run: `cd frontend && npx vitest run src/salary/__tests__/useSalaryVault.test.ts`
Expected: FAIL — `Failed to resolve import "../useSalaryVault"`

- [ ] **Step 3: 훅을 구현한다**

`frontend/src/salary/useSalaryVault.ts`:

```typescript
import { useCallback, useEffect, useRef, useState } from "react";
import { recordAccess } from "../api/salaryAudit";
import { decryptVault, encryptVault, VaultDecryptError } from "./crypto";
import { makeEmptyVault, recordKey, type SalaryRecord, type VaultData } from "./types";
import {
  loadHandle,
  pickVaultDirectory,
  readVault,
  saveHandle,
  vaultExists,
  verifyPermission,
  writeVault,
} from "./vault";

export const AUTO_LOCK_MS = 10 * 60 * 1000;
export const WARN_BEFORE_MS = 30 * 1000;
const TICK_MS = 1000;

export type VaultStatus = "DISCONNECTED" | "LOCKED" | "UNLOCKED" | "ERROR";

export function useSalaryVault() {
  const [status, setStatus] = useState<VaultStatus>("DISCONNECTED");
  const [records, setRecords] = useState<SalaryRecord[]>([]);
  const [dirty, setDirty] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [lockCountdown, setLockCountdown] = useState<number | null>(null);

  const dirRef = useRef<FileSystemDirectoryHandle | null>(null);
  const passwordRef = useRef<string | null>(null);
  const loadedAtRef = useRef<number | null>(null);
  const lastActivityRef = useRef<number>(Date.now());
  const suspendedRef = useRef(false);

  /** 키와 평문을 모두 버린다. */
  const lock = useCallback(() => {
    passwordRef.current = null;
    setRecords([]);
    setDirty(false);
    setLockCountdown(null);
    setStatus((prev) => (prev === "DISCONNECTED" ? prev : "LOCKED"));
    void recordAccess("LOCK");
  }, []);

  const suspendAutoLock = useCallback((suspended: boolean) => {
    suspendedRef.current = suspended;
    lastActivityRef.current = Date.now();
  }, []);

  // 자동 잠금 타이머
  useEffect(() => {
    if (status !== "UNLOCKED") return undefined;

    const bump = () => {
      lastActivityRef.current = Date.now();
    };
    const events = ["keydown", "mousemove", "scroll", "click"] as const;
    events.forEach((e) => window.addEventListener(e, bump));

    const timer = setInterval(() => {
      if (suspendedRef.current) return;
      const idle = Date.now() - lastActivityRef.current;
      const remaining = AUTO_LOCK_MS - idle;
      if (remaining <= 0) {
        lock();
      } else if (remaining <= WARN_BEFORE_MS) {
        setLockCountdown(Math.ceil(remaining / 1000));
      } else {
        setLockCountdown(null);
      }
    }, TICK_MS);

    return () => {
      events.forEach((e) => window.removeEventListener(e, bump));
      clearInterval(timer);
    };
  }, [status, lock]);

  // 저장하지 않은 편집이 있으면 이탈을 경고한다
  useEffect(() => {
    if (!dirty) return undefined;
    const handler = (e: BeforeUnloadEvent) => {
      e.preventDefault();
      e.returnValue = "";
    };
    window.addEventListener("beforeunload", handler);
    return () => window.removeEventListener("beforeunload", handler);
  }, [dirty]);

  // 재접속 시 폴더 핸들을 복원한다
  useEffect(() => {
    void (async () => {
      const dir = await loadHandle();
      if (!dir) return;
      dirRef.current = dir;
      setStatus((await vaultExists(dir)) ? "LOCKED" : "DISCONNECTED");
    })();
  }, []);

  const connect = useCallback(async () => {
    try {
      const dir = await pickVaultDirectory();
      dirRef.current = dir;
      await saveHandle(dir);
      setErrorMessage(null);
      setStatus((await vaultExists(dir)) ? "LOCKED" : "DISCONNECTED");
    } catch (error) {
      console.error("USB 폴더 선택에 실패했습니다:", error);
      setErrorMessage("폴더를 선택하지 못했습니다.");
    }
  }, []);

  const unlock = useCallback(async (password: string) => {
    const dir = dirRef.current;
    if (!dir) throw new Error("USB 폴더가 선택되지 않았습니다");
    if (!(await verifyPermission(dir, "readwrite"))) {
      setErrorMessage("폴더 접근 권한이 필요합니다.");
      return;
    }

    const file = await readVault(dir);
    try {
      const data = await decryptVault(file.bytes, password);
      passwordRef.current = password;
      loadedAtRef.current = file.lastModified;
      lastActivityRef.current = Date.now();
      setRecords(data.records);
      setDirty(false);
      setErrorMessage(null);
      setStatus("UNLOCKED");
      void recordAccess("OPEN", { recordCount: data.records.length });
    } catch (error) {
      if (error instanceof VaultDecryptError) {
        setErrorMessage(error.message);
        void recordAccess("UNLOCK_FAIL");
        return;
      }
      setErrorMessage((error as Error).message);
      setStatus("ERROR");
    }
  }, []);

  const persist = useCallback(
    async (nextRecords: SalaryRecord[], password: string) => {
      const dir = dirRef.current;
      if (!dir) throw new Error("USB 폴더가 선택되지 않았습니다");

      const payload: VaultData = {
        schemaVersion: 1,
        updatedAt: new Date().toISOString(),
        records: nextRecords,
      };
      const bytes = await encryptVault(payload, password);
      await writeVault(dir, bytes);
      const after = await readVault(dir);
      loadedAtRef.current = after.lastModified;
    },
    [],
  );

  const createVault = useCallback(
    async (password: string) => {
      const empty = makeEmptyVault(new Date().toISOString());
      await persist(empty.records, password);
      passwordRef.current = password;
      lastActivityRef.current = Date.now();
      setRecords([]);
      setDirty(false);
      setErrorMessage(null);
      setStatus("UNLOCKED");
      void recordAccess("CREATE_VAULT", { recordCount: 0 });
    },
    [persist],
  );

  const save = useCallback(async () => {
    const dir = dirRef.current;
    const password = passwordRef.current;
    if (!dir || !password) throw new Error("금고가 열려 있지 않습니다");

    const current = await readVault(dir);
    if (loadedAtRef.current !== null && current.lastModified !== loadedAtRef.current) {
      setErrorMessage(
        "파일이 INSA 밖에서 변경되었습니다. 저장을 중단했습니다.",
      );
      setStatus("ERROR");
      return;
    }

    await persist(records, password);
    setDirty(false);
    void recordAccess("SAVE", { recordCount: records.length });
  }, [records, persist]);

  const upsertRecord = useCallback((record: SalaryRecord) => {
    setRecords((prev) => {
      const key = recordKey(record);
      const found = prev.some((r) => recordKey(r) === key);
      return found
        ? prev.map((r) => (recordKey(r) === key ? record : r))
        : [...prev, record];
    });
    setDirty(true);
    lastActivityRef.current = Date.now();
  }, []);

  const removeRecord = useCallback((empId: number, year: number) => {
    setRecords((prev) =>
      prev.filter((r) => !(r.empId === empId && r.year === year)),
    );
    setDirty(true);
    lastActivityRef.current = Date.now();
  }, []);

  /**
   * 비밀번호 변경과 담당자 위임이 공유하는 동작.
   * salt 인자 없이 encryptVault를 부르므로 salt가 새로 생성된다.
   */
  const reencrypt = useCallback(
    async (newPassword: string, opts?: { targetUserId?: number }) => {
      if (dirty) throw new Error("저장하지 않은 편집이 있습니다");
      await persist(records, newPassword);
      passwordRef.current = newPassword;
      if (opts?.targetUserId !== undefined) {
        void recordAccess("DELEGATE", { targetUserId: opts.targetUserId });
        lock();
      } else {
        void recordAccess("PASSWORD_CHANGE");
      }
    },
    [dirty, records, persist, lock],
  );

  return {
    status,
    records,
    dirty,
    errorMessage,
    lockCountdown,
    connect,
    unlock,
    createVault,
    lock,
    save,
    upsertRecord,
    removeRecord,
    reencrypt,
    suspendAutoLock,
  };
}
```

- [ ] **Step 4: 테스트가 통과하는지 확인한다**

Run: `cd frontend && npx vitest run src/salary/__tests__/useSalaryVault.test.ts`
Expected: PASS — 7 tests passed

- [ ] **Step 5: 커밋한다**

```bash
git add frontend/src/salary/useSalaryVault.ts frontend/src/salary/__tests__/useSalaryVault.test.ts
git commit -m "feat(salary): 금고 상태 기계 훅 + 10분 자동 잠금"
```

---

## Task 9: 연봉 화면 — 미연결 · 잠김 · 오류 · IP 거부

**Files:**
- Create: `frontend/src/pages/SalaryPage.tsx`
- Test: `frontend/src/pages/__tests__/SalaryPage.test.tsx`

**Interfaces:**
- Consumes: Task 8 `useSalaryVault`, Task 7 `usePolicyCheck`, 기존 `useAuthStore`
- Produces: `export default function SalaryPage()`

이 작업에서는 잠금 해제 이전 상태만 만든다. 테이블은 Task 10에서 붙인다.

- [ ] **Step 1: 실패하는 테스트를 작성한다**

`frontend/src/pages/__tests__/SalaryPage.test.tsx`:

```typescript
// @vitest-environment jsdom
/// <reference types="@testing-library/jest-dom/vitest" />
import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import SalaryPage from "../SalaryPage";
import { useAuthStore } from "../../store/auth";

const vaultMock = vi.hoisted(() => ({
  state: {
    status: "DISCONNECTED" as string,
    records: [] as unknown[],
    dirty: false,
    errorMessage: null as string | null,
    lockCountdown: null as number | null,
  },
}));

vi.mock("../../salary/useSalaryVault", () => ({
  AUTO_LOCK_MS: 600000,
  WARN_BEFORE_MS: 30000,
  useSalaryVault: () => ({
    ...vaultMock.state,
    connect: vi.fn(),
    unlock: vi.fn(),
    createVault: vi.fn(),
    lock: vi.fn(),
    save: vi.fn(),
    upsertRecord: vi.fn(),
    removeRecord: vi.fn(),
    reencrypt: vi.fn(),
    suspendAutoLock: vi.fn(),
  }),
}));

const policyMock = vi.hoisted(() => ({
  data: {
    allowed: true,
    current_ip: "192.0.2.10",
    configured: true,
    reason: null as string | null,
  },
}));

vi.mock("../../api/salaryPolicy", () => ({
  usePolicyCheck: () => ({ data: policyMock.data, isLoading: false }),
}));

vi.mock("../../salary/vault", () => ({
  isFileSystemAccessSupported: () => true,
}));

function renderPage() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <SalaryPage />
    </QueryClientProvider>,
  );
}

describe("SalaryPage — 잠금 해제 이전 상태", () => {
  it("역할이 없으면 권한 없음을 보여준다", () => {
    useAuthStore.setState({ roles: ["EMPLOYEE"] });
    renderPage();
    expect(screen.getByText(/권한이 없습니다/)).toBeInTheDocument();
  });

  it("미연결 상태에서 USB 폴더 선택 버튼을 보여준다", () => {
    useAuthStore.setState({ roles: ["HR_ADMIN"] });
    vaultMock.state.status = "DISCONNECTED";
    policyMock.data = {
      allowed: true,
      current_ip: "192.0.2.10",
      configured: true,
      reason: null,
    };
    renderPage();
    expect(screen.getByRole("button", { name: /USB 폴더 선택/ })).toBeInTheDocument();
  });

  it("허용되지 않은 IP에서는 비밀번호 입력란을 렌더링하지 않는다", () => {
    useAuthStore.setState({ roles: ["HR_ADMIN"] });
    vaultMock.state.status = "LOCKED";
    policyMock.data = {
      allowed: false,
      current_ip: "192.0.2.10",
      configured: true,
      reason: "이 자리에서는 연봉 금고를 열 수 없습니다.",
    };
    renderPage();
    expect(screen.queryByLabelText("비밀번호")).not.toBeInTheDocument();
    expect(screen.getByText(/192\.168\.0\.99/)).toBeInTheDocument();
  });

  it("허용된 IP의 잠김 상태에서는 비밀번호 입력란을 보여준다", () => {
    useAuthStore.setState({ roles: ["HR_ADMIN"] });
    vaultMock.state.status = "LOCKED";
    policyMock.data = {
      allowed: true,
      current_ip: "192.0.2.10",
      configured: true,
      reason: null,
    };
    renderPage();
    expect(screen.getByLabelText("비밀번호")).toBeInTheDocument();
  });

  it("오류 상태에서는 백업 복원 안내를 보여준다", () => {
    useAuthStore.setState({ roles: ["HR_ADMIN"] });
    vaultMock.state.status = "ERROR";
    vaultMock.state.errorMessage = "파일이 손상되었습니다.";
    renderPage();
    expect(screen.getByText(/salary\.enc\.bak/)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: 테스트가 실패하는지 확인한다**

Run: `cd frontend && npx vitest run src/pages/__tests__/SalaryPage.test.tsx`
Expected: FAIL — `Failed to resolve import "../SalaryPage"`

- [ ] **Step 3: 화면을 구현한다**

`frontend/src/pages/SalaryPage.tsx`:

```typescript
import { useState } from "react";
import { Alert, Button, Card, Empty, Input, Space, Typography } from "antd";
import { useAuthStore } from "../store/auth";
import { usePolicyCheck } from "../api/salaryPolicy";
import { useSalaryVault } from "../salary/useSalaryVault";
import { isFileSystemAccessSupported } from "../salary/vault";

const { Title, Paragraph, Text } = Typography;

const ALLOWED_ROLES = ["SYSTEM_ADMIN", "HR_ADMIN"];

export default function SalaryPage() {
  const roles = useAuthStore((s) => s.roles);
  const policy = usePolicyCheck();
  const vault = useSalaryVault();
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");

  if (!roles.some((r) => ALLOWED_ROLES.includes(r))) {
    return (
      <Card>
        <Empty description="연봉 관리 권한이 없습니다." />
      </Card>
    );
  }

  if (!isFileSystemAccessSupported()) {
    return (
      <Alert
        type="warning"
        showIcon
        message="Chrome 또는 Edge에서 이용해 주세요"
        description="이 기능은 File System Access API가 필요합니다. Firefox와 Safari는 지원하지 않습니다."
      />
    );
  }

  if (policy.data && !policy.data.allowed) {
    return (
      <Card>
        <Title level={4}>이 자리에서는 연봉 금고를 열 수 없습니다</Title>
        <Paragraph>
          현재 접속 IP: <Text strong>{policy.data.current_ip ?? "확인 불가"}</Text>
        </Paragraph>
        <Paragraph type="secondary">
          이 IP를 시스템 관리자에게 알려 허용 목록을 갱신하세요.
        </Paragraph>
      </Card>
    );
  }

  const header = (
    <Space direction="vertical" size={4} style={{ marginBottom: 24 }}>
      <Title level={3} style={{ margin: 0 }}>
        연봉 관리
      </Title>
      <Text type="secondary">
        연봉 데이터는 서버에 저장되지 않습니다. USB의 salary.enc 파일에만 있습니다.
      </Text>
    </Space>
  );

  if (vault.status === "ERROR") {
    return (
      <>
        {header}
        <Alert
          type="error"
          showIcon
          message="금고 파일을 열 수 없습니다"
          description={
            <>
              <Paragraph>{vault.errorMessage}</Paragraph>
              <Paragraph>
                같은 폴더의 <Text code>salary.enc.bak</Text> 파일이 저장 직전의 원본입니다.
                파일명을 <Text code>salary.enc</Text>로 바꾼 뒤 다시 시도하세요.
              </Paragraph>
            </>
          }
        />
      </>
    );
  }

  if (vault.status === "DISCONNECTED") {
    return (
      <>
        {header}
        <Card>
          <Empty
            description={
              <Space direction="vertical">
                <Text>연봉 금고가 있는 USB 폴더를 선택하세요.</Text>
                <Text type="secondary">
                  폴더에 salary.enc가 없으면 새 금고를 만들 수 있습니다.
                </Text>
              </Space>
            }
          >
            <Space direction="vertical" style={{ width: 280 }}>
              <Button type="primary" onClick={() => void vault.connect()}>
                USB 폴더 선택
              </Button>
              <Input.Password
                aria-label="새 금고 비밀번호"
                placeholder="새 금고 비밀번호"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
              <Input.Password
                aria-label="새 금고 비밀번호 확인"
                placeholder="비밀번호 확인"
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
              />
              <Button
                disabled={password.length < 8 || password !== confirmPassword}
                onClick={() => void vault.createVault(password)}
              >
                새 연봉 금고 만들기
              </Button>
              <Text type="secondary" style={{ fontSize: 12 }}>
                비밀번호를 잃어버리면 복구할 수 없습니다.
              </Text>
            </Space>
          </Empty>
        </Card>
      </>
    );
  }

  if (vault.status === "LOCKED") {
    return (
      <>
        {header}
        <Card style={{ maxWidth: 420 }}>
          <Space direction="vertical" style={{ width: "100%" }}>
            <Text>금고가 잠겨 있습니다. 비밀번호를 입력하세요.</Text>
            <Input.Password
              aria-label="비밀번호"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              onPressEnter={() => void vault.unlock(password)}
            />
            {vault.errorMessage && (
              <Alert type="error" showIcon message={vault.errorMessage} />
            )}
            <Button type="primary" block onClick={() => void vault.unlock(password)}>
              열기
            </Button>
          </Space>
        </Card>
      </>
    );
  }

  // UNLOCKED 상태는 Task 10에서 구현한다.
  return (
    <>
      {header}
      <Card>열림 상태 화면은 다음 작업에서 붙인다.</Card>
    </>
  );
}
```

- [ ] **Step 4: 테스트가 통과하는지 확인한다**

Run: `cd frontend && npx vitest run src/pages/__tests__/SalaryPage.test.tsx`
Expected: PASS — 5 tests passed

- [ ] **Step 5: 커밋한다**

```bash
git add frontend/src/pages/SalaryPage.tsx frontend/src/pages/__tests__/SalaryPage.test.tsx
git commit -m "feat(salary): 연봉 화면 미연결·잠김·오류·IP거부 상태"
```

---

## Task 10: 연봉 화면 — 열림 상태 테이블과 저장

**Files:**
- Modify: `frontend/src/pages/SalaryPage.tsx` (마지막 `return` 블록 교체)
- Create: `frontend/src/salary/SalaryRecordModal.tsx`
- Modify: `frontend/src/pages/__tests__/SalaryPage.test.tsx` (테스트 추가)

**Interfaces:**
- Consumes: Task 8 `useSalaryVault` (`records`, `dirty`, `save`, `upsertRecord`, `removeRecord`, `lock`), 기존 `useEmployees` (`frontend/src/api/employees.ts`)
- Produces: `SalaryRecordModal` 컴포넌트

**직원 목록 훅 (확인 완료):** `frontend/src/api/employees.ts`의 `useEmployees(params)`가 `{ items: Employee[]; total; page; page_size }`를 반환한다. `Employee`의 이름 필드는 `name_ko`이고 사번은 `emp_no`다.

- [ ] **Step 1: 실패하는 테스트를 추가한다**

`frontend/src/pages/__tests__/SalaryPage.test.tsx` 끝에 추가:

```typescript
describe("SalaryPage — 열림 상태", () => {
  it("연봉 레코드를 테이블에 보여준다", () => {
    useAuthStore.setState({ roles: ["HR_ADMIN"] });
    vaultMock.state.status = "UNLOCKED";
    vaultMock.state.errorMessage = null;
    vaultMock.state.records = [
      {
        empId: 1,
        empNo: "20200001",
        empName: "김철수",
        year: 2026,
        effectiveDate: "2026-01-01",
        annualSalary: 52_000_000,
        raiseRate: 4.5,
        note: null,
      },
    ];
    renderPage();
    expect(screen.getByText("김철수")).toBeInTheDocument();
    expect(screen.getByText("52,000,000")).toBeInTheDocument();
  });

  it("dirty가 아니면 저장 버튼이 비활성이다", () => {
    useAuthStore.setState({ roles: ["HR_ADMIN"] });
    vaultMock.state.status = "UNLOCKED";
    vaultMock.state.dirty = false;
    renderPage();
    expect(screen.getByRole("button", { name: "저장" })).toBeDisabled();
  });

  it("잠김 상태에서는 금액이 DOM에 없다", () => {
    useAuthStore.setState({ roles: ["HR_ADMIN"] });
    vaultMock.state.status = "LOCKED";
    renderPage();
    expect(screen.queryByText("52,000,000")).not.toBeInTheDocument();
  });

  it("자동 잠금 경고를 카운트다운으로 보여준다", () => {
    useAuthStore.setState({ roles: ["HR_ADMIN"] });
    vaultMock.state.status = "UNLOCKED";
    vaultMock.state.lockCountdown = 25;
    renderPage();
    expect(screen.getByText(/25초 후 자동으로 잠깁니다/)).toBeInTheDocument();
  });
});
```

- [ ] **Step 3: 테스트가 실패하는지 확인한다**

Run: `cd frontend && npx vitest run src/pages/__tests__/SalaryPage.test.tsx`
Expected: FAIL — 열림 상태 테스트 4개 실패

- [ ] **Step 4: 입력 모달을 만든다**

`frontend/src/salary/SalaryRecordModal.tsx`:

```typescript
import { useEffect } from "react";
import { DatePicker, Form, Input, InputNumber, Modal, Select } from "antd";
import dayjs from "dayjs";
import type { SalaryRecord } from "./types";

export interface EmployeeOption {
  id: number;
  emp_no: string;
  name: string;
}

interface Props {
  open: boolean;
  initial: SalaryRecord | null;
  employees: EmployeeOption[];
  onCancel: () => void;
  onSubmit: (record: SalaryRecord) => void;
}

export default function SalaryRecordModal({
  open,
  initial,
  employees,
  onCancel,
  onSubmit,
}: Props) {
  const [form] = Form.useForm();

  useEffect(() => {
    if (!open) return;
    if (initial) {
      form.setFieldsValue({
        ...initial,
        effectiveDate: dayjs(initial.effectiveDate),
      });
    } else {
      form.resetFields();
    }
  }, [open, initial, form]);

  const handleOk = async () => {
    const values = await form.validateFields();
    const employee = employees.find((e) => e.id === values.empId);
    onSubmit({
      empId: values.empId,
      empNo: employee?.emp_no ?? initial?.empNo ?? "",
      empName: employee?.name ?? initial?.empName ?? "",
      year: values.year,
      effectiveDate: values.effectiveDate.format("YYYY-MM-DD"),
      annualSalary: values.annualSalary,
      raiseRate: values.raiseRate ?? null,
      note: values.note ?? null,
    });
  };

  return (
    <Modal
      open={open}
      title={initial ? "연봉 수정" : "연봉 등록"}
      onCancel={onCancel}
      onOk={handleOk}
      okText="확인"
      cancelText="취소"
      destroyOnClose
    >
      <Form form={form} layout="vertical" size="small">
        <Form.Item
          name="empId"
          label="직원"
          rules={[{ required: true, message: "직원을 선택하세요" }]}
        >
          <Select
            showSearch
            optionFilterProp="label"
            disabled={initial !== null}
            options={employees.map((e) => ({
              value: e.id,
              label: `${e.name} (${e.emp_no})`,
            }))}
          />
        </Form.Item>
        <Form.Item
          name="year"
          label="연도"
          rules={[{ required: true, message: "연도를 입력하세요" }]}
        >
          <InputNumber min={1990} max={2100} style={{ width: "100%" }} />
        </Form.Item>
        <Form.Item
          name="effectiveDate"
          label="적용일"
          rules={[{ required: true, message: "적용일을 선택하세요" }]}
        >
          <DatePicker style={{ width: "100%" }} />
        </Form.Item>
        <Form.Item
          name="annualSalary"
          label="연봉액 (원)"
          rules={[{ required: true, message: "연봉액을 입력하세요" }]}
        >
          <InputNumber
            min={0}
            style={{ width: "100%" }}
            formatter={(v) => `${v}`.replace(/\B(?=(\d{3})+(?!\d))/g, ",")}
            parser={(v) => Number((v ?? "").replace(/,/g, ""))}
          />
        </Form.Item>
        <Form.Item name="raiseRate" label="인상률 (%)">
          <InputNumber step={0.1} style={{ width: "100%" }} />
        </Form.Item>
        <Form.Item name="note" label="비고">
          <Input.TextArea rows={2} maxLength={200} />
        </Form.Item>
      </Form>
    </Modal>
  );
}
```

- [ ] **Step 5: 열림 상태 화면을 구현한다**

`frontend/src/pages/SalaryPage.tsx`의 마지막 블록

```typescript
  // UNLOCKED 상태는 Task 10에서 구현한다.
  return (
    <>
      {header}
      <Card>열림 상태 화면은 다음 작업에서 붙인다.</Card>
    </>
  );
```

를 아래로 교체한다:

```typescript
  return (
    <>
      <Space
        style={{ width: "100%", justifyContent: "space-between", marginBottom: 24 }}
        align="start"
      >
        <Space direction="vertical" size={4}>
          <Title level={3} style={{ margin: 0 }}>
            연봉 관리
          </Title>
          <Text type="secondary">
            열림 · 저장하지 않은 편집은 USB에 반영되지 않습니다.
          </Text>
        </Space>
        <Space>
          <Button onClick={() => vault.lock()}>잠그기</Button>
          <Button
            type="primary"
            disabled={!vault.dirty}
            onClick={() => void vault.save()}
          >
            저장
          </Button>
        </Space>
      </Space>

      {vault.lockCountdown !== null && (
        <Alert
          type="warning"
          showIcon
          style={{ marginBottom: 16 }}
          message={`${vault.lockCountdown}초 후 자동으로 잠깁니다`}
        />
      )}

      {vault.errorMessage && (
        <Alert
          type="error"
          showIcon
          style={{ marginBottom: 16 }}
          message={vault.errorMessage}
        />
      )}

      <Space style={{ marginBottom: 16 }}>
        <Input
          allowClear
          placeholder="직원명 검색"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          style={{ width: 200 }}
        />
        <Button
          onClick={() => {
            setEditing(null);
            setModalOpen(true);
          }}
        >
          + 연봉 등록
        </Button>
      </Space>

      <Table
        size="small"
        rowKey={(r) => `${r.empId}:${r.year}`}
        dataSource={visibleRecords}
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
                <Button
                  size="small"
                  type="link"
                  onClick={() => {
                    setEditing(row);
                    setModalOpen(true);
                  }}
                >
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
                      onOk: () => vault.removeRecord(row.empId, row.year),
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

      <SalaryRecordModal
        open={modalOpen}
        initial={editing}
        employees={employeeOptions}
        onCancel={() => setModalOpen(false)}
        onSubmit={(record) => {
          vault.upsertRecord(record);
          setModalOpen(false);
        }}
      />
    </>
  );
```

파일 상단에 필요한 것을 추가한다:

```typescript
import { Modal, Table } from "antd";
import SalaryRecordModal, { type EmployeeOption } from "../salary/SalaryRecordModal";
import type { SalaryRecord } from "../salary/types";
```

그리고 컴포넌트 안, 기존 `useState` 선언 아래에 추가한다:

```typescript
  const [search, setSearch] = useState("");
  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<SalaryRecord | null>(null);

  const employeeOptions: EmployeeOption[] = [];

  const visibleRecords = vault.records.filter((r) =>
    search ? r.empName.includes(search) : true,
  );
```

`employeeOptions` 자리에는 다음을 넣는다. 위의 빈 배열 선언은 지운다:

```typescript
  const employeesQuery = useEmployees({ page_size: 500 });
  const employeeOptions: EmployeeOption[] = (employeesQuery.data?.items ?? []).map(
    (e) => ({ id: e.id, emp_no: e.emp_no, name: e.name_ko }),
  );
```

import 추가:

```typescript
import { useEmployees } from "../api/employees";
```

테스트에서는 이 훅을 모킹한다. `SalaryPage.test.tsx` 상단에 추가:

```typescript
vi.mock("../../api/employees", () => ({
  useEmployees: () => ({ data: { items: [], total: 0 }, isLoading: false }),
}));
```

- [ ] **Step 6: 테스트가 통과하는지 확인한다**

Run: `cd frontend && npx vitest run src/pages/__tests__/SalaryPage.test.tsx`
Expected: PASS — 9 tests passed

- [ ] **Step 7: 커밋한다**

```bash
git add frontend/src/pages/SalaryPage.tsx frontend/src/salary/SalaryRecordModal.tsx frontend/src/pages/__tests__/SalaryPage.test.tsx
git commit -m "feat(salary): 열림 상태 테이블 + 등록/수정/삭제 + 저장"
```

---

## Task 11: 비밀번호 변경과 담당자 위임

**Files:**
- Create: `frontend/src/salary/DelegateModal.tsx`
- Modify: `frontend/src/pages/SalaryPage.tsx` (헤더에 버튼 2개 추가)
- Create: `frontend/src/salary/__tests__/DelegateModal.test.tsx`

**Interfaces:**
- Consumes: Task 8 `reencrypt`, `suspendAutoLock`
- Produces: `DelegateModal` — `{ open, users, onCancel, onConfirm }`
  - `onConfirm(input: { currentPassword: string; newPassword: string; targetUserId: number | null }): Promise<void>`
  - `targetUserId === null`이면 비밀번호 변경, 값이 있으면 위임

**2단계인 이유:** 전임자가 새 비밀번호를 입력하면 전임자가 그 비밀번호를 알게 되어 위임이 성립하지 않는다 (스펙 §8.1.1).

- [ ] **Step 1: 실패하는 테스트를 작성한다**

`frontend/src/salary/__tests__/DelegateModal.test.tsx`:

```typescript
// @vitest-environment jsdom
/// <reference types="@testing-library/jest-dom/vitest" />
import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import DelegateModal from "../DelegateModal";

const USERS = [
  { id: 7, login_id: "lee", display_name: "이영희" },
  { id: 8, login_id: "park", display_name: "박민수" },
];

describe("DelegateModal", () => {
  it("1단계에서는 새 비밀번호 입력란이 없다", () => {
    render(
      <DelegateModal open users={USERS} onCancel={vi.fn()} onConfirm={vi.fn()} />,
    );
    expect(screen.getByLabelText("현재 비밀번호")).toBeInTheDocument();
    expect(screen.queryByLabelText("새 비밀번호")).not.toBeInTheDocument();
  });

  it("현재 비밀번호가 비어 있으면 다음으로 갈 수 없다", () => {
    render(
      <DelegateModal open users={USERS} onCancel={vi.fn()} onConfirm={vi.fn()} />,
    );
    expect(screen.getByRole("button", { name: "다음" })).toBeDisabled();
  });

  it("2단계로 넘어가면 인계 안내와 새 비밀번호 입력란이 나온다", async () => {
    const user = userEvent.setup();
    render(
      <DelegateModal open users={USERS} onCancel={vi.fn()} onConfirm={vi.fn()} />,
    );

    await user.type(screen.getByLabelText("현재 비밀번호"), "old-password");
    await user.click(screen.getByRole("button", { name: "다음" }));

    expect(screen.getByText(/자리를 넘겨주세요/)).toBeInTheDocument();
    expect(screen.getByLabelText("새 비밀번호")).toBeInTheDocument();
  });

  it("2단계 화면에 1단계 입력값이 남아 있지 않다", async () => {
    const user = userEvent.setup();
    render(
      <DelegateModal open users={USERS} onCancel={vi.fn()} onConfirm={vi.fn()} />,
    );

    await user.type(screen.getByLabelText("현재 비밀번호"), "old-password");
    await user.click(screen.getByRole("button", { name: "다음" }));

    expect(screen.queryByDisplayValue("old-password")).not.toBeInTheDocument();
  });

  it("새 비밀번호 2회가 다르면 완료할 수 없다", async () => {
    const user = userEvent.setup();
    render(
      <DelegateModal open users={USERS} onCancel={vi.fn()} onConfirm={vi.fn()} />,
    );

    await user.type(screen.getByLabelText("현재 비밀번호"), "old-password");
    await user.click(screen.getByRole("button", { name: "다음" }));
    await user.type(screen.getByLabelText("새 비밀번호"), "new-password-1");
    await user.type(screen.getByLabelText("새 비밀번호 확인"), "different");

    expect(screen.getByRole("button", { name: "위임 완료" })).toBeDisabled();
  });

  it("취소하면 onConfirm이 호출되지 않는다", async () => {
    const user = userEvent.setup();
    const onConfirm = vi.fn();
    const onCancel = vi.fn();
    render(
      <DelegateModal open users={USERS} onCancel={onCancel} onConfirm={onConfirm} />,
    );

    await user.type(screen.getByLabelText("현재 비밀번호"), "old-password");
    await user.click(screen.getByRole("button", { name: "다음" }));
    await user.click(screen.getByRole("button", { name: "취소" }));

    expect(onConfirm).not.toHaveBeenCalled();
    expect(onCancel).toHaveBeenCalled();
  });
});
```

- [ ] **Step 2: 테스트가 실패하는지 확인한다**

Run: `cd frontend && npx vitest run src/salary/__tests__/DelegateModal.test.tsx`
Expected: FAIL — `Failed to resolve import "../DelegateModal"`

- [ ] **Step 3: 모달을 구현한다**

`frontend/src/salary/DelegateModal.tsx`:

```typescript
import { useEffect, useState } from "react";
import { Alert, Button, Input, Modal, Select, Space, Typography } from "antd";

const { Title, Paragraph, Text } = Typography;

export interface UserOption {
  id: number;
  login_id: string;
  display_name: string;
}

interface Props {
  open: boolean;
  users: UserOption[];
  /** 위임이 아니라 본인 비밀번호 변경 모드로 연다 */
  passwordChangeOnly?: boolean;
  onCancel: () => void;
  onConfirm: (input: {
    currentPassword: string;
    newPassword: string;
    targetUserId: number | null;
  }) => Promise<void>;
}

const STEP_TIMEOUT_MS = 5 * 60 * 1000;

export default function DelegateModal({
  open,
  users,
  passwordChangeOnly = false,
  onCancel,
  onConfirm,
}: Props) {
  const [step, setStep] = useState<1 | 2>(1);
  const [currentPassword, setCurrentPassword] = useState("");
  const [targetUserId, setTargetUserId] = useState<number | null>(null);
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const reset = () => {
    setStep(1);
    setCurrentPassword("");
    setTargetUserId(null);
    setNewPassword("");
    setConfirmPassword("");
    setSubmitting(false);
  };

  useEffect(() => {
    if (!open) reset();
  }, [open]);

  // 모달이 5분을 넘기면 취소한다. 후임자 입력 중 자동 잠금은 유예되므로,
  // 그 유예가 무기한이 되지 않도록 여기서 상한을 둔다.
  useEffect(() => {
    if (!open) return undefined;
    const timer = setTimeout(() => {
      reset();
      onCancel();
    }, STEP_TIMEOUT_MS);
    return () => clearTimeout(timer);
  }, [open, onCancel]);

  const canGoNext =
    currentPassword.length > 0 &&
    (passwordChangeOnly || targetUserId !== null);

  const canFinish =
    newPassword.length >= 8 && newPassword === confirmPassword && !submitting;

  const targetName =
    users.find((u) => u.id === targetUserId)?.display_name ?? "후임자";

  const handleFinish = async () => {
    setSubmitting(true);
    try {
      await onConfirm({ currentPassword, newPassword, targetUserId });
      reset();
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Modal
      open={open}
      title={passwordChangeOnly ? "비밀번호 변경" : "담당자 위임"}
      onCancel={() => {
        reset();
        onCancel();
      }}
      destroyOnClose
      footer={
        step === 1
          ? [
              <Button
                key="cancel"
                onClick={() => {
                  reset();
                  onCancel();
                }}
              >
                취소
              </Button>,
              <Button
                key="next"
                type="primary"
                disabled={!canGoNext}
                onClick={() => {
                  // 1단계 입력값을 화면에서 지운다. 전임자가 자리를 뜨기 전에
                  // 남은 입력이 보이면 안 된다.
                  setStep(2);
                }}
              >
                다음
              </Button>,
            ]
          : [
              <Button
                key="cancel"
                onClick={() => {
                  reset();
                  onCancel();
                }}
              >
                취소
              </Button>,
              <Button
                key="finish"
                type="primary"
                disabled={!canFinish}
                loading={submitting}
                onClick={() => void handleFinish()}
              >
                {passwordChangeOnly ? "변경 완료" : "위임 완료"}
              </Button>,
            ]
      }
    >
      {step === 1 ? (
        <Space direction="vertical" style={{ width: "100%" }}>
          {!passwordChangeOnly && (
            <>
              <Text>후임 담당자를 선택하세요.</Text>
              <Select
                aria-label="후임자"
                showSearch
                optionFilterProp="label"
                style={{ width: "100%" }}
                value={targetUserId ?? undefined}
                onChange={(v) => setTargetUserId(v)}
                options={users.map((u) => ({
                  value: u.id,
                  label: `${u.display_name} (${u.login_id})`,
                }))}
              />
            </>
          )}
          <Text>본인 확인을 위해 현재 비밀번호를 입력하세요.</Text>
          <Input.Password
            aria-label="현재 비밀번호"
            value={currentPassword}
            onChange={(e) => setCurrentPassword(e.target.value)}
          />
        </Space>
      ) : (
        <Space direction="vertical" style={{ width: "100%" }}>
          {!passwordChangeOnly && (
            <Alert
              type="info"
              showIcon
              message="이제 후임자에게 자리를 넘겨주세요"
              description="아래 비밀번호는 후임자가 직접 입력해야 합니다. 전임자에게 보이지 않습니다."
            />
          )}
          <Title level={5}>
            {passwordChangeOnly
              ? "새 비밀번호를 입력하세요"
              : `${targetName} 님, 새 비밀번호를 입력하세요`}
          </Title>
          <Input.Password
            aria-label="새 비밀번호"
            value={newPassword}
            onChange={(e) => setNewPassword(e.target.value)}
          />
          <Input.Password
            aria-label="새 비밀번호 확인"
            value={confirmPassword}
            onChange={(e) => setConfirmPassword(e.target.value)}
          />
          <Paragraph type="secondary" style={{ fontSize: 12, marginBottom: 0 }}>
            8자 이상. 잃어버리면 복구할 수 없습니다. 완료하면 금고가 즉시 잠기며,
            새 비밀번호로 열리는지 그 자리에서 확인하세요.
          </Paragraph>
        </Space>
      )}
    </Modal>
  );
}
```

- [ ] **Step 4: 테스트가 통과하는지 확인한다**

Run: `cd frontend && npx vitest run src/salary/__tests__/DelegateModal.test.tsx`
Expected: PASS — 6 tests passed

- [ ] **Step 5: `SalaryPage` 헤더에 버튼을 연결한다**

`SalaryPage.tsx`의 열림 상태 헤더 `<Space>` 안, `[잠그기]` 앞에 추가:

```typescript
          <Button
            disabled={vault.dirty}
            onClick={() => {
              setPasswordModalOpen(true);
              vault.suspendAutoLock(true);
            }}
          >
            비밀번호 변경
          </Button>
          <Button
            disabled={vault.dirty}
            onClick={() => {
              setDelegateModalOpen(true);
              vault.suspendAutoLock(true);
            }}
          >
            담당자 위임
          </Button>
```

컴포넌트 상단 state에 추가:

```typescript
  const [passwordModalOpen, setPasswordModalOpen] = useState(false);
  const [delegateModalOpen, setDelegateModalOpen] = useState(false);
```

열림 상태 `return`의 `</>` 직전에 추가:

```typescript
      <DelegateModal
        open={passwordModalOpen}
        passwordChangeOnly
        users={[]}
        onCancel={() => {
          setPasswordModalOpen(false);
          vault.suspendAutoLock(false);
        }}
        onConfirm={async ({ newPassword }) => {
          await vault.reencrypt(newPassword);
          setPasswordModalOpen(false);
          vault.suspendAutoLock(false);
        }}
      />

      <DelegateModal
        open={delegateModalOpen}
        users={userOptions}
        onCancel={() => {
          setDelegateModalOpen(false);
          vault.suspendAutoLock(false);
        }}
        onConfirm={async ({ newPassword, targetUserId }) => {
          await vault.reencrypt(newPassword, {
            targetUserId: targetUserId ?? undefined,
          });
          setDelegateModalOpen(false);
          vault.suspendAutoLock(false);
          Modal.info({
            title: "위임이 완료되었습니다",
            content:
              "후임자에게 연봉 메뉴 권한이 없다면 관리자 화면에서 부여해야 합니다. " +
              "후임자가 다른 자리를 쓴다면 허용 IP도 갱신해야 합니다.",
          });
        }}
      />
```

`userOptions`는 기존 `GET /api/v1/admin/users`에서 채운다. `AdminUserRow`의 이름 필드는 `name_ko`이며 `null`일 수 있다 (확인 완료):

```typescript
  const usersQuery = useQuery({
    queryKey: ["admin", "users", "for-delegate"],
    queryFn: async () => {
      const { data } = await apiClient.get<{
        items: Array<{ id: number; login_id: string; name_ko: string | null }>;
      }>("/admin/users");
      return data.items;
    },
    enabled: delegateModalOpen,
  });

  const userOptions: UserOption[] = (usersQuery.data ?? []).map((u) => ({
    id: u.id,
    login_id: u.login_id,
    display_name: u.name_ko ?? u.login_id,
  }));
```

import 추가:

```typescript
import { useQuery } from "@tanstack/react-query";
import apiClient from "../api/client";
import DelegateModal, { type UserOption } from "../salary/DelegateModal";
```

**주의:** `GET /admin/users`에는 현재 역할 가드가 없다(스펙 §9.1). 여기서 고치지 않는다. 위임 화면은 이 목록을 이름 표시용으로만 쓰고, 권한 변경에는 쓰지 않는다.

- [ ] **Step 6: 전체 프론트 테스트를 돌린다**

Run: `cd frontend && npx vitest run`
Expected: 전부 통과

- [ ] **Step 7: 커밋한다**

```bash
git add frontend/src/salary/DelegateModal.tsx frontend/src/salary/__tests__/DelegateModal.test.tsx frontend/src/pages/SalaryPage.tsx
git commit -m "feat(salary): 비밀번호 변경 + 담당자 위임 2단계 모달"
```

---

## Task 12: 관리자 화면 — IP 정책과 접근 로그

**Files:**
- Create: `frontend/src/pages/SalaryAdminPage.tsx`
- Create: `frontend/src/pages/__tests__/SalaryAdminPage.test.tsx`

**Interfaces:**
- Consumes: Task 7 `usePolicy`, `useUpsertPolicy`, `useAccessLogs`, `usePolicyCheck`
- Produces: `export default function SalaryAdminPage()`

"누가 열 수 있는가"와 "누가 열었는가"는 같은 자리에서 봐야 판단이 되므로 한 화면에 둔다.

- [ ] **Step 1: 실패하는 테스트를 작성한다**

`frontend/src/pages/__tests__/SalaryAdminPage.test.tsx`:

```typescript
// @vitest-environment jsdom
/// <reference types="@testing-library/jest-dom/vitest" />
import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import SalaryAdminPage from "../SalaryAdminPage";
import { useAuthStore } from "../../store/auth";

const mocks = vi.hoisted(() => ({
  policy: null as { allowed_ip: string; owner_user_id: number } | null,
  check: { allowed: true, current_ip: "192.0.2.10", configured: false, reason: null },
  upsert: vi.fn(),
  logs: [
    {
      id: 1,
      user_id: 2,
      action: "IP_DENIED",
      target_user_id: null,
      record_count: null,
      ip_address: "192.0.2.10",
      user_agent: "Chrome",
      occurred_at: "2026-08-19T01:00:00",
    },
  ],
}));

vi.mock("../../api/salaryPolicy", () => ({
  usePolicy: () => ({ data: mocks.policy, isLoading: false }),
  usePolicyCheck: () => ({ data: mocks.check, isLoading: false }),
  useUpsertPolicy: () => ({ mutateAsync: mocks.upsert, isPending: false }),
}));

vi.mock("../../api/salaryAudit", () => ({
  useAccessLogs: () => ({
    data: { items: mocks.logs, total: 1 },
    isLoading: false,
  }),
}));

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <SalaryAdminPage />
    </QueryClientProvider>,
  );
}

describe("SalaryAdminPage", () => {
  it("SYSTEM_ADMIN이 아니면 권한 없음을 보여준다", () => {
    useAuthStore.setState({ roles: ["HR_ADMIN"] });
    renderPage();
    expect(screen.getByText(/권한이 없습니다/)).toBeInTheDocument();
  });

  it("정책 미설정이면 경고를 보여준다", () => {
    useAuthStore.setState({ roles: ["SYSTEM_ADMIN"] });
    mocks.policy = null;
    renderPage();
    expect(screen.getByText(/허용 IP가 설정되지 않았습니다/)).toBeInTheDocument();
  });

  it("현재 접속 IP로 설정 버튼이 입력란을 채운다", async () => {
    const user = userEvent.setup();
    useAuthStore.setState({ roles: ["SYSTEM_ADMIN"] });
    mocks.policy = null;
    renderPage();

    await user.click(screen.getByRole("button", { name: /현재 접속 IP로 설정/ }));
    expect(screen.getByLabelText("허용 IP")).toHaveValue("192.0.2.10");
  });

  it("접근 로그를 보여주고 IP_DENIED를 표시한다", () => {
    useAuthStore.setState({ roles: ["SYSTEM_ADMIN"] });
    renderPage();
    expect(screen.getByText("IP_DENIED")).toBeInTheDocument();
    expect(screen.getByText("192.0.2.10")).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: 테스트가 실패하는지 확인한다**

Run: `cd frontend && npx vitest run src/pages/__tests__/SalaryAdminPage.test.tsx`
Expected: FAIL — `Failed to resolve import "../SalaryAdminPage"`

- [ ] **Step 3: 화면을 구현한다**

`frontend/src/pages/SalaryAdminPage.tsx`:

```typescript
import { useEffect, useState } from "react";
import {
  Alert,
  Button,
  Card,
  Empty,
  Input,
  InputNumber,
  Space,
  Table,
  Tag,
  Typography,
  message,
} from "antd";
import { useAuthStore } from "../store/auth";
import { usePolicy, usePolicyCheck, useUpsertPolicy } from "../api/salaryPolicy";
import { useAccessLogs, type AccessLogRow } from "../api/salaryAudit";

const { Title, Text } = Typography;

export default function SalaryAdminPage() {
  const roles = useAuthStore((s) => s.roles);
  const policyQuery = usePolicy();
  const checkQuery = usePolicyCheck();
  const upsert = useUpsertPolicy();
  const logsQuery = useAccessLogs({});

  const [allowedIp, setAllowedIp] = useState("");
  const [ownerUserId, setOwnerUserId] = useState<number | null>(null);

  useEffect(() => {
    if (policyQuery.data) {
      setAllowedIp(policyQuery.data.allowed_ip);
      setOwnerUserId(policyQuery.data.owner_user_id);
    }
  }, [policyQuery.data]);

  if (!roles.includes("SYSTEM_ADMIN")) {
    return (
      <Card>
        <Empty description="연봉 접근 관리 권한이 없습니다." />
      </Card>
    );
  }

  const handleSave = async () => {
    if (ownerUserId === null) {
      message.error("담당자 사용자 ID를 입력하세요");
      return;
    }
    try {
      await upsert.mutateAsync({
        owner_user_id: ownerUserId,
        allowed_ip: allowedIp,
      });
      message.success("허용 IP를 저장했습니다");
    } catch (error) {
      const detail = (error as { response?: { data?: { detail?: string } } })
        ?.response?.data?.detail;
      message.error(detail ?? "저장에 실패했습니다");
    }
  };

  const columns = [
    { title: "일시", dataIndex: "occurred_at", key: "occurred_at" },
    { title: "사용자", dataIndex: "user_id", key: "user_id" },
    {
      title: "동작",
      dataIndex: "action",
      key: "action",
      render: (v: string) =>
        v === "IP_DENIED" ? <Tag color="red">{v}</Tag> : <Tag>{v}</Tag>,
    },
    { title: "IP", dataIndex: "ip_address", key: "ip_address" },
    {
      title: "건수",
      dataIndex: "record_count",
      key: "record_count",
      align: "right" as const,
      render: (v: number | null) => v ?? "-",
    },
    {
      title: "후임자",
      dataIndex: "target_user_id",
      key: "target_user_id",
      render: (v: number | null) => v ?? "-",
    },
  ];

  return (
    <Space direction="vertical" size={32} style={{ width: "100%" }}>
      <div>
        <Title level={3} style={{ margin: 0 }}>
          연봉 접근 관리
        </Title>
        <Text type="secondary">
          누가 열 수 있는지와 누가 열었는지를 함께 확인합니다.
        </Text>
      </div>

      <Card title="허용 IP 정책">
        <Space direction="vertical" style={{ width: "100%" }} size={16}>
          {!policyQuery.data && (
            <Alert
              type="warning"
              showIcon
              message="허용 IP가 설정되지 않았습니다"
              description="설정 전까지는 모든 IP에서 연봉 금고를 열 수 있습니다."
            />
          )}
          <Space wrap>
            <label>
              담당자 사용자 ID{" "}
              <InputNumber
                aria-label="담당자 사용자 ID"
                value={ownerUserId ?? undefined}
                onChange={(v) => setOwnerUserId(v ?? null)}
              />
            </label>
            <label>
              허용 IP{" "}
              <Input
                aria-label="허용 IP"
                style={{ width: 200 }}
                value={allowedIp}
                onChange={(e) => setAllowedIp(e.target.value)}
              />
            </label>
            <Button
              onClick={() => setAllowedIp(checkQuery.data?.current_ip ?? "")}
            >
              현재 접속 IP로 설정 ({checkQuery.data?.current_ip ?? "확인 불가"})
            </Button>
            <Button
              type="primary"
              loading={upsert.isPending}
              onClick={() => void handleSave()}
            >
              저장
            </Button>
          </Space>
          <Text type="secondary" style={{ fontSize: 12 }}>
            담당자 PC에 고정 IP가 할당되어 있어야 합니다. DHCP로 IP가 바뀌면
            담당자가 금고를 열 수 없습니다.
          </Text>
        </Space>
      </Card>

      <Card title="접근 기록">
        <Table<AccessLogRow>
          size="small"
          rowKey="id"
          loading={logsQuery.isLoading}
          dataSource={logsQuery.data?.items ?? []}
          columns={columns}
          pagination={{ pageSize: 20 }}
        />
      </Card>
    </Space>
  );
}
```

- [ ] **Step 4: 테스트가 통과하는지 확인한다**

Run: `cd frontend && npx vitest run src/pages/__tests__/SalaryAdminPage.test.tsx`
Expected: PASS — 4 tests passed

- [ ] **Step 5: 커밋한다**

```bash
git add frontend/src/pages/SalaryAdminPage.tsx frontend/src/pages/__tests__/SalaryAdminPage.test.tsx
git commit -m "feat(salary): 관리자 화면 — IP 정책 설정 + 접근 로그 조회"
```

---

## Task 13: 메뉴와 라우트 등록

**Files:**
- Modify: `frontend/src/shell/menuRegistry.ts`
- Modify: `frontend/src/App.tsx`

**Interfaces:**
- Consumes: Task 9~12의 `SalaryPage`, `SalaryAdminPage`
- Produces: `/salary`, `/admin/salary-access` 경로

- [ ] **Step 1: 메뉴에 항목을 추가한다**

`frontend/src/shell/menuRegistry.ts`의 `인사` 도메인 `groups` 배열에 새 그룹을 추가한다. `hr-mgmt` 그룹 다음에 넣는다:

```typescript
      {
        key: "salary",
        label: "연봉관리",
        items: [
          {
            path: "/salary",
            label: "연봉관리",
            icon: "Solution",
            keywords: ["salary", "연봉", "급여", "vault"],
            roles: ["SYSTEM_ADMIN", "HR_ADMIN"],
          },
        ],
      },
```

`관리` 도메인의 `admin` 그룹 `items` 끝에 추가:

```typescript
          {
            path: "/admin/salary-access",
            label: "연봉접근관리",
            icon: "Setting",
            keywords: ["salary", "연봉", "ip", "감사"],
            roles: ["SYSTEM_ADMIN"],
          },
```

- [ ] **Step 2: 경로 접두사 매핑을 추가한다**

같은 파일의 `PATH_PREFIX_TO_GNB` 배열에 추가한다. `/admin`보다 먼저 오도록 `/salary`를 넣는다:

```typescript
  ["/salary", "인사"],
```

`/admin/salary-access`는 기존 `["/admin", "관리"]` 매핑이 처리하므로 따로 넣지 않는다. 배열에 `["/admin", "관리"]`가 없으면 추가한다. 확인:

```bash
grep -n "PATH_PREFIX_TO_GNB" -A 15 frontend/src/shell/menuRegistry.ts
```

- [ ] **Step 3: 라우트를 등록한다**

`frontend/src/App.tsx`의 lazy import 목록에 추가:

```typescript
const SalaryPage = lazy(() => import("./pages/SalaryPage"));
const SalaryAdminPage = lazy(() => import("./pages/SalaryAdminPage"));
```

`<Routes>` 안, `/admin/*` 라우트 근처에 추가:

```typescript
                    <Route path="/salary" element={<SalaryPage />} />
                    <Route path="/admin/salary-access" element={<SalaryAdminPage />} />
```

역할 검사는 페이지 컴포넌트 안에서 한다. 이 프로젝트의 `App.tsx`에는 역할 기반 라우트 가드가 없다.

- [ ] **Step 4: 타입 체크와 빌드를 확인한다**

Run: `cd frontend && npx tsc --noEmit && npm run build`
Expected: 0 errors, 빌드 성공

- [ ] **Step 5: 전체 테스트를 돌린다**

```bash
cd frontend && npx vitest run
cd ../backend && python -m pytest -q
```

Expected: 양쪽 모두 전부 통과

- [ ] **Step 6: 커밋한다**

```bash
git add frontend/src/shell/menuRegistry.ts frontend/src/App.tsx
git commit -m "feat(salary): /salary · /admin/salary-access 메뉴와 라우트 등록"
```

---

## Task 14: 브라우저 E2E 검증

**Files:** 없음 (수동 검증)

이 작업은 코드를 만들지 않는다. 자동 테스트로는 확인할 수 없는 것을 실제 브라우저와 USB로 확인한다.

- [ ] **Step 1: 마이그레이션을 적용한다**

```bash
cd backend && alembic upgrade head
```

Expected: `insa_salary_access_log`, `insa_salary_vault_policy` 생성

- [ ] **Step 2: 서버를 띄운다**

```bash
cd backend && uvicorn app.main:app --reload
cd frontend && npm run dev
```

- [ ] **Step 3: 다음 항목을 순서대로 확인한다**

Chrome에서 `HR_ADMIN`으로 로그인해 `/salary`로 이동한다.

- [ ] USB 폴더를 선택하고 새 금고를 만들면 USB에 `salary.enc`가 생긴다
- [ ] 연봉 1건을 등록하고 저장하면 `salary.enc.bak`이 함께 생긴다
- [ ] `.bak`의 수정 시각이 `salary.enc`보다 **앞선다**
- [ ] 브라우저를 새로고침하면 잠김 상태로 뜨고, 권한 재승인 1클릭 후 비밀번호로 열린다
- [ ] 틀린 비밀번호를 넣으면 열리지 않는다
- [ ] 10분간 아무 조작도 하지 않으면 잠긴다 (테스트 시 `AUTO_LOCK_MS`를 임시로 줄여 확인해도 된다. 확인 후 반드시 되돌린다)
- [ ] 잠긴 상태에서 개발자도구 Elements에서 연봉 금액 문자열이 검색되지 않는다
- [ ] 네트워크 탭에서 연봉 금액·직원명이 전송되지 않는다 — `access-logs` 요청 본문에 `action`과 `record_count`만 있다
- [ ] 담당자 위임 2단계가 동작하고, 완료 후 즉시 잠기며, **옛 비밀번호로는 열리지 않는다**
- [ ] `SYSTEM_ADMIN`으로 `/admin/salary-access`에서 허용 IP를 다른 값으로 설정하면, `/salary`에서 거부 화면이 뜨고 비밀번호 입력란이 나오지 않는다
- [ ] 그 거부 시도가 접근 기록에 `IP_DENIED`로 남는다
- [ ] `[현재 접속 IP로 설정]`으로 되돌리면 다시 열린다

- [ ] **Step 4: 발견한 문제를 수정하고 커밋한다**

문제가 없으면 이 작업은 커밋 없이 끝난다.

---

## Self-Review 결과

**스펙 커버리지 확인** — 스펙 각 절을 어느 작업이 구현하는지:

| 스펙 절 | 작업 |
|---|---|
| §4 파일 포맷 | Task 1 |
| §5 암호화 | Task 1 |
| §6.1 crypto.ts | Task 1 |
| §6.2 vault.ts | Task 2 |
| §6.3 useSalaryVault | Task 8 |
| §7 상태 기계 | Task 8, 9 |
| §8 레이아웃 | Task 9, 10 |
| §8.1 비밀번호 변경·위임 | Task 11 |
| §9 권한 | Task 4, 6, 9, 12 |
| §9.2 IP 제한 | Task 5, 6, 9, 12 |
| §10 감사 로그 | Task 3, 4, 12 |
| §11 에러 처리 | Task 8, 9 전반 |
| §12 테스트 | 각 작업의 TDD 단계 |
| §13 구현 단계 | Task 1~14 |
| §16 보안 체크리스트 | Task 14 |

**확인을 마친 사실**

- Pydantic **2.11.1** — `ConfigDict(from_attributes=True)`와 `model_validate`가 맞다
- `models.py`가 이미 `Boolean`·`func`를 import하고 있다
- `useEmployees(params)` → `{ items: Employee[]; total; page; page_size }`, 이름 필드는 `name_ko`
- `AdminUserRow`의 이름 필드는 `name_ko` (nullable)
- `backend/tests/conftest.py`에는 `HR_ADMIN` 픽스처만 있다 → Task 4에서 `SYSTEM_ADMIN`·`EMPLOYEE` 픽스처를 추가한다
- 최신 Alembic revision은 `20260506_0001`

**남은 위험 1가지**

**Task 6의 `test_check_allows_from_matching_ip`** — FastAPI `TestClient`가 보고하는 클라이언트 IP가 `testclient`라는 비-IP 문자열일 수 있다. 그 경우 `PolicyUpsert`의 `ipaddress` 검증이 422로 막는다. Task 6 Step 6에 대처법(conftest의 `client` 픽스처에 `TestClient(app, client=("127.0.0.1", 123))` 지정)을 적어 두었다.

**의도적으로 하지 않는 것**

`backend/app/api/v1/admin.py`의 `require_roles` 가드 부재는 이 계획에서 고치지 않는다. 본 기능 이전부터 있던 별도 결함이고, 이 설계는 그 API에 의존하지 않도록 만들어졌다 (스펙 §9.1, §14).
