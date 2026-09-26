import { describe, expect, it, vi } from "vitest";
import { ApiError, backoffDelayMs, errorDetail, onWakeStateChange, requestJson } from "../api";

/** A fake clock whose sleep() advances time instantly. */
function fakeClock() {
  let now = 0;
  const sleeps: number[] = [];
  return {
    now: () => now,
    sleep: async (ms: number) => {
      sleeps.push(ms);
      now += ms;
    },
    sleeps,
  };
}

/** Resolve to the ApiError a request rejects with (fails the test if it resolves). */
const failure = (promise: Promise<unknown>): Promise<ApiError> =>
  promise.then(
    () => {
      throw new Error("expected the request to fail");
    },
    (error: unknown) => error as ApiError,
  );

const json = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

describe("backoff", () => {
  it("doubles from 1 s and caps at 10 s", () => {
    expect([0, 1, 2, 3, 4, 5, 9].map(backoffDelayMs)).toEqual([1000, 2000, 4000, 8000, 10000, 10000, 10000]);
  });
});

describe("requestJson wake-up retry", () => {
  it("returns data straight away when the server is awake", async () => {
    const clock = fakeClock();
    const fetchImpl = vi.fn().mockResolvedValue(json(200, { ok: true }));
    await expect(requestJson("/x", {}, { fetchImpl, ...clock })).resolves.toEqual({ ok: true });
    expect(fetchImpl).toHaveBeenCalledTimes(1);
    expect(clock.sleeps).toEqual([]);
  });

  it("retries network errors and bare 502/503 until the server answers", async () => {
    const clock = fakeClock();
    const fetchImpl = vi
      .fn()
      .mockRejectedValueOnce(new TypeError("Failed to fetch"))
      .mockResolvedValueOnce(new Response("Bad Gateway", { status: 502 }))
      .mockResolvedValueOnce(new Response("", { status: 503 }))
      .mockResolvedValueOnce(json(200, { level: 1 }));
    await expect(requestJson("/x", {}, { fetchImpl, ...clock })).resolves.toEqual({ level: 1 });
    expect(fetchImpl).toHaveBeenCalledTimes(4);
    expect(clock.sleeps).toEqual([1000, 2000, 4000]);
  });

  it("gives up with wake_timeout once the 60 s budget would be exceeded", async () => {
    const clock = fakeClock();
    const fetchImpl = vi.fn().mockRejectedValue(new TypeError("Failed to fetch"));
    const error = await failure(requestJson("/x", {}, { fetchImpl, ...clock }));
    expect(error).toBeInstanceOf(ApiError);
    expect(error.kind).toBe("wake_timeout");
    // 1+2+4+8+10+10+10+10 = 55 s of waiting; one more 10 s wait would pass 60 s.
    expect(clock.sleeps).toEqual([1000, 2000, 4000, 8000, 10000, 10000, 10000, 10000]);
    expect(fetchImpl).toHaveBeenCalledTimes(9);
  });

  it("does NOT retry LEHAR's own 503 (a JSON error body means the app is awake)", async () => {
    const clock = fakeClock();
    const fetchImpl = vi
      .fn()
      .mockResolvedValue(json(503, { error: "http_error", detail: "FLOOD_DL_ENABLED is false.", status_code: 503 }));
    const error = await failure(requestJson("/flood/forecast/Multan", {}, { fetchImpl, ...clock }));
    expect(error).toBeInstanceOf(ApiError);
    expect(error.kind).toBe("http");
    expect(error.status).toBe(503);
    expect(error.detail).toBe("FLOOD_DL_ENABLED is false.");
    expect(fetchImpl).toHaveBeenCalledTimes(1);
  });

  it("does not retry client errors", async () => {
    const clock = fakeClock();
    const fetchImpl = vi.fn().mockResolvedValue(json(404, { error: "http_error", detail: "Unknown district: X", status_code: 404 }));
    const error = await failure(requestJson("/x", {}, { fetchImpl, ...clock }));
    expect(error.status).toBe(404);
    expect(fetchImpl).toHaveBeenCalledTimes(1);
  });

  it("flips the shared waking state on while retrying and off afterwards", async () => {
    const clock = fakeClock();
    const states: boolean[] = [];
    const unsubscribe = onWakeStateChange((waking) => states.push(waking));
    const fetchImpl = vi.fn().mockRejectedValueOnce(new TypeError("Failed to fetch")).mockResolvedValueOnce(json(200, {}));
    await requestJson("/x", {}, { fetchImpl, ...clock });
    unsubscribe();
    expect(states).toEqual([false, true, false]);
  });
});

describe("errorDetail", () => {
  it("reads string details and flattens 422 validation lists", () => {
    expect(errorDetail({ detail: "nope" }, "fallback")).toBe("nope");
    expect(
      errorDetail({ detail: [{ loc: ["body", "min_level"], msg: "Input should be less than or equal to 5" }] }, "fallback"),
    ).toBe("min_level: Input should be less than or equal to 5");
    expect(errorDetail("plain text", "fallback")).toBe("fallback");
  });
});
