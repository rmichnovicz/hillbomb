import { useState, useEffect, type Dispatch, type SetStateAction } from 'react'

/**
 * useState that mirrors its value to localStorage under `key`, so the setting
 * survives a page refresh. Falls back to `defaultValue` when nothing is stored
 * or the stored JSON is unreadable. Keys are versioned by the caller (e.g.
 * `hillbomb_toggles_v1`) so a schema change can invalidate old data by bumping
 * the suffix.
 */
export function usePersistedState<T>(
  key: string,
  defaultValue: T,
): [T, Dispatch<SetStateAction<T>>] {
  const [value, setValue] = useState<T>(() => {
    try {
      const raw = localStorage.getItem(key)
      if (raw == null) return defaultValue
      return JSON.parse(raw) as T
    } catch {
      return defaultValue
    }
  })

  useEffect(() => {
    try {
      localStorage.setItem(key, JSON.stringify(value))
    } catch {
      // Quota exceeded or private mode — silently ignore
    }
  }, [key, value])

  return [value, setValue]
}
