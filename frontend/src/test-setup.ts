import '@testing-library/jest-dom'

// jsdom has no canvas backend, so getContext('2d') returns null and logs
// "Not implemented". Chart.js treats that as "can't acquire context" and gives up
// before it constructs any controller — which silently defuses the ProfilePanel
// tests: they'd pass with the chart never actually built. This stub is a no-op
// context that draws nothing but lets Chart.js run its real code path.
const noopContext = (canvas: HTMLCanvasElement) => {
  const measured = { width: 0, actualBoundingBoxAscent: 0, actualBoundingBoxDescent: 0 }
  const gradient = { addColorStop: () => {} }
  const target: Record<string, unknown> = {
    // Chart.js rejects a context whose .canvas isn't the element it asked about,
    // and rejecting it means falling back to the same do-nothing path as null.
    canvas,
    measureText: () => measured,
    createLinearGradient: () => gradient,
    createRadialGradient: () => gradient,
    createPattern: () => null,
    getImageData: () => ({ data: new Uint8ClampedArray(4) }),
    isPointInPath: () => false,
    isPointInStroke: () => false,
  }
  // Everything else Chart.js touches is either a drawing call (no-op) or a style
  // property (store and hand back, so save/restore round-trips behave).
  return new Proxy(target, {
    get(obj, prop) {
      if (prop in obj) return obj[prop as string]
      return (obj[prop as string] = () => {})
    },
    set(obj, prop, value) {
      obj[prop as string] = value
      return true
    },
  })
}

// Chart.js observes its container for resizes. jsdom never lays anything out, so a
// stub that observes nothing is honest as well as sufficient.
if (typeof globalThis.ResizeObserver === 'undefined') {
  globalThis.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver
}

const contexts = new WeakMap<HTMLCanvasElement, unknown>()
HTMLCanvasElement.prototype.getContext = function (this: HTMLCanvasElement, type: string) {
  if (type !== '2d') return null
  if (!contexts.has(this)) contexts.set(this, noopContext(this))
  return contexts.get(this) as CanvasRenderingContext2D
} as HTMLCanvasElement['getContext']

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
