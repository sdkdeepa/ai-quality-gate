import { useEffect, useState } from 'react'
import { ApiError } from '../api/client'

interface FetchState<T> {
  data: T | null
  error: string | null
  loading: boolean
}

/** Runs `fetcher` once on mount (and whenever `deps` change), tracking
 * loading/error/data state — the same three states every page in this
 * dashboard needs, written once instead of five times. */
export function useApiData<T>(fetcher: () => Promise<T>, deps: unknown[] = []): FetchState<T> {
  const [state, setState] = useState<FetchState<T>>({ data: null, error: null, loading: true })

  // This hook intentionally takes `deps` as its own parameter (the same
  // pattern used by e.g. `useAsync`-style hooks) so every page can control
  // its own re-fetch triggers without duplicating this loading/error/data
  // boilerplate; oxlint's exhaustive-deps check can't verify a
  // caller-supplied array, hence the (expected) lint warning below.
  useEffect(() => {
    let cancelled = false
    setState((s) => ({ ...s, loading: true, error: null }))
    fetcher()
      .then((data) => {
        if (!cancelled) setState({ data, error: null, loading: false })
      })
      .catch((err: unknown) => {
        if (cancelled) return
        const message = err instanceof ApiError ? err.detail : (err as Error).message
        setState({ data: null, error: message, loading: false })
      })
    return () => {
      cancelled = true
    }
  }, deps)

  return state
}
