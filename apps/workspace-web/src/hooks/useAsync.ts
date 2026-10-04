import { useCallback, useEffect, useRef, useState } from "react";

export type AsyncState<T> =
  { status: "loading" } | { status: "error"; error: unknown } | { status: "success"; data: T };

/**
 * Runs `load` whenever `key` changes (or `reload` is called), aborting stale
 * requests so a slow response can never overwrite a newer one.
 */
export function useAsync<T>(
  load: (signal: AbortSignal) => Promise<T>,
  key: string,
): { state: AsyncState<T>; reload: () => void; setData: (data: T) => void } {
  const [state, setState] = useState<AsyncState<T>>({ status: "loading" });
  const [nonce, setNonce] = useState(0);
  const loadRef = useRef(load);
  loadRef.current = load;

  useEffect(() => {
    const controller = new AbortController();
    setState({ status: "loading" });
    loadRef.current(controller.signal).then(
      (data) => {
        if (!controller.signal.aborted) setState({ status: "success", data });
      },
      (error: unknown) => {
        if (!controller.signal.aborted) setState({ status: "error", error });
      },
    );
    return () => controller.abort();
  }, [key, nonce]);

  const reload = useCallback(() => setNonce((n) => n + 1), []);
  const setData = useCallback((data: T) => setState({ status: "success", data }), []);
  return { state, reload, setData };
}
