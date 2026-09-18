// @vitest-environment jsdom
import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AUTO_LOCK_MS, useSalaryVault, WARN_BEFORE_MS } from "../useSalaryVault";
import { loadHandle, readVault, rekeyBackup, vaultExists, writeVault } from "../vault";
import { BACKUP_FILENAME, VAULT_FILENAME } from "../types";
import { decryptVault, encryptVault, VaultDecryptError } from "../crypto";

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
  rekeyBackup: vi.fn().mockResolvedValue(undefined),
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
    expect(result.current.records[0]!.annualSalary).toBe(45_000_000);
  });

  it("저장 중 오류가 나면 errorMessage를 세우고 UNLOCKED·dirty를 유지한다", async () => {
    const { result } = renderHook(() => useSalaryVault());
    await act(async () => {
      await result.current.createVault("password-1234");
    });

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
    expect(result.current.dirty).toBe(true);

    // USB가 저장 도중 뽑히거나 권한이 취소된 상황을 흉내낸다.
    vi.mocked(writeVault).mockRejectedValueOnce(new Error("USB가 분리되었습니다"));

    await act(async () => {
      await result.current.save();
    });

    // ERROR로 바꾸면 전체 화면이 교체되어 저장 못한 편집이 화면에서
    // 사라진 것처럼 보인다. UNLOCKED와 dirty를 유지해 테이블이 그대로
    // 남고, errorMessage로만 실패를 알려야 한다.
    expect(result.current.status).toBe("UNLOCKED");
    expect(result.current.dirty).toBe(true);
    expect(result.current.errorMessage).toBeTruthy();
    expect(result.current.records).toHaveLength(1);
  });

  it("복원 중 vaultExists가 권한 오류로 거부되어도 이후 동작은 정상이다", async () => {
    const notAllowed = Object.assign(new Error("permission revoked"), {
      name: "NotAllowedError",
    });
    vi.mocked(vaultExists).mockRejectedValueOnce(notAllowed);

    const { result } = renderHook(() => useSalaryVault());

    // 마운트 시 복원 effect의 vaultExists 호출이 거부되지만,
    // dirRef.current는 이미 세팅되어 있으므로 createVault는 여전히 성공해야 한다.
    await act(async () => {
      await result.current.createVault("password-1234");
    });

    expect(result.current.status).toBe("UNLOCKED");
  });

  it("복원 중 권한 오류가 나면 DISCONNECTED가 아니라 LOCKED로 남는다", async () => {
    // 브라우저 재시작 후 저장된 핸들의 권한은 "prompt"라 getFileHandle이
    // NotAllowedError로 거부된다. DISCONNECTED로 남기면 살아 있는 금고를 둔 채
    // "새 금고를 만드세요" 화면이 떠서, 권한 재승인 1클릭 경로가 죽는다.
    const notAllowed = Object.assign(new Error("permission revoked"), {
      name: "NotAllowedError",
    });
    vi.mocked(vaultExists).mockRejectedValueOnce(notAllowed);

    const { result } = renderHook(() => useSalaryVault());
    await act(async () => {
      // 복원 effect의 프라미스 체인(loadHandle → vaultExists → catch)을 흘려보낸다.
      await Promise.resolve();
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(result.current.status).toBe("LOCKED");
  });

  it("unlock은 파일 읽기 실패를 삼키지 않고 errorMessage로 남긴다", async () => {
    // USB를 집에 두고 온 상황. void unlock(...)으로 부르므로 여기서 잡지
    // 않으면 [열기]를 눌러도 화면에 아무 일도 일어나지 않는다.
    const { result } = renderHook(() => useSalaryVault());
    vi.mocked(readVault).mockRejectedValueOnce(
      Object.assign(new Error("device not found"), { name: "NotFoundError" }),
    );

    await act(async () => {
      await result.current.unlock("password-1234");
    });

    expect(result.current.errorMessage).toBeTruthy();
    expect(result.current.status).not.toBe("UNLOCKED");
  });

  it("createVault는 폴더를 고르지 않은 실패를 삼키지 않고 errorMessage로 남긴다", async () => {
    // 처음 쓰는 담당자가 폴더 선택 없이 [새 연봉 금고 만들기]를 누른 경로.
    vi.mocked(loadHandle).mockResolvedValueOnce(null);
    const { result } = renderHook(() => useSalaryVault());

    await act(async () => {
      await result.current.createVault("password-1234");
    });

    expect(result.current.errorMessage).toBeTruthy();
    expect(result.current.status).toBe("DISCONNECTED");
  });

  /**
   * 이 두 테스트의 관심사는 반환값이 아니라 "무엇을 근거로 판단했는가"다.
   * 파일을 다시 읽어 후보 비밀번호로 복호해봐야 재인증이 성립한다(§8.1.2).
   * 메모리의 passwordRef와 문자열만 비교하면, 잠금 해제된 채 방치된 화면에서
   * 지나가던 사람이 통과할 수는 없어도, 파일이 이미 다른 키로 바뀐 경우를
   * 놓친다. readVault·decryptVault 호출을 직접 단언해 문자열 비교로 되돌리면
   * 반드시 실패하게 만든다.
   */
  const FILE_BYTES = new Uint8Array([7, 7, 7]);

  it("verifyPassword는 파일을 다시 읽어 후보 비밀번호로 복호해본다", async () => {
    const { result } = renderHook(() => useSalaryVault());
    await act(async () => {
      await result.current.createVault("password-1234");
    });

    // createVault가 남긴 호출 기록을 지운다 — 아래 단언은 verifyPassword가
    // 만든 호출만 본다.
    vi.mocked(readVault).mockClear();
    vi.mocked(decryptVault).mockClear();
    vi.mocked(readVault).mockResolvedValueOnce({
      bytes: FILE_BYTES,
      lastModified: 1_700_000_000_000,
    });

    let ok: boolean | undefined;
    await act(async () => {
      ok = await result.current.verifyPassword("password-1234");
    });

    expect(ok).toBe(true);
    expect(readVault).toHaveBeenCalledTimes(1);
    expect(decryptVault).toHaveBeenCalledWith(FILE_BYTES, "password-1234");
  });

  it("verifyPassword는 복호에 실패하면 false를 주고 던지지 않는다", async () => {
    const { result } = renderHook(() => useSalaryVault());
    await act(async () => {
      await result.current.createVault("password-1234");
    });

    vi.mocked(readVault).mockClear();
    vi.mocked(decryptVault).mockClear();
    vi.mocked(readVault).mockResolvedValueOnce({
      bytes: FILE_BYTES,
      lastModified: 1_700_000_000_000,
    });
    vi.mocked(decryptVault).mockRejectedValueOnce(
      new VaultDecryptError("비밀번호가 올바르지 않거나 파일이 손상되었습니다."),
    );

    let ok: boolean | undefined;
    await act(async () => {
      ok = await result.current.verifyPassword("wrong-password");
    });

    expect(ok).toBe(false);
    // mockRejectedValueOnce가 실제로 소비되었는지까지 확인한다. 문자열 비교
    // 구현에서는 이 준비값이 한 번도 쓰이지 않은 채 테스트가 통과했다.
    expect(readVault).toHaveBeenCalledTimes(1);
    expect(decryptVault).toHaveBeenCalledWith(FILE_BYTES, "wrong-password");
  });

  /**
   * 위임·비밀번호 변경 직후 USB에 남는 두 파일을 함께 본다. writeVault와
   * rekeyBackup을 실제 vault.ts와 같은 규칙으로 흉내내는 파일 저장소를 두어,
   * "salary.enc는 새 키로 열리는데 salary.enc.bak은 옛 키로 열린다"는 이음매
   * 결함을 잡는다. 암호문 대신 `enc:<비밀번호>#<n>` 문자열을 쓰므로 어느 키로
   * 열리는 바이트인지 그대로 읽힌다.
   */
  describe("재암호화 후의 .bak", () => {
    const files = new Map<string, Uint8Array>();
    const decode = (name: string) =>
      new TextDecoder().decode(files.get(name) ?? new Uint8Array());
    let writeCount = 0;

    beforeEach(() => {
      files.clear();
      writeCount = 0;
      vi.mocked(encryptVault).mockImplementation(async (_payload, password) => {
        writeCount += 1;
        return new TextEncoder().encode(`enc:${password}#${writeCount}`);
      });
      // vault.ts의 writeVault와 같은 순서: .bak ← 직전 원본, 그다음 원본 덮어쓰기
      vi.mocked(writeVault).mockImplementation(async (_dir, bytes) => {
        const previous = files.get(VAULT_FILENAME);
        if (previous) files.set(BACKUP_FILENAME, previous);
        files.set(VAULT_FILENAME, bytes);
      });
      vi.mocked(rekeyBackup).mockImplementation(async (_dir, bytes) => {
        files.set(BACKUP_FILENAME, bytes);
      });
    });

    afterEach(() => {
      vi.mocked(encryptVault).mockReset().mockResolvedValue(new Uint8Array([1, 2, 3]));
      vi.mocked(writeVault).mockReset().mockResolvedValue(undefined);
      vi.mocked(rekeyBackup).mockReset().mockResolvedValue(undefined);
    });

    it("위임 후 .bak이 옛 비밀번호로 열리는 전체 사본을 남기지 않는다", async () => {
      const { result } = renderHook(() => useSalaryVault());
      await act(async () => {
        await result.current.createVault("old-password");
      });
      expect(decode(VAULT_FILENAME)).toBe("enc:old-password#1");

      await act(async () => {
        await result.current.reencrypt("new-password", { targetUserId: 7 });
      });

      expect(decode(VAULT_FILENAME)).toBe("enc:new-password#2");
      // 이 줄이 핵심이다. rekeyBackup 호출이 없으면 여기에
      // "enc:old-password#1"이 남아 전임자가 후임자의 USB를 그대로 읽는다.
      expect(decode(BACKUP_FILENAME)).toBe("enc:new-password#2");
      expect(result.current.status).toBe("LOCKED");
    });

    it("비밀번호 변경 후에도 .bak이 옛 비밀번호로 열리지 않는다", async () => {
      const { result } = renderHook(() => useSalaryVault());
      await act(async () => {
        await result.current.createVault("old-password");
      });

      await act(async () => {
        await result.current.reencrypt("changed-password");
      });

      expect(decode(BACKUP_FILENAME)).toBe("enc:changed-password#2");
      expect(result.current.status).toBe("UNLOCKED");
    });

    it("일반 저장의 .bak은 그대로 '저장 직전 원본'이다", async () => {
      const { result } = renderHook(() => useSalaryVault());
      await act(async () => {
        await result.current.createVault("old-password");
      });

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
      await act(async () => {
        await result.current.save();
      });

      // 복구용 한 세대 백업이 저장 경로에서는 유지되어야 한다.
      expect(rekeyBackup).not.toHaveBeenCalled();
      expect(decode(BACKUP_FILENAME)).toBe("enc:old-password#1");
      expect(decode(VAULT_FILENAME)).toBe("enc:old-password#2");
    });
  });
});
