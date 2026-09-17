import { describe, expect, it, vi } from "vitest";
import { act, renderHook, waitFor } from "@testing-library/react";
import { useCallback } from "react";
import { useAsyncResource } from "./useAsyncResource.js";

describe("useAsyncResource", () => {
  it("loads on mount and exposes the resolved data", async () => {
    const loader = vi.fn().mockResolvedValue(["a", "b"]);
    const { result } = renderHook(() => useAsyncResource<string[]>([], loader));

    expect(result.current.data).toEqual([]);
    expect(result.current.loading).toBe(true);

    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.data).toEqual(["a", "b"]);
    expect(result.current.error).toBe("");
    expect(loader).toHaveBeenCalledTimes(1);
  });

  it("stores a fallback message on failure and keeps the previous data", async () => {
    const loader = vi.fn().mockRejectedValue(new Error("boom"));
    const { result } = renderHook(() =>
      useAsyncResource<string[]>(["stale"], loader, "Yüklenemedi."),
    );

    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.error).toBe("boom");
    expect(result.current.data).toEqual(["stale"]);
  });

  it("uses the fallback message for a non-Error throw", async () => {
    const loader = vi.fn().mockRejectedValue({ unexpected: true });
    const { result } = renderHook(() => useAsyncResource<string[]>([], loader, "Yüklenemedi."));

    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.error).toBe("Yüklenemedi.");
  });

  it("reload() re-invokes the loader and replaces the data", async () => {
    const loader = vi
      .fn()
      .mockResolvedValueOnce(["first"])
      .mockResolvedValueOnce(["second"]);
    const { result } = renderHook(() => useAsyncResource<string[]>([], loader));

    await waitFor(() => expect(result.current.data).toEqual(["first"]));

    await act(async () => {
      await result.current.reload();
    });

    expect(result.current.data).toEqual(["second"]);
    expect(loader).toHaveBeenCalledTimes(2);
  });

  it("re-runs when the memoized loader's identity changes, mirroring a filter-dependent reload", async () => {
    // Mirrors PromptAdminPanel: the caller re-memoizes `loader` with
    // useCallback whenever a filter changes, producing a new function
    // reference only when `filter` itself changes -- this hook must react
    // to that identity change the same way its internal useEffect reacts to
    // any other dependency.
    const { result, rerender } = renderHook(
      ({ filter }) => {
        const loader = useCallback(async () => [filter], [filter]);
        return useAsyncResource<string[]>([], loader);
      },
      { initialProps: { filter: "a" } },
    );

    await waitFor(() => expect(result.current.data).toEqual(["a"]));

    rerender({ filter: "b" });

    await waitFor(() => expect(result.current.data).toEqual(["b"]));
  });

  it("setData/setError expose raw setters for callers that mutate state directly", async () => {
    const loader = vi.fn().mockResolvedValue([]);
    const { result } = renderHook(() => useAsyncResource<string[]>([], loader));

    await waitFor(() => expect(result.current.loading).toBe(false));

    act(() => {
      result.current.setData(["manual"]);
      result.current.setError("manual error");
    });

    expect(result.current.data).toEqual(["manual"]);
    expect(result.current.error).toBe("manual error");
  });
});
