import { useCallback, useEffect, useRef, useState } from "react";

/**
 * Petit hook de lecture : annule la requête précédente quand une nouvelle part
 * (ou au démontage) — plus de réponses reçues dans le désordre — et conserve
 * les dernières données valides si une requête échoue.
 */
export function useApi<T>(fetcher: (signal: AbortSignal) => Promise<T>, deps: unknown[]) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const ctrl = useRef<AbortController | null>(null);
  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;

  const reload = useCallback(async () => {
    ctrl.current?.abort();
    const c = new AbortController();
    ctrl.current = c;
    setLoading(true);
    setError(null);
    try {
      const result = await fetcherRef.current(c.signal);
      if (c.signal.aborted) return;
      setData(result);
    } catch (e) {
      if (c.signal.aborted) return;
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      if (ctrl.current === c) setLoading(false);
    }
  }, []);

  useEffect(() => {
    void reload();
    return () => ctrl.current?.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  return { data, error, loading, reload };
}
