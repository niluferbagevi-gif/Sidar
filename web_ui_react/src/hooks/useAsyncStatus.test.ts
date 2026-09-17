import { describe, expect, it } from "vitest";
import { act, renderHook } from "@testing-library/react";
import { useAsyncStatus } from "./useAsyncStatus.js";

describe("useAsyncStatus", () => {
  it("starts idle with no error", () => {
    const { result } = renderHook(() => useAsyncStatus());
    expect(result.current.loading).toBe(false);
    expect(result.current.error).toBe("");
  });

  it("honors an explicit initial loading value", () => {
    const { result } = renderHook(() => useAsyncStatus(true));
    expect(result.current.loading).toBe(true);
  });

  it("setLoading/setError expose the raw setters for bespoke control flow", () => {
    const { result } = renderHook(() => useAsyncStatus());
    act(() => {
      result.current.setLoading(true);
      result.current.setError("manual");
    });
    expect(result.current.loading).toBe(true);
    expect(result.current.error).toBe("manual");
  });

  it("run() sets loading while the action is in flight, then clears it", async () => {
    const { result } = renderHook(() => useAsyncStatus());
    let resolveAction: (value: string) => void = () => {};
    const pending = new Promise<string>((resolve) => {
      resolveAction = resolve;
    });

    let runPromise: Promise<string | undefined> = Promise.resolve(undefined);
    act(() => {
      runPromise = result.current.run(() => pending);
    });
    expect(result.current.loading).toBe(true);

    await act(async () => {
      resolveAction("payload");
      await expect(runPromise).resolves.toBe("payload");
    });

    expect(result.current.loading).toBe(false);
    expect(result.current.error).toBe("");
  });

  it("run() clears a stale error before the action starts", async () => {
    const { result } = renderHook(() => useAsyncStatus());
    act(() => {
      result.current.setError("stale error from a previous run");
    });

    await act(async () => {
      await result.current.run(async () => "ok");
    });

    expect(result.current.error).toBe("");
  });

  it("run() without a fallback stores String(error) for a non-Error throw, mirroring errorMessage()", async () => {
    const { result } = renderHook(() => useAsyncStatus());

    await act(async () => {
      const value = await result.current.run(async () => {
        throw "plain string failure";
      });
      expect(value).toBeUndefined();
    });

    expect(result.current.error).toBe("plain string failure");
    expect(result.current.loading).toBe(false);
  });

  it("run() with a fallback uses it for a non-Error throw", async () => {
    const { result } = renderHook(() => useAsyncStatus());

    await act(async () => {
      await result.current.run(async () => {
        throw { unexpected: true };
      }, "Yüklenemedi.");
    });

    expect(result.current.error).toBe("Yüklenemedi.");
  });

  it("run() uses an Error instance's own message regardless of fallback", async () => {
    const { result } = renderHook(() => useAsyncStatus());

    await act(async () => {
      await result.current.run(async () => {
        throw new Error("boom");
      }, "ignored fallback");
    });

    expect(result.current.error).toBe("boom");
  });
});
