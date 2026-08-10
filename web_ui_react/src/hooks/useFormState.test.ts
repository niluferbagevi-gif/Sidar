import { describe, expect, it } from "vitest";
import { act, renderHook } from "@testing-library/react";
import { useFormState } from "./useFormState.js";

describe("useFormState", () => {
  it("initializes values from the given initial object", () => {
    const { result } = renderHook(() => useFormState({ name: "Sidar", limit: 10 }));
    expect(result.current[0]).toEqual({ name: "Sidar", limit: 10 });
  });

  it("setField updates a single key without touching the others", () => {
    const { result } = renderHook(() => useFormState({ name: "Sidar", limit: 10 }));
    act(() => {
      result.current[1]("name", "Yeni ad");
    });
    expect(result.current[0]).toEqual({ name: "Yeni ad", limit: 10 });
  });

  it("setField accepts already-coerced values (numbers, booleans)", () => {
    const { result } = renderHook(() => useFormState({ limit: 10, append: true }));
    act(() => {
      result.current[1]("limit", 42);
      result.current[1]("append", false);
    });
    expect(result.current[0]).toEqual({ limit: 42, append: false });
  });

  it("exposes the raw setValues escape hatch for whole-object replacement", () => {
    const { result } = renderHook(() => useFormState({ name: "Sidar" }));
    act(() => {
      result.current[2]({ name: "Reset" });
    });
    expect(result.current[0]).toEqual({ name: "Reset" });
  });
});
