import {
  useCallback,
  useEffect,
  useState,
  type Dispatch,
  type SetStateAction,
} from "react";
import { useAsyncStatus } from "./useAsyncStatus.js";

export interface UseAsyncResourceResult<T> {
  data: T;
  setData: Dispatch<SetStateAction<T>>;
  loading: boolean;
  error: string;
  setError: (value: string) => void;
  reload: () => Promise<void>;
}

/**
 * Loads a resource on mount (and whenever `loader`'s identity changes --
 * memoize it with useCallback and its own dependency list, same as any
 * other effect dependency) via the shared useAsyncStatus loading/error
 * cycle, and exposes `reload()` for a manual refresh button.
 *
 * Extracted from the identical "items useState + useAsyncStatus + load
 * callback + mount effect" skeleton copy-pasted across
 * PluginMarketplacePanel/PromptAdminPanel/OperationsQaPanel: each one hand-
 * rolled `const [items, setItems] = useState(...)`, a `loadX` useCallback
 * that called `run()` and then `setItems(...)`, and a
 * `useEffect(() => { loadX(); }, [loadX])` to trigger it on mount.
 *
 * TenantAdminPanel's loadTenantData is NOT a candidate for this hook: it
 * has its own abort-controller/debounce/request-sequencing race guard
 * across two parallel fetches (see useAsyncStatus's docstring for why it
 * uses the raw loading/error setters instead of `run()`), which this hook
 * doesn't model and shouldn't be forced to.
 */
export function useAsyncResource<T>(
  initialData: T,
  loader: () => Promise<T>,
  fallbackMessage?: string,
): UseAsyncResourceResult<T> {
  const [data, setData] = useState<T>(initialData);
  const { loading, error, setError, run } = useAsyncStatus(true);

  const reload = useCallback(async () => {
    await run(async () => {
      const result = await loader();
      setData(result);
    }, fallbackMessage);
  }, [fallbackMessage, loader, run]);

  useEffect(() => {
    reload();
  }, [reload]);

  return { data, setData, loading, error, setError, reload };
}
