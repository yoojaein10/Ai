// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from "vitest";
import apiClient from "../../api/client";
import { checkPolicy } from "../../api/salaryPolicy";
import { recordAccess } from "../../api/salaryAudit";

vi.mock("../../api/client", () => ({
  default: {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
  },
}));

/**
 * 이 파일이 지키는 것은 두 개의 의도적인 fail-open 분기다. 둘 다 조용히
 * 반대로 뒤집힐 수 있고, 뒤집히면 급여 업무가 멈춘다(§10.4·§11).
 *
 * - recordAccess: 로그 서버가 죽어도 절대 던지지 않는다. 던지면 잠금 해제·
 *   저장·위임이 통째로 실패한다. 대신 감사 추적이 조용히 끊기므로, "던지지
 *   않는다"는 성질은 반드시 테스트로 고정되어 있어야 한다.
 * - checkPolicy: 정책 서버가 죽으면 허용으로 간주한다. fail-closed로 바뀌면
 *   서버 장애가 곧 급여 마감 중단이 된다.
 */
describe("연봉 fail-open 분기", () => {
  beforeEach(() => {
    vi.mocked(apiClient.get).mockReset();
    vi.mocked(apiClient.post).mockReset();
    vi.spyOn(console, "error").mockImplementation(() => {});
  });

  it("recordAccess는 로그 전송이 실패해도 던지지 않는다", async () => {
    vi.mocked(apiClient.post).mockRejectedValue(new Error("502 Bad Gateway"));

    await expect(recordAccess("OPEN", { recordCount: 3 })).resolves.toBeUndefined();

    // 1회 재시도까지 하고 포기한다 (§10.4).
    expect(apiClient.post).toHaveBeenCalledTimes(2);
  });

  it("recordAccess는 재시도가 성공하면 더 부르지 않는다", async () => {
    vi.mocked(apiClient.post)
      .mockRejectedValueOnce(new Error("timeout"))
      .mockResolvedValueOnce({ data: null });

    await expect(recordAccess("LOCK")).resolves.toBeUndefined();

    expect(apiClient.post).toHaveBeenCalledTimes(2);
  });

  it("checkPolicy는 정책 조회가 실패하면 허용으로 간주한다", async () => {
    vi.mocked(apiClient.get).mockRejectedValue(new Error("network down"));

    const result = await checkPolicy();

    // fail-closed로 뒤집히면 서버 장애가 곧 급여 업무 중단이 된다 (§9.2.1·§11).
    expect(result.allowed).toBe(true);
    expect(result.configured).toBe(false);
    expect(result.reason).toBeTruthy();
  });

  it("checkPolicy는 서버가 거부하면 그 결과를 그대로 전한다", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({
      data: {
        allowed: false,
        current_ip: "192.0.2.10",
        configured: true,
        reason: "허용되지 않은 IP입니다.",
      },
    });

    const result = await checkPolicy();

    expect(result.allowed).toBe(false);
    expect(result.current_ip).toBe("192.0.2.10");
  });
});
