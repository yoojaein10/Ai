// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from "vitest";
import { readVault, rekeyBackup, writeVault, vaultExists } from "../vault";
import { BACKUP_FILENAME, VAULT_FILENAME } from "../types";

/** File System Access API를 흉내내는 최소 구현 */
function makeFakeDir(
  initial: Record<string, Uint8Array> = {},
  options: { failFirstGetFileHandleWith?: string } = {},
) {
  const files = new Map<string, Uint8Array>(Object.entries(initial));
  const writeOrder: string[] = [];
  const failOn = { name: null as string | null };
  let getFileHandleCalls = 0;

  const dir = {
    files,
    writeOrder,
    failOn,
    async getFileHandle(name: string, opts?: { create?: boolean }) {
      getFileHandleCalls += 1;
      // 첫 호출(=vaultExists의 존재 확인 호출)만 지정된 오류로 실패시킨다.
      // 이후 호출(예: writeFile의 create:true 호출)은 정상 동작한다 — 그래야
      // "존재 확인은 실패했지만 실제 쓰기는 진행되는" 버그 경로를 재현할 수 있다.
      if (getFileHandleCalls === 1 && options.failFirstGetFileHandleWith) {
        const err = new Error("permission revoked");
        err.name = options.failFirstGetFileHandleWith;
        throw err;
      }
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

  it("rekeyBackup은 .bak을 새 바이트로 덮어쓰고 원본은 건드리지 않는다", async () => {
    // writeVault 직후의 상태를 흉내낸다: salary.enc는 새 키, .bak은 옛 키.
    const dir = makeFakeDir({
      [VAULT_FILENAME]: new Uint8Array([2, 2, 2]),
      [BACKUP_FILENAME]: new Uint8Array([1, 1, 1]),
    });

    await rekeyBackup(dir, new Uint8Array([2, 2, 2]));

    expect(Array.from(dir.files.get(BACKUP_FILENAME)!)).toEqual([2, 2, 2]);
    expect(Array.from(dir.files.get(VAULT_FILENAME)!)).toEqual([2, 2, 2]);
    // 지우지 않고 덮어쓴다 — 한 세대 복구 수단은 남는다.
    expect(dir.files.has(BACKUP_FILENAME)).toBe(true);
  });

  it("vaultExists의 존재 확인이 권한 오류(NotFoundError가 아님)로 실패하면 writeVault도 실패하고 원본은 그대로 남는다", async () => {
    // salary.enc는 실제로 존재하지만, 첫 getFileHandle 호출(vaultExists의 확인)은
    // NotAllowedError로 실패한다. 이후 호출(writeFile의 create:true)은 정상 동작하므로
    // vaultExists가 오류를 삼키고 false를 반환하는 버그가 있다면, writeVault는 그대로
    // salary.enc를 create:true로 열어 덮어써 버린다 — 그 데이터 파괴를 이 테스트가 잡아낸다.
    const dir = makeFakeDir(
      { [VAULT_FILENAME]: new Uint8Array([1, 1, 1]) },
      { failFirstGetFileHandleWith: "NotAllowedError" },
    );

    let caught: unknown = null;
    try {
      await writeVault(dir, new Uint8Array([2, 2, 2]));
    } catch (error) {
      caught = error;
    }

    // 원본이 파괴되었는지부터 확인한다 — 이 assertion이 먼저 실패해야
    // "예외를 던졌는가"가 아니라 "데이터가 살아남았는가"를 검증하는 테스트가 된다.
    expect(Array.from(dir.files.get(VAULT_FILENAME)!)).toEqual([1, 1, 1]);
    expect(dir.files.has(BACKUP_FILENAME)).toBe(false);
    expect(dir.writeOrder).toEqual([]);
    expect(caught).not.toBeNull();
  });
});
