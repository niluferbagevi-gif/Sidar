import { describe, expect, it } from "vitest";
import { errorMessage } from "./errors.js";

describe("errorMessage", () => {
  it("returns the Error instance's message, ignoring any fallback", () => {
    expect(errorMessage(new Error("boom"), "fallback")).toBe("boom");
    expect(errorMessage(new Error("boom"))).toBe("boom");
  });

  it("returns the caller-supplied fallback for a non-Error value", () => {
    expect(errorMessage("not an error", "fallback text")).toBe("fallback text");
    expect(errorMessage({ detail: "nope" }, "fallback text")).toBe("fallback text");
    expect(errorMessage(null, "fallback text")).toBe("fallback text");
  });

  it("stringifies the thrown value when no fallback is supplied", () => {
    expect(errorMessage("plain string")).toBe("plain string");
    expect(errorMessage(404)).toBe("404");
    expect(errorMessage(null)).toBe("null");
    expect(errorMessage(undefined)).toBe("undefined");
  });
});
