import { useCallback, useEffect, useRef, useState } from 'react'

interface PolledState<T> {
  key: string
  data: T | null
  loading: boolean
  error: string | null
}

/**
 * Fetch on mount and whenever `key` changes, then re-fetch every `intervalMs`
 * while mounted. `refresh()` fetches again at once (after an action).
 *
 * `load` must be fully determined by `key`: polling restarts when `key`
 * changes, not when `load` does, so callers can pass an inline function. A
 * later success clears an earlier error, and a failed refresh keeps the data
 * already shown.
 */
export function usePolled<T>(
  load: () => Promise<T>,
  key: string,
  intervalMs: number,
) {
  const [state, setState] = useState<PolledState<T>>({
    key,
    data: null,
    loading: true,
    error: null,
  })
  const [refreshCount, setRefreshCount] = useState(0)

  // Always call the caller's latest loader, without restarting the polling
  // every time it passes a new inline function.
  const loadRef = useRef(load)
  useEffect(() => {
    loadRef.current = load
  })

  useEffect(() => {
    let cancelled = false

    const run = () => {
      loadRef
        .current()
        .then((data) => {
          if (!cancelled) setState({ key, data, loading: false, error: null })
        })
        .catch((err: unknown) => {
          if (cancelled) return
          setState((previous) => ({
            key,
            data: previous.key === key ? previous.data : null,
            loading: false,
            error: err instanceof Error ? err.message : String(err),
          }))
        })
    }

    run()
    const interval = setInterval(run, intervalMs)

    return () => {
      cancelled = true
      clearInterval(interval)
    }
  }, [key, intervalMs, refreshCount])

  const refresh = useCallback(() => setRefreshCount((count) => count + 1), [])

  // While the stored state belongs to another key, report loading rather than
  // showing the previous selection's data.
  if (state.key !== key) {
    return { data: null, loading: true, error: null, refresh }
  }
  return {
    data: state.data,
    loading: state.loading,
    error: state.error,
    refresh,
  }
}
