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
    tampered[HEADER_SIZE]! ^= 0xff;
    await expect(decryptVault(tampered, PASSWORD)).rejects.toBeInstanceOf(
      VaultDecryptError,
    );
  });

  it("5. 헤더의 iv를 1바이트 변조하면 AAD 불일치로 실패한다", async () => {
    const bytes = await encryptVault(SAMPLE, PASSWORD);
    const tampered = new Uint8Array(bytes);
    tampered[29]! ^= 0xff;
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
