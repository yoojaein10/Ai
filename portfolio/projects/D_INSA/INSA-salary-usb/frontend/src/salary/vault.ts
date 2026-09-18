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
  } catch (error) {
    if (error instanceof Error && error.name === "NotFoundError") return false;
    throw error;
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
    await writable.write(new Uint8Array(bytes));
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

/**
 * .bak을 새 바이트로 덮어쓴다. 재암호화(비밀번호 변경·담당자 위임)가 끝난
 * 직후에만 쓴다 — writeVault가 남긴 .bak은 "옛 비밀번호로 열리는 완전한
 * 데이터"이므로, 그대로 두면 전임자가 후임자의 USB에서 전체 데이터를 그대로
 * 읽을 수 있다(스펙 §8.1.1·§16). 지우지 않고 덮어쓰는 이유는 한 세대짜리
 * 복구 수단을 유지하기 위해서다 — 새 비밀번호로만 열리는 백업이 된다.
 *
 * 일반 저장(save)에서는 부르지 않는다. 그쪽의 .bak은 "직전 원본"이어야 한다.
 */
export async function rekeyBackup(
  dir: FileSystemDirectoryHandle,
  bytes: Uint8Array,
): Promise<void> {
  await writeFile(dir, BACKUP_FILENAME, bytes);
}
