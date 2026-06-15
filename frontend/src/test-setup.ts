import '@testing-library/jest-dom'

// Node 26 exposes an experimental built-in localStorage that is undefined
// without --localstorage-file, shadowing jsdom's window.localStorage.
// Polyfill it here so localStorage-dependent tests work in jsdom environment.
if (typeof localStorage === 'undefined') {
  const store: Record<string, string> = {}
  Object.defineProperty(globalThis, 'localStorage', {
    value: {
      getItem: (key: string) => store[key] ?? null,
      setItem: (key: string, value: string) => { store[key] = value },
      removeItem: (key: string) => { delete store[key] },
      clear: () => { Object.keys(store).forEach(k => delete store[k]) },
      get length() { return Object.keys(store).length },
      key: (n: number) => Object.keys(store)[n] ?? null,
    },
    writable: true,
  })
}
