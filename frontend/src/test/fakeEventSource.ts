// Controllable EventSource stand-in for jsdom (no native EventSource). The hook reads
// `globalThis.EventSource`, so installing this is the only seam needed.

type Listener = (e: MessageEvent) => void

export class FakeEventSource {
  static instances: FakeEventSource[] = []
  static last(): FakeEventSource {
    return FakeEventSource.instances[FakeEventSource.instances.length - 1]
  }
  static reset() {
    FakeEventSource.instances = []
  }

  url: string
  closed = false
  onopen: ((e: Event) => void) | null = null
  onerror: ((e: Event) => void) | null = null
  private listeners = new Map<string, Set<Listener>>()

  constructor(url: string) {
    this.url = url
    FakeEventSource.instances.push(this)
  }

  addEventListener(type: string, fn: Listener) {
    if (!this.listeners.has(type)) this.listeners.set(type, new Set())
    this.listeners.get(type)!.add(fn)
  }

  close() {
    this.closed = true
  }

  // --- test drivers ---
  open() {
    this.onopen?.(new Event('open'))
  }
  error() {
    this.onerror?.(new Event('error'))
  }
  emit(type: string, data: unknown) {
    const payload = { data: JSON.stringify(data) } as MessageEvent
    this.listeners.get(type)?.forEach((fn) => fn(payload))
  }
  emitRaw(type: string, raw: string) {
    const payload = { data: raw } as MessageEvent
    this.listeners.get(type)?.forEach((fn) => fn(payload))
  }
}

export function installFakeEventSource() {
  FakeEventSource.reset()
  ;(globalThis as { EventSource: unknown }).EventSource =
    FakeEventSource as unknown as typeof EventSource
}
