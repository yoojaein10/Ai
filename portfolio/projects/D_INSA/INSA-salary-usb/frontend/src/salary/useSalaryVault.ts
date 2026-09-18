import { useCallback, useEffect, useRef, useState } from "react";
import { recordAccess } from "../api/salaryAudit";
import { decryptVault, encryptVault, VaultDecryptError } from "./crypto";
import { makeEmptyVault, recordKey, type SalaryRecord, type VaultData } from "./types";
import {
  loadHandle,
  pickVaultDirectory,
  readVault,
  rekeyBackup,
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
  /**
   * 마운트 시 폴더 핸들 복원(loadHandle)은 비동기다. dirRef를 읽는 모든
   * 동작은 이 프라미스를 먼저 기다려, 복원이 끝나기 전에 "폴더가 선택되지
   * 않음"으로 오판하는 경쟁 상태를 막는다.
   */
  const restoreRef = useRef<Promise<void>>(Promise.resolve());

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
    restoreRef.current = (async () => {
      const dir = await loadHandle();
      if (!dir) return;
      dirRef.current = dir;
      try {
        setStatus((await vaultExists(dir)) ? "LOCKED" : "DISCONNECTED");
      } catch (error) {
        // vaultExists는 NotFoundError가 아닌 DOM 예외(권한 취소, SecurityError 등)를
        // 그대로 rethrow한다(Task 2 결정). 여기서 삼키지 않으면 restoreRef가 영원히
        // reject된 프라미스로 남아, unlock/persist/save가 매번 그 rejection을 다시
        // 던지며 훅 전체가 멈춘다.
        //
        // 상태는 LOCKED로 둔다. 브라우저를 다시 켜면 저장된 핸들의 권한이
        // "prompt"라 getFileHandle이 NotAllowedError로 거부되는데, 이때
        // DISCONNECTED로 남기면 "폴더에 salary.enc가 없으면 새 금고를 만들 수
        // 있습니다" 화면이 뜬다 — 살아 있는 금고가 든 폴더를 두고 새로 만들라고
        // 권하는 셈이다. 핸들은 분명히 있고 권한만 모르는 상태이므로 ②로 보내,
        // 잠금 해제 화면의 verifyPermission이 "권한 재승인 1클릭"(§7·§11)을
        // 처리하게 한다. 파일이 정말 없다면 vaultExists가 던지지 않고 false를
        // 주므로 이 경로로 오지 않는다.
        console.error("금고 상태 확인에 실패했습니다:", error);
        setStatus("LOCKED");
      }
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

  /**
   * 복호 이전 단계(권한 확인·파일 읽기)의 실패도 여기서 붙잡아 errorMessage로
   * 남긴다. 호출부는 `void unlock(...)`으로 부르므로 거부된 프라미스에 처리기가
   * 붙지 않는다 — USB를 집에 두고 온 담당자가 [열기]를 눌러도 화면에 아무 일도
   * 일어나지 않던 원인이다. save()·reencrypt와 같은 층에서 닫는다.
   */
  const unlock = useCallback(async (password: string) => {
    try {
      await restoreRef.current;
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
    } catch (error) {
      console.error("금고를 열지 못했습니다:", error);
      setErrorMessage(
        "금고를 열지 못했습니다. USB가 연결되어 있고 폴더 접근을 허용했는지 확인하세요.",
      );
    }
  }, []);

  const persist = useCallback(
    async (nextRecords: SalaryRecord[], password: string) => {
      await restoreRef.current;
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
      return bytes;
    },
    [],
  );

  /**
   * 폴더를 고르지 않은 채 [새 연봉 금고 만들기]를 누르면 persist가 던진다.
   * 호출부가 `void`로 부르므로 그대로 두면 화면에 아무 변화가 없다 — 처음
   * 쓰는 담당자가 가장 먼저 마주치는 경로다. unlock·save와 같은 층에서 붙잡는다.
   */
  const createVault = useCallback(
    async (password: string) => {
      try {
        const empty = makeEmptyVault(new Date().toISOString());
        await persist(empty.records, password);
        passwordRef.current = password;
        lastActivityRef.current = Date.now();
        setRecords([]);
        setDirty(false);
        setErrorMessage(null);
        setStatus("UNLOCKED");
        void recordAccess("CREATE_VAULT", { recordCount: 0 });
      } catch (error) {
        console.error("새 금고를 만들지 못했습니다:", error);
        setErrorMessage(
          "새 금고를 만들지 못했습니다. 먼저 USB 폴더를 선택했는지 확인하세요.",
        );
      }
    },
    [persist],
  );

  const save = useCallback(async () => {
    await restoreRef.current;
    const dir = dirRef.current;
    const password = passwordRef.current;
    if (!dir || !password) throw new Error("금고가 열려 있지 않습니다");

    try {
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
      setErrorMessage(null);
      void recordAccess("SAVE", { recordCount: records.length });
    } catch (error) {
      // USB 권한 취소, 강제 분리, I/O 오류 등 예상치 못한 실패다. status를
      // ERROR로 바꾸면 화면 전체가 교체되어 저장하지 못한 편집이 화면에서
      // 사라지는 것처럼 보인다(Task 10 리뷰 지적). UNLOCKED와 dirty를
      // 유지해 테이블이 그대로 남고, 사용자는 errorMessage를 보고 재시도할
      // 수 있다.
      console.error("저장에 실패했습니다:", error);
      setErrorMessage(
        "저장에 실패했습니다. 편집 내용은 화면에 남아 있습니다. USB 연결을 확인하고 다시 시도하세요.",
      );
    }
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
      const bytes = await persist(records, newPassword);
      passwordRef.current = newPassword;

      // writeVault가 방금 만든 .bak은 "옛 비밀번호로 열리는 완전한 데이터"다.
      // 위임이라면 그 USB를 그대로 후임자가 들고 가므로, 전임자가 아무것도
      // 복사하지 않고 스펙 §15.5를 그대로 따라도 옛 비밀번호로 전체를 읽을 수
      // 있다 — §8.1.1의 권한 회수와 §16 체크리스트가 성립하지 않는다.
      // 새 바이트로 덮어써서 백업은 남기되 새 비밀번호로만 열리게 한다.
      // passwordRef를 먼저 갱신해 두는 것은, 여기서 실패하더라도 메모리의
      // 비밀번호가 파일과 어긋나지 않게 하기 위해서다(재시도가 자기 치유된다).
      const dir = dirRef.current;
      if (!dir) throw new Error("USB 폴더가 선택되지 않았습니다");
      await rekeyBackup(dir, bytes);

      if (opts?.targetUserId !== undefined) {
        void recordAccess("DELEGATE", { targetUserId: opts.targetUserId });
        lock();
      } else {
        void recordAccess("PASSWORD_CHANGE");
      }
    },
    [dirty, records, persist, lock],
  );

  /**
   * 비밀번호 변경·위임 1단계 재인증에 쓴다. 메모리에 든 passwordRef와
   * 비교하지 않고, 실제 파일을 다시 복호해본다 — 스펙 §8.1.2 "복호에
   * 성공해야만 다음 단계로 간다". 화면이 잠금 해제된 채 방치된 상태에서
   * 지나가던 사람이 아무 값이나 넣고 통과하는 것을 막는 게 목적이므로,
   * in-memory 문자열 비교로는 그 목적을 달성할 수 없다.
   * 비밀번호가 틀리면 false, 그 외 오류(파일 접근 실패 등)는 그대로 던진다.
   */
  const verifyPassword = useCallback(async (candidate: string): Promise<boolean> => {
    await restoreRef.current;
    const dir = dirRef.current;
    if (!dir) throw new Error("USB 폴더가 선택되지 않았습니다");
    const file = await readVault(dir);
    try {
      await decryptVault(file.bytes, candidate);
      return true;
    } catch (error) {
      if (error instanceof VaultDecryptError) return false;
      throw error;
    }
  }, []);

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
    verifyPassword,
  };
}
