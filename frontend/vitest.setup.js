import '@testing-library/jest-dom/vitest'
import { afterEach } from 'vitest'
import { cleanup } from '@testing-library/react'

// Node 26 hides jsdom's localStorage behind the experimental `--localstorage-file`
// flag. Provide a minimal in-memory shim so tests stay portable.
if (typeof globalThis.localStorage === 'undefined') {
  const store = new Map()
  globalThis.localStorage = {
    getItem: (k) => (store.has(k) ? store.get(k) : null),
    setItem: (k, v) => { store.set(k, String(v)) },
    removeItem: (k) => { store.delete(k) },
    clear: () => { store.clear() },
    key: (i) => Array.from(store.keys())[i] ?? null,
    get length() { return store.size },
  }
}

afterEach(() => {
  cleanup()
  localStorage.clear()
})
