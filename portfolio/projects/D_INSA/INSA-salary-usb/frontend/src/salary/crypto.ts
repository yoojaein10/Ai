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
    { name: "PBKDF2", salt: salt.slice(), iterations, hash: "SHA-256" },
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
      { name: "AES-GCM", iv: iv.slice(), additionalData: header.slice(), tagLength: 128 },
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
        iv: header.iv.slice(),
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
