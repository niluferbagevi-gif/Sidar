import { useCallback, useState } from "react";
import { errorMessage } from "../lib/errors.js";

export interface UseAsyncStatusResult {
  loading: boolean;
  setLoading: (value: boolean) => void;
  error: string;
  setError: (value: string) => void;
  /**
   * Convenience wrapper for the "set loading, clear error, run, catch into
   * error, clear loading" cycle previously copy-pasted into every admin
   * panel's load function. Panels with bespoke control flow (abort/debounce/
   * request-sequencing races -- see TenantAdminPanel's loadTenantData) should
   * use the raw loading/error setters directly instead of this wrapper.
   */
  run: <T>(action: () => Promise<T>, fallbackMessage?: string) => Promise<T | undefined>;
}

export function useAsyncStatus(initialLoading = false): UseAsyncStatusResult {
  const [loading, setLoading] = useState(initialLoading);
  const [error, setError] = useState("");

  const run = useCallback(
    async <T,>(action: () => Promise<T>, fallbackMessage?: string): Promise<T | undefined> => {
      setLoading(true);
      setError("");
      try {
        return await action();
      } catch (err: unknown) {
        setError(fallbackMessage === undefined ? errorMessage(err) : errorMessage(err, fallbackMessage));
        return undefined;
      } finally {
        setLoading(false);
      }
    },
    [],
  );

  return { loading, setLoading, error, setError, run };
}
